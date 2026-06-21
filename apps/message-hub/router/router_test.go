package router

import (
	"testing"
	"time"
)

func TestRouteFansOutToConnectedRecipient(t *testing.T) {
	clock := newTestClock()
	router := New(clock.Now)

	if _, err := router.Connect("conn-2", "agent-reviewer"); err != nil {
		t.Fatal(err)
	}
	if _, err := router.Connect("conn-1", "agent-reviewer"); err != nil {
		t.Fatal(err)
	}

	result, err := router.Route(RouteEvent{
		MessageID:         "message-1",
		ThreadID:          "thread-1",
		SenderAgentID:     "agent-researcher",
		RecipientAgentIDs: []string{"agent-reviewer"},
		Payload:           []byte(`{"content":"hello"}`),
	})
	if err != nil {
		t.Fatal(err)
	}

	if got := len(result.Deliveries); got != 1 {
		t.Fatalf("deliveries length = %d, want 1", got)
	}
	if result.Deliveries[0].Status != DeliveryDelivered {
		t.Fatalf("delivery status = %s, want %s", result.Deliveries[0].Status, DeliveryDelivered)
	}

	gotConnectionIDs := []string{
		result.OutboundEvents[0].ConnectionID,
		result.OutboundEvents[1].ConnectionID,
	}
	wantConnectionIDs := []string{"conn-1", "conn-2"}
	if !equal(gotConnectionIDs, wantConnectionIDs) {
		t.Fatalf("connection ids = %v, want %v", gotConnectionIDs, wantConnectionIDs)
	}
}

func TestRouteQueuesOfflineRecipient(t *testing.T) {
	router := New(newTestClock().Now)

	result, err := router.Route(RouteEvent{
		MessageID:         "message-1",
		ThreadID:          "thread-1",
		SenderAgentID:     "agent-researcher",
		RecipientAgentIDs: []string{"agent-reviewer"},
	})
	if err != nil {
		t.Fatal(err)
	}

	if result.Deliveries[0].Status != DeliveryQueued {
		t.Fatalf("delivery status = %s, want %s", result.Deliveries[0].Status, DeliveryQueued)
	}
	if got := len(result.OutboundEvents); got != 0 {
		t.Fatalf("outbound events length = %d, want 0", got)
	}
}

func TestRouteDedupesRecipientsAndSkipsSender(t *testing.T) {
	router := New(newTestClock().Now)
	if _, err := router.Connect("conn-1", "agent-reviewer"); err != nil {
		t.Fatal(err)
	}

	result, err := router.Route(RouteEvent{
		MessageID:     "message-1",
		ThreadID:      "thread-1",
		SenderAgentID: "agent-researcher",
		RecipientAgentIDs: []string{
			"agent-researcher",
			"agent-reviewer",
			"agent-reviewer",
			"",
		},
	})
	if err != nil {
		t.Fatal(err)
	}

	if got := len(result.Deliveries); got != 1 {
		t.Fatalf("deliveries length = %d, want 1", got)
	}
	if result.Deliveries[0].RecipientAgentID != "agent-reviewer" {
		t.Fatalf("recipient = %s, want agent-reviewer", result.Deliveries[0].RecipientAgentID)
	}
}

func TestDeliveryTransitions(t *testing.T) {
	router := New(newTestClock().Now)
	result, err := router.Route(RouteEvent{
		MessageID:         "message-1",
		ThreadID:          "thread-1",
		SenderAgentID:     "agent-researcher",
		RecipientAgentIDs: []string{"agent-reviewer"},
	})
	if err != nil {
		t.Fatal(err)
	}

	deliveryID := result.Deliveries[0].DeliveryID
	failed, err := router.FailDelivery(deliveryID, "websocket gone")
	if err != nil {
		t.Fatal(err)
	}
	if failed.Status != DeliveryFailed {
		t.Fatalf("status = %s, want %s", failed.Status, DeliveryFailed)
	}
	if failed.RetryCount != 1 {
		t.Fatalf("retry count = %d, want 1", failed.RetryCount)
	}
	if failed.LastError != "websocket gone" {
		t.Fatalf("last error = %q, want websocket gone", failed.LastError)
	}

	acked, err := router.AckDelivery(deliveryID)
	if err != nil {
		t.Fatal(err)
	}
	if acked.Status != DeliveryAcked {
		t.Fatalf("status = %s, want %s", acked.Status, DeliveryAcked)
	}
}

func TestConnectAndDisconnect(t *testing.T) {
	router := New(newTestClock().Now)
	if _, err := router.Connect("conn-1", "agent-reviewer"); err != nil {
		t.Fatal(err)
	}

	if got := len(router.Connections("agent-reviewer")); got != 1 {
		t.Fatalf("connections length = %d, want 1", got)
	}
	if !router.Disconnect("conn-1", "agent-reviewer") {
		t.Fatal("disconnect returned false, want true")
	}
	if got := len(router.Connections("agent-reviewer")); got != 0 {
		t.Fatalf("connections length = %d, want 0", got)
	}
}

type testClock struct {
	next time.Time
}

func newTestClock() *testClock {
	return &testClock{next: time.Date(2026, 6, 12, 0, 0, 0, 0, time.UTC)}
}

func (c *testClock) Now() time.Time {
	now := c.next
	c.next = c.next.Add(time.Second)
	return now
}

func equal[T comparable](left []T, right []T) bool {
	if len(left) != len(right) {
		return false
	}
	for i := range left {
		if left[i] != right[i] {
			return false
		}
	}
	return true
}
