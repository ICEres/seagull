package main

import (
	"context"
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
	now              func() time.Time
}

type connectionRecord struct {
	ConnectionID string `dynamodbav:"connection_id"`
	AgentID      string `dynamodbav:"agent_id"`
	ConnectedAt  string `dynamodbav:"connected_at"`
	ExpiresAt    int64  `dynamodbav:"expires_at"`
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

	h := handler{
		ddb:              dynamodb.NewFromConfig(cfg),
		awsConfig:        cfg,
		connectionsTable: tableName,
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
	agentID := firstNonEmpty(
		request.QueryStringParameters["agent_id"],
		request.QueryStringParameters["agentId"],
		request.QueryStringParameters["handle"],
	)
	if agentID == "" {
		return jsonResponse(http.StatusBadRequest, map[string]any{
			"error":   "bad_request",
			"message": "agent_id query parameter is required",
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
