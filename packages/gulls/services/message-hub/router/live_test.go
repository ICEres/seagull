package router

import (
	"testing"
)

// Live is optional real-time delivery that falls back to the durable Inbox
// when an agent disconnects, and resumes from durable state when it returns
// (packages/gulls/docs/concept.md). These tests pin that behaviour.

func routeTo(t *testing.T, router *Router, messageID string, recipient string) Delivery {
	t.Helper()

	result, err := router.Route(RouteEvent{
		MessageID:         messageID,
		ThreadID:          "thread-1",
		SenderAgentID:     "agent-sender",
		RecipientAgentIDs: []string{recipient},
		Payload:           []byte(`{"content":"hi"}`),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Deliveries) != 1 {
		t.Fatalf("expected 1 delivery, got %d", len(result.Deliveries))
	}
	return result.Deliveries[0]
}

func TestLiveSessionGoesActiveOnConnectAndDegradesOnDisconnect(t *testing.T) {
	clock := newTestClock()
	router := New(clock.Now)

	if _, ok := router.LiveSession("agent-reviewer"); ok {
		t.Fatal("expected no session before the agent has ever connected")
	}

	if _, err := router.Connect("conn-1", "agent-reviewer"); err != nil {
		t.Fatal(err)
	}
	session, ok := router.LiveSession("agent-reviewer")
	if !ok || session.State != LiveActive {
		t.Fatalf("expected an active session, got %+v (ok=%v)", session, ok)
	}

	router.Disconnect("conn-1", "agent-reviewer")
	session, ok = router.LiveSession("agent-reviewer")
	if !ok {
		t.Fatal("session must survive a disconnect so a reconnect can resume")
	}
	if session.State != LiveDegraded {
		t.Fatalf("expected the session to degrade to Inbox, got %q", session.State)
	}
}

func TestASecondConnectionKeepsTheSessionLive(t *testing.T) {
	clock := newTestClock()
	router := New(clock.Now)

	if _, err := router.Connect("conn-1", "agent-reviewer"); err != nil {
		t.Fatal(err)
	}
	if _, err := router.Connect("conn-2", "agent-reviewer"); err != nil {
		t.Fatal(err)
	}
	router.Disconnect("conn-1", "agent-reviewer")

	session, _ := router.LiveSession("agent-reviewer")
	if session.State != LiveActive {
		t.Fatalf("one connection remains, so the session is still live; got %q", session.State)
	}
}

func TestSequenceAdvancesWhetherOrNotTheAgentIsLive(t *testing.T) {
	clock := newTestClock()
	router := New(clock.Now)

	// Offline: still sequenced, so the backlog is replayable.
	first := routeTo(t, router, "message-1", "agent-reviewer")
	if first.Status != DeliveryQueued {
		t.Fatalf("expected a queued delivery for an offline agent, got %q", first.Status)
	}
	if first.Sequence != 1 {
		t.Fatalf("expected sequence 1, got %d", first.Sequence)
	}

	if _, err := router.Connect("conn-1", "agent-reviewer"); err != nil {
		t.Fatal(err)
	}
	second := routeTo(t, router, "message-2", "agent-reviewer")
	if second.Status != DeliveryDelivered {
		t.Fatalf("expected a live delivery, got %q", second.Status)
	}
	if second.Sequence != 2 {
		t.Fatalf("sequence must keep counting across the fallback, got %d", second.Sequence)
	}
}

func TestSequencesArePerRecipient(t *testing.T) {
	clock := newTestClock()
	router := New(clock.Now)

	result, err := router.Route(RouteEvent{
		MessageID:         "message-1",
		ThreadID:          "thread-1",
		SenderAgentID:     "agent-sender",
		RecipientAgentIDs: []string{"agent-a", "agent-b"},
	})
	if err != nil {
		t.Fatal(err)
	}

	for _, delivery := range result.Deliveries {
		if delivery.Sequence != 1 {
			t.Fatalf("each recipient has its own stream; %s got sequence %d",
				delivery.RecipientAgentID, delivery.Sequence)
		}
	}
}

func TestResumeReplaysWhatWasMissedOldestFirst(t *testing.T) {
	clock := newTestClock()
	router := New(clock.Now)

	// Agent is away; three messages queue up in the durable Inbox.
	routeTo(t, router, "message-1", "agent-reviewer")
	routeTo(t, router, "message-2", "agent-reviewer")
	routeTo(t, router, "message-3", "agent-reviewer")

	// It reconnects having already seen the first.
	if _, err := router.Connect("conn-1", "agent-reviewer"); err != nil {
		t.Fatal(err)
	}
	resumed, err := router.Resume("agent-reviewer", 1)
	if err != nil {
		t.Fatal(err)
	}

	if len(resumed.Missed) != 2 {
		t.Fatalf("expected 2 missed deliveries, got %d", len(resumed.Missed))
	}
	if resumed.Missed[0].MessageID != "message-2" || resumed.Missed[1].MessageID != "message-3" {
		t.Fatalf("replay must be oldest first, got %s then %s",
			resumed.Missed[0].MessageID, resumed.Missed[1].MessageID)
	}
	if resumed.Session.State != LiveActive {
		t.Fatalf("expected the resumed session to be live, got %q", resumed.Session.State)
	}
}

func TestResumeFromZeroReplaysTheWholeBacklog(t *testing.T) {
	clock := newTestClock()
	router := New(clock.Now)

	routeTo(t, router, "message-1", "agent-reviewer")
	routeTo(t, router, "message-2", "agent-reviewer")

	resumed, err := router.Resume("agent-reviewer", 0)
	if err != nil {
		t.Fatal(err)
	}

	if len(resumed.Missed) != 2 {
		t.Fatalf("expected the full backlog, got %d", len(resumed.Missed))
	}
}

func TestResumeSkipsWhatTheAgentAlreadyAcked(t *testing.T) {
	clock := newTestClock()
	router := New(clock.Now)

	first := routeTo(t, router, "message-1", "agent-reviewer")
	routeTo(t, router, "message-2", "agent-reviewer")

	if _, err := router.AckDelivery(first.DeliveryID); err != nil {
		t.Fatal(err)
	}

	resumed, err := router.Resume("agent-reviewer", 0)
	if err != nil {
		t.Fatal(err)
	}

	if len(resumed.Missed) != 1 {
		t.Fatalf("an acked delivery must not be replayed; got %d", len(resumed.Missed))
	}
	if resumed.Missed[0].MessageID != "message-2" {
		t.Fatalf("expected message-2, got %s", resumed.Missed[0].MessageID)
	}
}

func TestResumeIgnoresOtherAgentsStreams(t *testing.T) {
	clock := newTestClock()
	router := New(clock.Now)

	routeTo(t, router, "message-1", "agent-reviewer")
	routeTo(t, router, "message-2", "agent-other")

	resumed, err := router.Resume("agent-reviewer", 0)
	if err != nil {
		t.Fatal(err)
	}

	if len(resumed.Missed) != 1 || resumed.Missed[0].RecipientAgentID != "agent-reviewer" {
		t.Fatalf("resume must be scoped to one agent, got %+v", resumed.Missed)
	}
}

func TestResumeRequiresAnAgent(t *testing.T) {
	router := New(newTestClock().Now)

	if _, err := router.Resume("", 0); err == nil {
		t.Fatal("expected an error for an empty agent id")
	}
}

func TestOutboundEventsCarryTheResumePoint(t *testing.T) {
	clock := newTestClock()
	router := New(clock.Now)

	if _, err := router.Connect("conn-1", "agent-reviewer"); err != nil {
		t.Fatal(err)
	}
	result, err := router.Route(RouteEvent{
		MessageID:         "message-1",
		ThreadID:          "thread-1",
		SenderAgentID:     "agent-sender",
		RecipientAgentIDs: []string{"agent-reviewer"},
	})
	if err != nil {
		t.Fatal(err)
	}

	if len(result.OutboundEvents) != 1 {
		t.Fatalf("expected 1 outbound event, got %d", len(result.OutboundEvents))
	}
	// The client needs the sequence to know what to resume after.
	if got := result.OutboundEvents[0].Sequence; got != 1 {
		t.Fatalf("expected sequence 1 on the outbound event, got %d", got)
	}
}
