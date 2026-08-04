package main

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

func TestParseAgentToken(t *testing.T) {
	tokenID, secret, err := parseAgentToken("sga_tokenid_secret")
	if err != nil {
		t.Fatalf("parseAgentToken returned error: %v", err)
	}
	if tokenID != "tokenid" || secret != "secret" {
		t.Fatalf("unexpected token parts: %q %q", tokenID, secret)
	}

	if _, _, err := parseAgentToken("not-a-token"); err == nil {
		t.Fatal("expected invalid token error")
	}
}

func TestTokenHashMatches(t *testing.T) {
	expected := hashTokenParts("tokenid", "secret")

	if !tokenHashMatches("tokenid", "secret", expected) {
		t.Fatal("expected token hash to match")
	}
	if tokenHashMatches("tokenid", "wrong", expected) {
		t.Fatal("expected token hash mismatch")
	}
}

func TestBearerTokenFromHeaders(t *testing.T) {
	token, err := bearerTokenFromHeaders(map[string]string{"Authorization": "Bearer sga_tokenid_secret"})
	if err != nil {
		t.Fatalf("bearerTokenFromHeaders returned error: %v", err)
	}
	if token != "sga_tokenid_secret" {
		t.Fatalf("unexpected token: %q", token)
	}

	if _, err := bearerTokenFromHeaders(map[string]string{"Authorization": "Basic abc"}); err == nil {
		t.Fatal("expected non-bearer authorization error")
	}
}

func TestBearerTokenFromRequestAcceptsQueryToken(t *testing.T) {
	token, err := bearerTokenFromRequest(events.APIGatewayWebsocketProxyRequest{
		QueryStringParameters: map[string]string{"access_token": "sga_tokenid_secret"},
	})
	if err != nil {
		t.Fatalf("bearerTokenFromRequest returned error: %v", err)
	}
	if token != "sga_tokenid_secret" {
		t.Fatalf("unexpected token: %q", token)
	}
}

func TestHasScope(t *testing.T) {
	if !hasScope([]string{"agent:read", "agent:inbox"}, "agent:inbox") {
		t.Fatal("expected scope match")
	}
	if hasScope([]string{"agent:read"}, "agent:inbox") {
		t.Fatal("expected missing scope")
	}
}

func TestAuthorizeRouteSenderRequiresConnectionAgentAndPostScope(t *testing.T) {
	route := routeRequest{
		MessageID:     "message-1",
		ThreadID:      "thread-1",
		SenderAgentID: "agent-sender",
	}
	connection := connectionRecord{
		ConnectionID: "conn-1",
		AgentID:      "agent-sender",
		Scopes:       []string{"agent:inbox", "agent:post"},
	}

	if err := authorizeRouteSender(route, connection); err != nil {
		t.Fatalf("authorizeRouteSender returned error: %v", err)
	}

	wrongSender := route
	wrongSender.SenderAgentID = "agent-attacker"
	if err := authorizeRouteSender(wrongSender, connection); err == nil {
		t.Fatal("expected sender mismatch error")
	}

	missingScope := connection
	missingScope.Scopes = []string{"agent:inbox"}
	if err := authorizeRouteSender(route, missingScope); err == nil {
		t.Fatal("expected missing post scope error")
	}
}

func TestTokenExpired(t *testing.T) {
	now := time.Date(2026, 6, 30, 0, 0, 0, 0, time.UTC)

	if tokenExpired("", now) {
		t.Fatal("empty expiry should not expire")
	}
	if !tokenExpired("not-a-date", now) {
		t.Fatal("invalid expiry should fail closed")
	}
	if !tokenExpired("2026-06-29T23:59:59Z", now) {
		t.Fatal("past expiry should expire")
	}
	if tokenExpired("2026-06-30T00:00:01Z", now) {
		t.Fatal("future expiry should not expire")
	}
}

// fakeQueryItem is one row of a fake recipient-created-at-index page.
type fakeQueryItem struct {
	deliveryID string
	recipient  string
	status     string
	createdAt  string
}

// fakeDynamoQuery reproduces the one DynamoDB Query behavior this store
// depends on getting right: Limit caps items *evaluated*, not items
// returned, so a FilterExpression can still leave a page empty while
// LastEvaluatedKey says there is more to page through.
type fakeDynamoQuery struct {
	items []fakeQueryItem
	calls int
}

func (f *fakeDynamoQuery) Query(_ context.Context, params *dynamodb.QueryInput, _ ...func(*dynamodb.Options)) (*dynamodb.QueryOutput, error) {
	f.calls++

	start := 0
	if params.ExclusiveStartKey != nil {
		if key, ok := params.ExclusiveStartKey["delivery_id"].(*types.AttributeValueMemberS); ok {
			for i, item := range f.items {
				if item.deliveryID == key.Value {
					start = i + 1
					break
				}
			}
		}
	}
	remaining := f.items[start:]

	limit := int(aws.ToInt32(params.Limit))
	page := remaining
	truncated := false
	if limit > 0 && len(page) > limit {
		page = page[:limit]
		truncated = true
	}

	outItems := make([]map[string]types.AttributeValue, 0, len(page))
	for _, item := range page {
		// Simulates the FilterExpression: applied to the already-truncated page.
		if item.status == "acked" {
			continue
		}
		outItems = append(outItems, map[string]types.AttributeValue{
			"delivery_id":        &types.AttributeValueMemberS{Value: item.deliveryID},
			"message_id":         &types.AttributeValueMemberS{Value: "message-" + item.deliveryID},
			"thread_id":          &types.AttributeValueMemberS{Value: "thread-1"},
			"sender_agent_id":    &types.AttributeValueMemberS{Value: "sender-1"},
			"recipient_agent_id": &types.AttributeValueMemberS{Value: item.recipient},
			"status":             &types.AttributeValueMemberS{Value: item.status},
			"created_at":         &types.AttributeValueMemberS{Value: item.createdAt},
		})
	}

	var lastKey map[string]types.AttributeValue
	if truncated {
		lastKey = map[string]types.AttributeValue{
			"delivery_id": &types.AttributeValueMemberS{Value: page[len(page)-1].deliveryID},
		}
	}
	return &dynamodb.QueryOutput{Items: outItems, LastEvaluatedKey: lastKey}, nil
}

// TestDeliveriesForAgentPagesPastAnOldestFirstAckedPage pins C13: an agent
// with more than resumeBacklogLimit lifetime deliveries, most of them acked
// and sorted oldest-first by the index, must still get its outstanding
// deliveries -- not an empty page because Limit truncated before the acked
// ones were filtered out.
func TestDeliveriesForAgentPagesPastAnOldestFirstAckedPage(t *testing.T) {
	items := make([]fakeQueryItem, 0, 150)
	for i := 0; i < 120; i++ {
		items = append(items, fakeQueryItem{
			deliveryID: fmt.Sprintf("acked-%03d", i),
			recipient:  "agent-1",
			status:     "acked",
			createdAt:  time.Date(2026, 1, 1, 0, 0, i, 0, time.UTC).Format(time.RFC3339Nano),
		})
	}
	for i := 0; i < 30; i++ {
		items = append(items, fakeQueryItem{
			deliveryID: fmt.Sprintf("open-%03d", i),
			recipient:  "agent-1",
			status:     "queued",
			createdAt:  time.Date(2026, 1, 1, 0, 2, i, 0, time.UTC).Format(time.RFC3339Nano),
		})
	}

	fake := &fakeDynamoQuery{items: items}
	store := dynamoDeliveryStore{ctx: context.Background(), ddb: fake, table: "deliveries"}

	deliveries, err := store.DeliveriesForAgent("agent-1", time.Time{})
	if err != nil {
		t.Fatalf("DeliveriesForAgent returned error: %v", err)
	}

	if len(deliveries) != 30 {
		t.Fatalf("expected 30 outstanding deliveries, got %d", len(deliveries))
	}
	for _, delivery := range deliveries {
		if delivery.Status == "acked" {
			t.Fatalf("acked delivery leaked into the replay: %+v", delivery)
		}
	}
	if fake.calls < 2 {
		t.Fatalf("expected the store to page past the acked-only first page, got %d call(s)", fake.calls)
	}
}

// TestResumeCursorRoundTripMatchesHubMillisecondFormat pins the real half of
// C14: the resume cursor must round-trip through the same fixed-width
// millisecond layout the Python hub's to_iso writes, not RFC3339Nano's
// trailing-zero-stripped rendering.
func TestResumeCursorRoundTripMatchesHubMillisecondFormat(t *testing.T) {
	instant := time.Date(2026, 6, 30, 10, 0, 0, 0, time.UTC) // lands on a whole second

	formatted := instant.Format(isoMillis)
	if formatted != "2026-06-30T10:00:00.000Z" {
		t.Fatalf("expected fixed-width milliseconds, got %q", formatted)
	}

	parsed, err := time.Parse(time.RFC3339Nano, formatted)
	if err != nil {
		t.Fatalf("failed to parse formatted cursor: %v", err)
	}
	if reformatted := parsed.Format(isoMillis); reformatted != formatted {
		t.Fatalf("cursor did not round-trip: got %q, want %q", reformatted, formatted)
	}
}

// TestIsoMillisOrdersLexicographicallyLikeTime pins that the fixed-width
// layout's byte ordering agrees with real time ordering across values that
// would otherwise trip on RFC3339Nano's variable-width fractional seconds.
func TestIsoMillisOrdersLexicographicallyLikeTime(t *testing.T) {
	values := []string{
		"2026-06-30T10:00:00.000Z",
		"2026-06-30T10:00:00.250Z",
		"2026-06-30T10:00:00.500Z",
		"2026-06-30T10:00:01.000Z",
	}
	for i := 1; i < len(values); i++ {
		if !(values[i-1] < values[i]) {
			t.Fatalf("expected %q < %q lexicographically", values[i-1], values[i])
		}
		prev, err := time.Parse(time.RFC3339Nano, values[i-1])
		if err != nil {
			t.Fatalf("failed to parse %q: %v", values[i-1], err)
		}
		next, err := time.Parse(time.RFC3339Nano, values[i])
		if err != nil {
			t.Fatalf("failed to parse %q: %v", values[i], err)
		}
		if !prev.Before(next) {
			t.Fatalf("expected %v before %v", prev, next)
		}
	}
}
