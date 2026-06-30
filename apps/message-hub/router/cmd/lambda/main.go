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

	routecore "seagull/apps/message-hub/router"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/feature/dynamodb/attributevalue"
	"github.com/aws/aws-sdk-go-v2/service/apigatewaymanagementapi"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

const connectionTTL = 24 * time.Hour

type handler struct {
	ddb              *dynamodb.Client
	awsConfig        aws.Config
	connectionsTable string
	agentTokensTable string
	now              func() time.Time
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
	if agentTokensTable == "" {
		panic("AGENT_TOKENS_TABLE is required")
	}

	h := handler{
		ddb:              dynamodb.NewFromConfig(cfg),
		awsConfig:        cfg,
		connectionsTable: tableName,
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

	return jsonResponse(http.StatusOK, map[string]any{
		"ok":            true,
		"connection_id": connectionID,
		"agent_id":      agentID,
	})
}

func (h handler) requireAgentToken(ctx context.Context, request events.APIGatewayWebsocketProxyRequest, requiredScope string) (agentTokenRecord, *events.APIGatewayProxyResponse, error) {
	bearerToken, err := bearerTokenFromHeaders(request.Headers)
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
				stale++
				_ = h.deleteConnection(ctx, connectionID)
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
