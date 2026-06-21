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
	Payload      []byte
}

type Delivery struct {
	DeliveryID       string
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
		status := DeliveryQueued
		if len(connections) > 0 {
			status = DeliveryDelivered
		}

		delivery := Delivery{
			DeliveryID:       deliveryID(event.MessageID, recipientID),
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
