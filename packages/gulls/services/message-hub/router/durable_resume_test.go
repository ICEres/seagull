package router

import (
	"errors"
	"testing"
	"time"
)

var base = time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

type stubStore struct {
	deliveries []Delivery
	err        error
	gotAgentID string
	gotAfter   time.Time
}

func (s *stubStore) DeliveriesForAgent(agentID string, after time.Time) ([]Delivery, error) {
	s.gotAgentID = agentID
	s.gotAfter = after
	return s.deliveries, s.err
}

func at(seconds int) time.Time { return base.Add(time.Duration(seconds) * time.Second) }

func TestResumeFromReplaysOldestFirst(t *testing.T) {
	store := &stubStore{deliveries: []Delivery{
		{DeliveryID: "d3", RecipientAgentID: "a1", Status: DeliveryQueued, CreatedAt: at(30)},
		{DeliveryID: "d1", RecipientAgentID: "a1", Status: DeliveryQueued, CreatedAt: at(10)},
		{DeliveryID: "d2", RecipientAgentID: "a1", Status: DeliveryDelivered, CreatedAt: at(20)},
	}}

	result, err := ResumeFrom(store, "a1", time.Time{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	got := []string{}
	for _, d := range result.Missed {
		got = append(got, d.DeliveryID)
	}
	want := []string{"d1", "d2", "d3"}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}

func TestResumeFromExcludesAcked(t *testing.T) {
	// The agent already handled these; replaying them would duplicate work.
	store := &stubStore{deliveries: []Delivery{
		{DeliveryID: "done", RecipientAgentID: "a1", Status: DeliveryAcked, CreatedAt: at(10)},
		{DeliveryID: "open", RecipientAgentID: "a1", Status: DeliveryQueued, CreatedAt: at(20)},
	}}

	result, _ := ResumeFrom(store, "a1", time.Time{})

	if len(result.Missed) != 1 || result.Missed[0].DeliveryID != "open" {
		t.Fatalf("expected only the unacked delivery, got %+v", result.Missed)
	}
}

func TestResumeFromHonoursTheCursor(t *testing.T) {
	store := &stubStore{deliveries: []Delivery{
		{DeliveryID: "before", RecipientAgentID: "a1", Status: DeliveryQueued, CreatedAt: at(10)},
		{DeliveryID: "at", RecipientAgentID: "a1", Status: DeliveryQueued, CreatedAt: at(20)},
		{DeliveryID: "after", RecipientAgentID: "a1", Status: DeliveryQueued, CreatedAt: at(30)},
	}}

	result, _ := ResumeFrom(store, "a1", at(20))

	// Strictly after: the cursor delivery was already handed over.
	if len(result.Missed) != 1 || result.Missed[0].DeliveryID != "after" {
		t.Fatalf("expected only deliveries after the cursor, got %+v", result.Missed)
	}
	if !store.gotAfter.Equal(at(20)) {
		t.Fatalf("cursor not passed to the store: %v", store.gotAfter)
	}
}

func TestResumeFromNeverLeaksAnotherAgentsInbox(t *testing.T) {
	// A store that over-returns must not become a disclosure.
	store := &stubStore{deliveries: []Delivery{
		{DeliveryID: "mine", RecipientAgentID: "a1", Status: DeliveryQueued, CreatedAt: at(10)},
		{DeliveryID: "theirs", RecipientAgentID: "a2", Status: DeliveryQueued, CreatedAt: at(20)},
	}}

	result, _ := ResumeFrom(store, "a1", time.Time{})

	if len(result.Missed) != 1 || result.Missed[0].DeliveryID != "mine" {
		t.Fatalf("expected only this agent's deliveries, got %+v", result.Missed)
	}
}

func TestResumeFromReportsSessionAsDegraded(t *testing.T) {
	// Resuming means the agent was away; the session stays addressable so the
	// reconnect continues rather than starting over.
	result, _ := ResumeFrom(&stubStore{}, "a1", time.Time{})

	if result.Session.AgentID != "a1" || result.Session.State != LiveDegraded {
		t.Fatalf("unexpected session: %+v", result.Session)
	}
}

func TestResumeFromRequiresStoreAndAgent(t *testing.T) {
	if _, err := ResumeFrom(nil, "a1", time.Time{}); err == nil {
		t.Fatal("expected an error with no store")
	}
	if _, err := ResumeFrom(&stubStore{}, "", time.Time{}); err == nil {
		t.Fatal("expected an error with no agent id")
	}
}

func TestResumeFromSurfacesStoreErrors(t *testing.T) {
	// A read failure must not read as "nothing was missed".
	store := &stubStore{err: errors.New("dynamo unavailable")}

	if _, err := ResumeFrom(store, "a1", time.Time{}); err == nil {
		t.Fatal("expected the store error to surface")
	}
}

func TestResumeFromOrdersTiesStably(t *testing.T) {
	store := &stubStore{deliveries: []Delivery{
		{DeliveryID: "b", RecipientAgentID: "a1", Status: DeliveryQueued, CreatedAt: at(10)},
		{DeliveryID: "a", RecipientAgentID: "a1", Status: DeliveryQueued, CreatedAt: at(10)},
	}}

	result, _ := ResumeFrom(store, "a1", time.Time{})

	if result.Missed[0].DeliveryID != "a" || result.Missed[1].DeliveryID != "b" {
		t.Fatalf("expected stable tie ordering, got %+v", result.Missed)
	}
}
