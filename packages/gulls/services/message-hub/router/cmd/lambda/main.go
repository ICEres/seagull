package main

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	routecore "seagull/packages/gulls/services/message-hub/router"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/feature/dynamodb/attributevalue"
	"github.com/aws/aws-sdk-go-v2/service/apigatewaymanagementapi"
	apigwtypes "github.com/aws/aws-sdk-go-v2/service/apigatewaymanagementapi/types"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

const connectionTTL = 24 * time.Hour

// resumeBacklogLimit caps a replay. An agent away for a long time could
// otherwise be handed an unbounded backlog on reconnect, which would blow the
// Lambda's time budget and flood the socket. Anything beyond this stays in the
// durable Inbox for the agent to pull.
const resumeBacklogLimit = 100

// isoMillis matches the fixed 3-digit-millisecond layout the Python hub's
// to_iso writes for created_at (storage/dynamodb.py). RFC3339Nano strips
// trailing fractional zeros, which would otherwise make the resume cursor's
// lexicographic comparison against the stored value disagree with real time
// ordering for any instant landing on a whole millisecond, tenth, or second.
const isoMillis = "2006-01-02T15:04:05.000Z"

type handler struct {
	ddb              *dynamodb.Client
	awsConfig        aws.Config
	connectionsTable string
	agentTokensTable string
	deliveriesTable  string
	now              func() time.Time
}

// deliveryRecord is the subset of a stored delivery a resume needs. The hub
// writes the full record from Python; this reads only what a replay carries.
type deliveryRecord struct {
	DeliveryID       string `dynamodbav:"delivery_id"`
	MessageID        string `dynamodbav:"message_id"`
	ThreadID         string `dynamodbav:"thread_id"`
	SenderAgentID    string `dynamodbav:"sender_agent_id"`
	RecipientAgentID string `dynamodbav:"recipient_agent_id"`
	Status           string `dynamodbav:"status"`
	CreatedAt        string `dynamodbav:"created_at"`
}

// dynamoQueryAPI is the subset of *dynamodb.Client dynamoDeliveryStore needs,
// narrowed so tests can supply a fake Query implementation.
type dynamoQueryAPI interface {
	Query(ctx context.Context, params *dynamodb.QueryInput, optFns ...func(*dynamodb.Options)) (*dynamodb.QueryOutput, error)
}

// dynamoDeliveryStore backs routecore.DeliveryStore with the hub's deliveries
// table, querying the recipient-created-at-index the table already carries.
type dynamoDeliveryStore struct {
	ctx   context.Context
	ddb   dynamoQueryAPI
	table string
}

func (s dynamoDeliveryStore) DeliveriesForAgent(agentID string, after time.Time) ([]routecore.Delivery, error) {
	if s.table == "" {
		return nil, errors.New("deliveries table is not configured")
	}

	keyCondition := "recipient_agent_id = :agent"
	values := map[string]types.AttributeValue{
		":agent": &types.AttributeValueMemberS{Value: agentID},
		":acked": &types.AttributeValueMemberS{Value: string(routecore.DeliveryAcked)},
	}
	// Range on created_at so the index does the filtering rather than a scan.
	if !after.IsZero() {
		keyCondition += " AND created_at > :after"
		values[":after"] = &types.AttributeValueMemberS{
			// Round down to millisecond precision so a sub-millisecond cursor
			// can never lexicographically skip a stored row.
			Value: after.UTC().Truncate(time.Millisecond).Format(isoMillis),
		}
	}

	// Acked rows must be dropped server-side, not after Limit has already
	// truncated the page: an agent with more than resumeBacklogLimit lifetime
	// (mostly acked) deliveries would otherwise see the query cut off before
	// it ever reaches the outstanding ones. DynamoDB still applies Limit to
	// items *evaluated* rather than items returned, so the filter alone is not
	// enough -- this pages with ExclusiveStartKey until it has gathered
	// resumeBacklogLimit unacked deliveries or the index is exhausted.
	deliveries := make([]routecore.Delivery, 0, resumeBacklogLimit)
	var startKey map[string]types.AttributeValue
	for {
		out, err := s.ddb.Query(s.ctx, &dynamodb.QueryInput{
			TableName:                 aws.String(s.table),
			IndexName:                 aws.String("recipient-created-at-index"),
			KeyConditionExpression:    aws.String(keyCondition),
			FilterExpression:          aws.String("#status <> :acked"),
			ExpressionAttributeNames:  map[string]string{"#status": "status"},
			ExpressionAttributeValues: values,
			Limit:                     aws.Int32(resumeBacklogLimit),
			ExclusiveStartKey:         startKey,
		})
		if err != nil {
			return nil, err
		}

		for _, item := range out.Items {
			var record deliveryRecord
			if err := attributevalue.UnmarshalMap(item, &record); err != nil {
				return nil, err
			}
			createdAt, err := time.Parse(time.RFC3339Nano, record.CreatedAt)
			if err != nil {
				// A row we cannot place in the stream is worse than one we skip:
				// replaying it out of order would corrupt the agent's view.
				continue
			}
			deliveries = append(deliveries, routecore.Delivery{
				DeliveryID:       record.DeliveryID,
				MessageID:        record.MessageID,
				ThreadID:         record.ThreadID,
				SenderAgentID:    record.SenderAgentID,
				RecipientAgentID: record.RecipientAgentID,
				Status:           routecore.DeliveryStatus(record.Status),
				CreatedAt:        createdAt,
			})
			if len(deliveries) >= resumeBacklogLimit {
				return deliveries[:resumeBacklogLimit], nil
			}
		}

		if out.LastEvaluatedKey == nil {
			break
		}
		startKey = out.LastEvaluatedKey
	}
	return deliveries, nil
}

type connectionRecord struct {
	ConnectionID string   `dynamodbav:"connection_id"`
	AgentID      string   `dynamodbav:"agent_id"`
	Scopes       []string `dynamodbav:"scopes"`
	ConnectedAt  string   `dynamodbav:"connected_at"`
	ExpiresAt    int64    `dynamodbav:"expires_at"`
}

type agentTokenRecord struct {
	TokenID   string   `dynamodbav:"token_id"`
	TokenHash string   `dynamodbav:"token_hash"`
	AgentID   string   `dynamodbav:"agent_id"`
	Scopes    []string `dynamodbav:"scopes"`
	RevokedAt string   `dynamodbav:"revoked_at"`
	ExpiresAt string   `dynamodbav:"expires_at"`
}

type routeRequest struct {
	Action            string          `json:"action"`
	MessageID         string          `json:"message_id"`
	ThreadID          string          `json:"thread_id"`
	SenderAgentID     string          `json:"sender_agent_id"`
	RecipientAgentIDs []string        `json:"recipient_agent_ids"`
	Payload           json.RawMessage `json:"payload"`
}

func main() {
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		panic(err)
	}

	tableName := os.Getenv("CONNECTIONS_TABLE")
	if tableName == "" {
		panic("CONNECTIONS_TABLE is required")
	}
	agentTokensTable := os.Getenv("AGENT_TOKENS_TABLE")
	// Optional: without it $connect still authenticates and registers, it just
	// cannot replay. Resume degrades to "the agent asks for its own backlog",
	// which is the behaviour that existed before.
	deliveriesTable := os.Getenv("DELIVERIES_TABLE")
	if agentTokensTable == "" {
		panic("AGENT_TOKENS_TABLE is required")
	}

	h := handler{
		ddb:              dynamodb.NewFromConfig(cfg),
		awsConfig:        cfg,
		connectionsTable: tableName,
		deliveriesTable:  deliveriesTable,
		agentTokensTable: agentTokensTable,
		now:              time.Now,
	}
	lambda.Start(h.handle)
}

func (h handler) handle(ctx context.Context, request events.APIGatewayWebsocketProxyRequest) (events.APIGatewayProxyResponse, error) {
	switch request.RequestContext.RouteKey {
	case "$connect":
		return h.connect(ctx, request)
	case "$disconnect":
		return h.disconnect(ctx, request)
	case "$default":
		return h.route(ctx, request)
	default:
		return jsonResponse(http.StatusNotFound, map[string]any{
			"error": "not_found",
			"route": request.RequestContext.RouteKey,
		})
	}
}

func (h handler) connect(ctx context.Context, request events.APIGatewayWebsocketProxyRequest) (events.APIGatewayProxyResponse, error) {
	tokenRecord, authResponse, err := h.requireAgentToken(ctx, request, "agent:inbox")
	if err != nil {
		return serverError(err)
	}
	if authResponse != nil {
		return *authResponse, nil
	}

	agentID := strings.TrimSpace(tokenRecord.AgentID)
	requestedAgentID := firstNonEmpty(
		request.QueryStringParameters["agent_id"],
		request.QueryStringParameters["agentId"],
		request.QueryStringParameters["handle"],
	)
	if requestedAgentID != "" && requestedAgentID != agentID {
		return jsonResponse(http.StatusForbidden, map[string]any{
			"error":   "forbidden",
			"message": "agent_id does not match authenticated token",
		})
	}

	connectionID := request.RequestContext.ConnectionID
	if connectionID == "" {
		return jsonResponse(http.StatusBadRequest, map[string]any{
			"error":   "bad_request",
			"message": "connection id is required",
		})
	}

	now := h.now().UTC()
	record := connectionRecord{
		ConnectionID: connectionID,
		AgentID:      agentID,
		Scopes:       tokenRecord.Scopes,
		ConnectedAt:  now.Format(time.RFC3339),
		ExpiresAt:    now.Add(connectionTTL).Unix(),
	}
	item, err := attributevalue.MarshalMap(record)
	if err != nil {
		return serverError(err)
	}

	_, err = h.ddb.PutItem(ctx, &dynamodb.PutItemInput{
		TableName: aws.String(h.connectionsTable),
		Item:      item,
	})
	if err != nil {
		return serverError(err)
	}

	// Replay what the agent missed while it was away. This is the Live fallback
	// closing: delivery fell back to the durable Inbox, and the reconnect
	// resumes from it rather than starting over.
	//
	// Best effort on purpose -- a replay failure must not refuse a connection
	// the agent is entitled to. The backlog stays durable either way, so the
	// worst case is the pre-existing behaviour of the agent pulling it itself.
	resumed := h.replayBacklog(ctx, request, agentID, connectionID)

	return jsonResponse(http.StatusOK, map[string]any{
		"ok":            true,
		"connection_id": connectionID,
		"agent_id":      agentID,
		"resumed_count": resumed,
	})
}

// replayBacklog pushes an agent's unacked deliveries to a fresh connection and
// returns how many were sent.
func (h handler) replayBacklog(
	ctx context.Context,
	request events.APIGatewayWebsocketProxyRequest,
	agentID string,
	connectionID string,
) int {
	if h.deliveriesTable == "" {
		return 0
	}

	// A client that knows where it left off resumes from there; one that does
	// not gets the whole outstanding backlog.
	after := time.Time{}
	if raw := strings.TrimSpace(request.QueryStringParameters["resume_after"]); raw != "" {
		parsed, err := time.Parse(time.RFC3339Nano, raw)
		if err != nil {
			// An unparseable cursor must not silently replay everything: that
			// would flood a client that believed it was asking for a little.
			return 0
		}
		after = parsed
	}

	store := dynamoDeliveryStore{ctx: ctx, ddb: h.ddb, table: h.deliveriesTable}
	result, err := routecore.ResumeFrom(store, agentID, after)
	if err != nil {
		return 0
	}
	if len(result.Missed) == 0 {
		return 0
	}

	client := h.managementClient(request)
	sent := 0
	for _, delivery := range result.Missed {
		payload, err := json.Marshal(map[string]any{
			"type":               "resume",
			"delivery_id":        delivery.DeliveryID,
			"message_id":         delivery.MessageID,
			"thread_id":          delivery.ThreadID,
			"sender_agent_id":    delivery.SenderAgentID,
			"recipient_agent_id": delivery.RecipientAgentID,
			"status":             string(delivery.Status),
			"created_at":         delivery.CreatedAt.UTC().Format(isoMillis),
		})
		if err != nil {
			continue
		}
		if _, err := client.PostToConnection(ctx, &apigatewaymanagementapi.PostToConnectionInput{
			ConnectionId: aws.String(connectionID),
			Data:         payload,
		}); err != nil {
			// The socket went away mid-replay; the rest stays durable.
			break
		}
		sent++
	}
	return sent
}

func (h handler) requireAgentToken(ctx context.Context, request events.APIGatewayWebsocketProxyRequest, requiredScope string) (agentTokenRecord, *events.APIGatewayProxyResponse, error) {
	bearerToken, err := bearerTokenFromRequest(request)
	if err != nil {
		response, responseErr := jsonResponse(http.StatusUnauthorized, map[string]any{
			"error":   "unauthorized",
			"message": err.Error(),
		})
		return agentTokenRecord{}, &response, responseErr
	}
	tokenID, secret, err := parseAgentToken(bearerToken)
	if err != nil {
		response, responseErr := jsonResponse(http.StatusUnauthorized, map[string]any{
			"error":   "unauthorized",
			"message": err.Error(),
		})
		return agentTokenRecord{}, &response, responseErr
	}

	result, err := h.ddb.GetItem(ctx, &dynamodb.GetItemInput{
		TableName: aws.String(h.agentTokensTable),
		Key: map[string]types.AttributeValue{
			"token_id": &types.AttributeValueMemberS{Value: tokenID},
		},
	})
	if err != nil {
		return agentTokenRecord{}, nil, err
	}
	if result.Item == nil {
		response, responseErr := jsonResponse(http.StatusUnauthorized, map[string]any{
			"error":   "unauthorized",
			"message": "agent token not found",
		})
		return agentTokenRecord{}, &response, responseErr
	}

	var record agentTokenRecord
	if err := attributevalue.UnmarshalMap(result.Item, &record); err != nil {
		return agentTokenRecord{}, nil, err
	}
	if !tokenHashMatches(tokenID, secret, record.TokenHash) {
		response, responseErr := jsonResponse(http.StatusUnauthorized, map[string]any{
			"error":   "unauthorized",
			"message": "agent token is invalid",
		})
		return agentTokenRecord{}, &response, responseErr
	}
	if strings.TrimSpace(record.RevokedAt) != "" {
		response, responseErr := jsonResponse(http.StatusUnauthorized, map[string]any{
			"error":   "unauthorized",
			"message": "agent token is revoked",
		})
		return agentTokenRecord{}, &response, responseErr
	}
	if tokenExpired(record.ExpiresAt, h.now().UTC()) {
		response, responseErr := jsonResponse(http.StatusUnauthorized, map[string]any{
			"error":   "unauthorized",
			"message": "agent token is expired",
		})
		return agentTokenRecord{}, &response, responseErr
	}
	if strings.TrimSpace(record.AgentID) == "" {
		response, responseErr := jsonResponse(http.StatusUnauthorized, map[string]any{
			"error":   "unauthorized",
			"message": "agent token agent_id is invalid",
		})
		return agentTokenRecord{}, &response, responseErr
	}
	if !hasScope(record.Scopes, requiredScope) {
		response, responseErr := jsonResponse(http.StatusForbidden, map[string]any{
			"error":   "forbidden",
			"message": "missing agent token scope: " + requiredScope,
		})
		return agentTokenRecord{}, &response, responseErr
	}
	return record, nil, nil
}

func bearerTokenFromRequest(request events.APIGatewayWebsocketProxyRequest) (string, error) {
	token, err := bearerTokenFromHeaders(request.Headers)
	if err == nil {
		return token, nil
	}

	queryToken := strings.TrimSpace(firstNonEmpty(
		request.QueryStringParameters["access_token"],
		request.QueryStringParameters["token"],
	))
	if queryToken == "" {
		return "", err
	}
	if strings.HasPrefix(strings.ToLower(queryToken), "bearer ") {
		queryToken = strings.TrimSpace(queryToken[len("bearer "):])
	}
	if queryToken == "" {
		return "", errors.New("authorization token is required")
	}
	return queryToken, nil
}

func (h handler) disconnect(ctx context.Context, request events.APIGatewayWebsocketProxyRequest) (events.APIGatewayProxyResponse, error) {
	connectionID := request.RequestContext.ConnectionID
	if connectionID == "" {
		return jsonResponse(http.StatusOK, map[string]any{"ok": true})
	}

	if err := h.deleteConnection(ctx, connectionID); err != nil {
		return serverError(err)
	}

	return jsonResponse(http.StatusOK, map[string]any{
		"ok":            true,
		"connection_id": connectionID,
	})
}

func (h handler) route(ctx context.Context, request events.APIGatewayWebsocketProxyRequest) (events.APIGatewayProxyResponse, error) {
	var route routeRequest
	if err := json.Unmarshal([]byte(request.Body), &route); err != nil {
		return jsonResponse(http.StatusBadRequest, map[string]any{
			"error":   "bad_request",
			"message": "body must be a JSON route request",
		})
	}

	if err := validateRoute(route); err != nil {
		return jsonResponse(http.StatusBadRequest, map[string]any{
			"error":   "bad_request",
			"message": err.Error(),
		})
	}

	connectionID := request.RequestContext.ConnectionID
	if connectionID == "" {
		return jsonResponse(http.StatusBadRequest, map[string]any{
			"error":   "bad_request",
			"message": "connection id is required",
		})
	}
	connection, found, err := h.connectionForID(ctx, connectionID)
	if err != nil {
		return serverError(err)
	}
	if !found {
		return jsonResponse(http.StatusUnauthorized, map[string]any{
			"error":   "unauthorized",
			"message": "connection is not authenticated",
		})
	}
	if err := authorizeRouteSender(route, connection); err != nil {
		return jsonResponse(http.StatusForbidden, map[string]any{
			"error":   "forbidden",
			"message": err.Error(),
		})
	}

	recipients := routecore.PlanRecipients(route.SenderAgentID, route.RecipientAgentIDs)
	if len(recipients) == 0 {
		return jsonResponse(http.StatusBadRequest, map[string]any{
			"error":   "bad_request",
			"message": "at least one recipient is required",
		})
	}

	payload := route.Payload
	if len(payload) == 0 {
		payload = json.RawMessage(request.Body)
	}

	client := h.managementClient(request)
	posted := 0
	stale := 0
	failed := 0
	for _, recipient := range recipients {
		connectionIDs, err := h.connectionIDsForAgent(ctx, recipient)
		if err != nil {
			return serverError(err)
		}

		for _, connectionID := range connectionIDs {
			_, err := client.PostToConnection(ctx, &apigatewaymanagementapi.PostToConnectionInput{
				ConnectionId: aws.String(connectionID),
				Data:         []byte(payload),
			})
			if err != nil {
				// Only a 410 Gone means the connection is actually closed and its
				// record should be removed. Transient failures (throttling,
				// timeouts, oversized payloads) must not delete a live connection,
				// or we would silently de-route and de-authenticate a healthy peer.
				var gone *apigwtypes.GoneException
				if errors.As(err, &gone) {
					stale++
					_ = h.deleteConnection(ctx, connectionID)
				} else {
					failed++
				}
				continue
			}
			posted++
		}
	}

	return jsonResponse(http.StatusOK, map[string]any{
		"message_id":       route.MessageID,
		"recipient_count":  len(recipients),
		"posted_count":     posted,
		"stale_count":      stale,
		"failed_count":     failed,
		"connection_table": h.connectionsTable,
	})
}

func validateRoute(route routeRequest) error {
	if route.MessageID == "" {
		return errors.New("message_id is required")
	}
	if route.ThreadID == "" {
		return errors.New("thread_id is required")
	}
	if route.SenderAgentID == "" {
		return errors.New("sender_agent_id is required")
	}
	return nil
}

func authorizeRouteSender(route routeRequest, connection connectionRecord) error {
	if strings.TrimSpace(connection.AgentID) == "" {
		return errors.New("connection is not authenticated")
	}
	if route.SenderAgentID != connection.AgentID {
		return errors.New("sender_agent_id does not match authenticated connection")
	}
	if !hasScope(connection.Scopes, "agent:post") {
		return errors.New("missing agent token scope: agent:post")
	}
	return nil
}

func bearerTokenFromHeaders(headers map[string]string) (string, error) {
	authorization := firstNonEmpty(headers["authorization"], headers["Authorization"])
	if authorization == "" {
		return "", errors.New("missing authorization header")
	}
	parts := strings.SplitN(strings.TrimSpace(authorization), " ", 2)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "bearer") || strings.TrimSpace(parts[1]) == "" {
		return "", errors.New("authorization header must be bearer token")
	}
	return strings.TrimSpace(parts[1]), nil
}

func parseAgentToken(token string) (string, string, error) {
	parts := strings.SplitN(token, "_", 3)
	if len(parts) != 3 || parts[0] != "sga" || parts[1] == "" || parts[2] == "" {
		return "", "", errors.New("agent token has invalid format")
	}
	return parts[1], parts[2], nil
}

func tokenHashMatches(tokenID string, secret string, expectedHash string) bool {
	actualHash := hashTokenParts(tokenID, secret)
	return subtle.ConstantTimeCompare([]byte(actualHash), []byte(expectedHash)) == 1
}

func hashTokenParts(tokenID string, secret string) string {
	sum := sha256.Sum256([]byte(tokenID + "." + secret))
	return hex.EncodeToString(sum[:])
}

func hasScope(scopes []string, requiredScope string) bool {
	for _, scope := range scopes {
		if strings.EqualFold(strings.TrimSpace(scope), requiredScope) {
			return true
		}
	}
	return false
}

func tokenExpired(expiresAt string, now time.Time) bool {
	if strings.TrimSpace(expiresAt) == "" {
		return false
	}
	parsed, err := time.Parse(time.RFC3339, expiresAt)
	if err != nil {
		return true
	}
	return !parsed.After(now)
}

func (h handler) connectionIDsForAgent(ctx context.Context, agentID string) ([]string, error) {
	result, err := h.ddb.Query(ctx, &dynamodb.QueryInput{
		TableName:              aws.String(h.connectionsTable),
		IndexName:              aws.String("agent-index"),
		KeyConditionExpression: aws.String("agent_id = :agent_id"),
		ExpressionAttributeValues: map[string]types.AttributeValue{
			":agent_id": &types.AttributeValueMemberS{Value: agentID},
		},
	})
	if err != nil {
		return nil, err
	}

	connectionIDs := make([]string, 0, len(result.Items))
	for _, item := range result.Items {
		value, ok := item["connection_id"].(*types.AttributeValueMemberS)
		if !ok || value.Value == "" {
			continue
		}
		connectionIDs = append(connectionIDs, value.Value)
	}
	return connectionIDs, nil
}

func (h handler) connectionForID(ctx context.Context, connectionID string) (connectionRecord, bool, error) {
	result, err := h.ddb.GetItem(ctx, &dynamodb.GetItemInput{
		TableName: aws.String(h.connectionsTable),
		Key: map[string]types.AttributeValue{
			"connection_id": &types.AttributeValueMemberS{Value: connectionID},
		},
	})
	if err != nil {
		return connectionRecord{}, false, err
	}
	if result.Item == nil {
		return connectionRecord{}, false, nil
	}
	var record connectionRecord
	if err := attributevalue.UnmarshalMap(result.Item, &record); err != nil {
		return connectionRecord{}, false, err
	}
	return record, true, nil
}

func (h handler) deleteConnection(ctx context.Context, connectionID string) error {
	_, err := h.ddb.DeleteItem(ctx, &dynamodb.DeleteItemInput{
		TableName: aws.String(h.connectionsTable),
		Key: map[string]types.AttributeValue{
			"connection_id": &types.AttributeValueMemberS{Value: connectionID},
		},
	})
	return err
}

func (h handler) managementClient(request events.APIGatewayWebsocketProxyRequest) *apigatewaymanagementapi.Client {
	endpoint := fmt.Sprintf(
		"https://%s/%s",
		request.RequestContext.DomainName,
		strings.TrimPrefix(request.RequestContext.Stage, "/"),
	)
	return apigatewaymanagementapi.NewFromConfig(h.awsConfig, func(options *apigatewaymanagementapi.Options) {
		options.BaseEndpoint = aws.String(endpoint)
	})
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func jsonResponse(statusCode int, body map[string]any) (events.APIGatewayProxyResponse, error) {
	payload, err := json.Marshal(body)
	if err != nil {
		return events.APIGatewayProxyResponse{}, err
	}
	return events.APIGatewayProxyResponse{
		StatusCode: statusCode,
		Headers: map[string]string{
			"content-type":  "application/json",
			"cache-control": "no-store",
		},
		Body: string(payload),
	}, nil
}

func serverError(err error) (events.APIGatewayProxyResponse, error) {
	return jsonResponse(http.StatusInternalServerError, map[string]any{
		"error":   "internal_error",
		"message": err.Error(),
	})
}
