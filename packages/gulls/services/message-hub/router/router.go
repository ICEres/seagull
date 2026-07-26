package router

import (
	"errors"
	"fmt"
	"slices"
	"sync"
	"time"
)

type DeliveryStatus string

const (
	DeliveryQueued    DeliveryStatus = "queued"
	DeliveryDelivered DeliveryStatus = "delivered"
	DeliveryAcked     DeliveryStatus = "acked"
	DeliveryFailed    DeliveryStatus = "failed"
)

type Clock func() time.Time

type Router struct {
	mu                 sync.RWMutex
	clock              Clock
	connectionsByAgent map[string]map[string]Connection
	deliveries         map[string]Delivery
	liveByAgent        map[string]LiveSession
}

// LiveSessionState mirrors seagull_protocol.events.LiveSessionState.
type LiveSessionState string

const (
	// LiveActive: the agent is connected and receiving in real time.
	LiveActive LiveSessionState = "active"
	// LiveDegraded: the agent dropped, so delivery fell back to the durable
	// Inbox. The session stays addressable so a reconnect resumes rather than
	// starting over.
	LiveDegraded LiveSessionState = "degraded"
)

// LiveSession is the real-time projection of an agent's delivery stream.
//
// It carries no content. Messages and deliveries remain the durable records;
// this only tracks how far the stream has advanced and where a reconnecting
// agent should resume (packages/gulls/docs/concept.md).
type LiveSession struct {
	AgentID string
	State   LiveSessionState
	// DeliveredSequence is the high-water mark handed to this agent. It only
	// ever increases, so a resume point stays meaningful across reconnects.
	DeliveredSequence int64
	UpdatedAt         time.Time
}

// ResumeResult is what a reconnecting agent missed while it was away.
type ResumeResult struct {
	Session LiveSession
	// Missed are the durable deliveries after the resume point, oldest first,
	// so the agent replays in the order they happened.
	Missed []Delivery
}

type Connection struct {
	ConnectionID string
	AgentID      string
	ConnectedAt  time.Time
}

type RouteEvent struct {
	MessageID         string
	ThreadID          string
	SenderAgentID     string
	RecipientAgentIDs []string
	Payload           []byte
}

type OutboundEvent struct {
	ConnectionID string
	AgentID      string
	MessageID    string
	ThreadID     string
	Sequence     int64
	Payload      []byte
}

type Delivery struct {
	DeliveryID string
	// Sequence orders one recipient's stream. Resume replays everything after
	// a given sequence, so this is what makes "resume from durable state"
	// answerable without re-sending what the agent already saw.
	Sequence         int64
	MessageID        string
	ThreadID         string
	SenderAgentID    string
	RecipientAgentID string
	Status           DeliveryStatus
	RetryCount       int
	LastError        string
	CreatedAt        time.Time
	UpdatedAt        time.Time
}

type RouteResult struct {
	Deliveries     []Delivery
	OutboundEvents []OutboundEvent
}

func New(clock Clock) *Router {
	if clock == nil {
		clock = time.Now
	}

	return &Router{
		clock:              clock,
		connectionsByAgent: make(map[string]map[string]Connection),
		deliveries:         make(map[string]Delivery),
		liveByAgent:        make(map[string]LiveSession),
	}
}

func (r *Router) Connect(connectionID string, agentID string) (Connection, error) {
	if connectionID == "" {
		return Connection{}, errors.New("connection id is required")
	}
	if agentID == "" {
		return Connection{}, errors.New("agent id is required")
	}

	connection := Connection{
		ConnectionID: connectionID,
		AgentID:      agentID,
		ConnectedAt:  r.clock(),
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	if _, ok := r.connectionsByAgent[agentID]; !ok {
		r.connectionsByAgent[agentID] = make(map[string]Connection)
	}
	r.connectionsByAgent[agentID][connectionID] = connection

	session := r.sessionFor(agentID)
	session.State = LiveActive
	session.UpdatedAt = connection.ConnectedAt
	r.liveByAgent[agentID] = session

	return connection, nil
}

func (r *Router) Disconnect(connectionID string, agentID string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()

	connections, ok := r.connectionsByAgent[agentID]
	if !ok {
		return false
	}
	if _, ok := connections[connectionID]; !ok {
		return false
	}

	delete(connections, connectionID)
	if len(connections) == 0 {
		delete(r.connectionsByAgent, agentID)
		// Last connection gone: Live degrades to durable Inbox delivery. The
		// session is kept, not dropped, so a reconnect can resume.
		session := r.sessionFor(agentID)
		session.State = LiveDegraded
		session.UpdatedAt = r.clock()
		r.liveByAgent[agentID] = session
	}
	return true
}

func (r *Router) Route(event RouteEvent) (RouteResult, error) {
	if event.MessageID == "" {
		return RouteResult{}, errors.New("message id is required")
	}
	if event.ThreadID == "" {
		return RouteResult{}, errors.New("thread id is required")
	}
	if event.SenderAgentID == "" {
		return RouteResult{}, errors.New("sender agent id is required")
	}

	recipients := uniqueRecipients(event.SenderAgentID, event.RecipientAgentIDs)
	if len(recipients) == 0 {
		return RouteResult{}, errors.New("at least one recipient is required")
	}

	now := r.clock()
	result := RouteResult{
		Deliveries:     make([]Delivery, 0, len(recipients)),
		OutboundEvents: make([]OutboundEvent, 0, len(recipients)),
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	for _, recipientID := range recipients {
		connections := r.connectionsByAgent[recipientID]
		live := len(connections) > 0

		// Every delivery advances the recipient's stream whether or not they
		// are live. A queued delivery still has a sequence, which is what lets
		// a reconnect replay exactly what it missed.
		session := r.sessionFor(recipientID)
		session.DeliveredSequence++
		if live {
			session.State = LiveActive
		} else {
			// Not connected: Live falls back to the durable Inbox.
			session.State = LiveDegraded
		}
		session.UpdatedAt = now
		r.liveByAgent[recipientID] = session

		status := DeliveryQueued
		if live {
			status = DeliveryDelivered
		}

		delivery := Delivery{
			DeliveryID:       deliveryID(event.MessageID, recipientID),
			Sequence:         session.DeliveredSequence,
			MessageID:        event.MessageID,
			ThreadID:         event.ThreadID,
			SenderAgentID:    event.SenderAgentID,
			RecipientAgentID: recipientID,
			Status:           status,
			CreatedAt:        now,
			UpdatedAt:        now,
		}
		r.deliveries[delivery.DeliveryID] = delivery
		result.Deliveries = append(result.Deliveries, delivery)

		connectionIDs := sortedConnectionIDs(connections)
		for _, connectionID := range connectionIDs {
			result.OutboundEvents = append(result.OutboundEvents, OutboundEvent{
				ConnectionID: connectionID,
				AgentID:      recipientID,
				MessageID:    event.MessageID,
				ThreadID:     event.ThreadID,
				Sequence:     delivery.Sequence,
				Payload:      slices.Clone(event.Payload),
			})
		}
	}

	return result, nil
}

func (r *Router) AckDelivery(deliveryID string) (Delivery, error) {
	return r.updateDelivery(deliveryID, func(delivery Delivery, now time.Time) Delivery {
		delivery.Status = DeliveryAcked
		delivery.UpdatedAt = now
		return delivery
	})
}

func (r *Router) FailDelivery(deliveryID string, reason string) (Delivery, error) {
	return r.updateDelivery(deliveryID, func(delivery Delivery, now time.Time) Delivery {
		delivery.Status = DeliveryFailed
		delivery.RetryCount++
		delivery.LastError = reason
		delivery.UpdatedAt = now
		return delivery
	})
}

func (r *Router) Delivery(deliveryID string) (Delivery, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	delivery, ok := r.deliveries[deliveryID]
	return delivery, ok
}

func (r *Router) Connections(agentID string) []Connection {
	r.mu.RLock()
	defer r.mu.RUnlock()

	connections := r.connectionsByAgent[agentID]
	connectionIDs := sortedConnectionIDs(connections)
	result := make([]Connection, 0, len(connectionIDs))
	for _, connectionID := range connectionIDs {
		result = append(result, connections[connectionID])
	}
	return result
}

// LiveSession reports an agent's real-time session state.
func (r *Router) LiveSession(agentID string) (LiveSession, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	session, ok := r.liveByAgent[agentID]
	return session, ok
}

// Resume replays what an agent missed, from durable state.
//
// This is the Inbox side of the Live fallback: everything after resumeAfter
// that has not been acked, oldest first. Acked deliveries are excluded because
// the agent already handled them; passing a resumeAfter of 0 replays the whole
// outstanding backlog.
func (r *Router) Resume(agentID string, resumeAfter int64) (ResumeResult, error) {
	if agentID == "" {
		return ResumeResult{}, errors.New("agent id is required")
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	missed := make([]Delivery, 0)
	for _, delivery := range r.deliveries {
		if delivery.RecipientAgentID != agentID {
			continue
		}
		if delivery.Sequence <= resumeAfter {
			continue
		}
		if delivery.Status == DeliveryAcked {
			continue
		}
		missed = append(missed, delivery)
	}

	// Oldest first: a replay must arrive in the order the messages happened.
	slices.SortFunc(missed, func(a, b Delivery) int {
		switch {
		case a.Sequence < b.Sequence:
			return -1
		case a.Sequence > b.Sequence:
			return 1
		default:
			return 0
		}
	})

	session := r.sessionFor(agentID)
	return ResumeResult{Session: session, Missed: missed}, nil
}

// sessionFor returns the agent's session, creating a zero-value one on first
// use. Callers hold the lock.
func (r *Router) sessionFor(agentID string) LiveSession {
	session, ok := r.liveByAgent[agentID]
	if !ok {
		session = LiveSession{AgentID: agentID, State: LiveDegraded}
	}
	return session
}

func (r *Router) updateDelivery(deliveryID string, update func(Delivery, time.Time) Delivery) (Delivery, error) {
	if deliveryID == "" {
		return Delivery{}, errors.New("delivery id is required")
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	delivery, ok := r.deliveries[deliveryID]
	if !ok {
		return Delivery{}, fmt.Errorf("delivery not found: %s", deliveryID)
	}

	updated := update(delivery, r.clock())
	r.deliveries[deliveryID] = updated
	return updated, nil
}

func uniqueRecipients(senderAgentID string, recipientAgentIDs []string) []string {
	recipients := make([]string, 0, len(recipientAgentIDs))
	seen := map[string]bool{senderAgentID: true}

	for _, recipientID := range recipientAgentIDs {
		if recipientID == "" || seen[recipientID] {
			continue
		}
		recipients = append(recipients, recipientID)
		seen[recipientID] = true
	}

	return recipients
}

func PlanRecipients(senderAgentID string, recipientAgentIDs []string) []string {
	return uniqueRecipients(senderAgentID, recipientAgentIDs)
}

func sortedConnectionIDs(connections map[string]Connection) []string {
	connectionIDs := make([]string, 0, len(connections))
	for connectionID := range connections {
		connectionIDs = append(connectionIDs, connectionID)
	}
	slices.Sort(connectionIDs)
	return connectionIDs
}

func deliveryID(messageID string, recipientAgentID string) string {
	return fmt.Sprintf("%s:%s", messageID, recipientAgentID)
}
