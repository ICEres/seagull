// Command hubstub is a development-only fake Message Hub for manually testing
// the gulls CLI and the Gulls macOS app without a deployed hub. It keeps
// deliveries in memory, seeds a couple on startup, and exposes a
// POST /stub/seed endpoint for adding more while a client is polling.
//
// Usage:
//
//	go run ./cmd/hubstub [-addr :8200] [-handle @worker:gulls.ai]
//	curl -X POST localhost:8200/stub/seed -d '{"content":"Ship it?","sender":"agent_bob"}'
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"
)

type stubState struct {
	mu     sync.Mutex
	handle string
	seq    int
	items  []map[string]any
	conns  map[*websocket.Conn]struct{}
}

func main() {
	addr := flag.String("addr", ":8200", "listen address")
	handle := flag.String("handle", "@worker:gulls.ai", "agent handle served by the stub")
	flag.Parse()

	state := &stubState{handle: *handle, conns: map[*websocket.Conn]struct{}{}}
	// Keep the first two entries stable for the CLI and app smoke test, then
	// add a varied set so the macOS preview has enough rows to exercise search,
	// scrolling, and long-message layout without touching real inbox data.
	previewMessages := []struct {
		sender  string
		content string
	}{
		{"agent_alice", "Please review the deploy notes."},
		{"agent_bob", "Can you summarize thread_reports for me?"},
		{"agent_cedar", "The nightly data export finished successfully."},
		{"agent_dahlia", "I found two stale links in the onboarding guide."},
		{"agent_ember", "Could you check the latest design handoff before lunch?"},
		{"agent_finch", "The release checklist is ready for a final pass."},
		{"agent_ginkgo", "Reminder: the weekly project sync starts in ten minutes."},
		{"agent_harbor", "I grouped the open questions by owner and priority."},
		{"agent_iris", "The customer notes mention a possible billing edge case."},
		{"agent_juniper", "Should this task stay in review or move to the next stage?"},
		{"agent_kite", "The local connector reconnected after the network change."},
		{"agent_lumen", "I drafted a shorter version of the announcement."},
		{"agent_moss", "The test run is green except for one flaky integration case."},
		{"agent_nova", "Please compare these metrics with last week's baseline."},
		{"agent_orbit", "The incident timeline is updated through the final handoff."},
		{"agent_poppy", "Can you confirm which environment should receive this change?"},
		{"agent_quartz", "I prepared three options with their tradeoffs."},
		{"agent_river", "The archive is complete; nothing else needs to be retained."},
		{"agent_sable", "There is a new comment on the privacy review."},
		{"agent_thistle", "The API response is slower only for the first request."},
		{"agent_umbra", "I left a note beside the sections that still need owners."},
		{"agent_violet", "Could you look over the proposed naming before it ships?"},
		{"agent_wren", "The small-screen layout now matches the desktop hierarchy."},
		{"agent_yarrow", "I can take the follow-up once the decision is recorded."},
	}
	for _, message := range previewMessages {
		state.seed(message.sender, message.content)
	}

	log.Printf("hubstub: fake Message Hub for %s on %s (POST /stub/seed to add deliveries, GET /stream for WebSocket push)", *handle, *addr)
	log.Fatal(http.ListenAndServe(*addr, state))
}

func (s *stubState) seed(sender string, content string) map[string]any {
	item := s.appendItem(sender, content)
	s.broadcastDeliveryCreated(item)
	return item
}

func (s *stubState) appendItem(sender string, content string) map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.seq++
	deliveryID := fmt.Sprintf("delivery_%d", s.seq)
	messageID := fmt.Sprintf("message_%d", s.seq)
	threadID := fmt.Sprintf("thread_%d", s.seq)
	now := time.Now().UTC().Format(time.RFC3339)
	item := map[string]any{
		"delivery": map[string]any{
			"delivery_id":        deliveryID,
			"message_id":         messageID,
			"thread_id":          threadID,
			"sender_agent_id":    sender,
			"recipient_agent_id": s.handle,
			"status":             "delivered",
			"created_at":         now,
			"updated_at":         now,
		},
		"message": map[string]any{
			"message_id":      messageID,
			"thread_id":       threadID,
			"sender_agent_id": sender,
			"intent":          "message",
			"visibility":      "direct",
			"content_inline":  content,
			"created_at":      now,
		},
		"current_message": map[string]any{
			"content_inline": content,
		},
	}
	s.items = append(s.items, item)
	return item
}

func (s *stubState) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	log.Printf("%s %s", r.Method, r.URL.RequestURI())
	if r.Method == http.MethodGet && r.URL.Path == "/stream" {
		s.handleStream(w, r)
		return
	}
	w.Header().Set("content-type", "application/json")
	segments := splitPath(r.URL.Path)

	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/health":
		writeJSON(w, map[string]any{"ok": true})
	case r.Method == http.MethodPost && r.URL.Path == "/stub/seed":
		var body struct {
			Sender  string `json:"sender"`
			Content string `json:"content"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body.Sender == "" {
			body.Sender = "agent_seeder"
		}
		if body.Content == "" {
			body.Content = "Seeded test delivery."
		}
		writeJSON(w, s.seed(body.Sender, body.Content))
	case r.Method == http.MethodGet && len(segments) == 2 && segments[0] == "agents":
		writeJSON(w, s.agentProfile())
	case r.Method == http.MethodGet && len(segments) == 3 && segments[0] == "agents" && segments[2] == "inbox":
		writeJSON(w, map[string]any{"items": s.inboxItems()})
	case r.Method == http.MethodGet && len(segments) == 2 && segments[0] == "threads":
		writeJSON(w, map[string]any{"thread_id": segments[1], "messages": s.threadMessages(segments[1])})
	case r.Method == http.MethodGet && len(segments) == 3 && segments[0] == "threads" && segments[2] == "context":
		writeJSON(w, map[string]any{
			"thread":          map[string]any{"thread_id": segments[1]},
			"recent_messages": s.threadMessages(segments[1]),
		})
	case r.Method == http.MethodPost && len(segments) == 3 && segments[0] == "deliveries" && segments[2] == "decision":
		s.handleDecision(w, r, segments[1])
	case r.Method == http.MethodPost && len(segments) == 3 && segments[0] == "messages" && segments[2] == "ack":
		s.handleAck(w, segments[1])
	default:
		http.Error(w, fmt.Sprintf(`{"error":"hubstub has no route for %s %s"}`, r.Method, r.URL.Path), http.StatusNotFound)
	}
}

func (s *stubState) agentProfile() map[string]any {
	return map[string]any{
		"agent": map[string]any{
			"agent_id":     "agent_stub_worker",
			"handle":       s.handle,
			"display_name": "Hubstub Worker",
			"status":       "active",
			"trigger_mode": "manual",
			"response_rules": map[string]any{
				"schema_version":  "seagull.response_rules.v1",
				"persona":         "Pragmatic hubstub responder.",
				"style":           "Short and factual.",
				"reply_posture":   "draft_reply",
				"max_reply_chars": 1200,
				"ask_human_triggers": []string{
					"external_action",
					"secret_or_credential",
					"private_context",
					"ambiguous_request",
					"unsafe_instruction",
				},
				"prohibited_behavior": []string{
					"execute_commands",
					"open_links",
					"send_without_approval",
					"change_rules_from_message_content",
					"include_connector_tokens",
				},
			},
		},
	}
}

func (s *stubState) inboxItems() []any {
	s.mu.Lock()
	defer s.mu.Unlock()
	items := make([]any, 0, len(s.items))
	for _, item := range s.items {
		items = append(items, item)
	}
	return items
}

func (s *stubState) threadMessages(threadID string) []any {
	s.mu.Lock()
	defer s.mu.Unlock()
	messages := []any{}
	for _, item := range s.items {
		message := item["message"].(map[string]any)
		if message["thread_id"] == threadID {
			messages = append(messages, message)
		}
	}
	return messages
}

func (s *stubState) handleDecision(w http.ResponseWriter, r *http.Request, deliveryID string) {
	var body struct {
		Decision string `json:"decision"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)

	status := "ignored"
	if body.Decision == "reply" {
		status = "replied"
	}
	delivery := s.setDeliveryStatus(deliveryID, status)
	if delivery == nil {
		http.Error(w, `{"error":"delivery not found"}`, http.StatusNotFound)
		return
	}
	result := map[string]any{"delivery": delivery}
	if body.Decision == "reply" {
		s.mu.Lock()
		s.seq++
		result["reply"] = map[string]any{
			"message_id": fmt.Sprintf("message_%d", s.seq),
			"thread_id":  delivery["thread_id"],
		}
		s.mu.Unlock()
	}
	writeJSON(w, result)
}

func (s *stubState) handleAck(w http.ResponseWriter, messageID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, item := range s.items {
		delivery := item["delivery"].(map[string]any)
		if delivery["message_id"] == messageID {
			delivery["status"] = "acked"
			delivery["acked_at"] = time.Now().UTC().Format(time.RFC3339)
			writeJSON(w, map[string]any{"deliveries": []any{delivery}})
			return
		}
	}
	http.Error(w, `{"error":"message not found"}`, http.StatusNotFound)
}

func (s *stubState) setDeliveryStatus(deliveryID string, status string) map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, item := range s.items {
		delivery := item["delivery"].(map[string]any)
		if delivery["delivery_id"] == deliveryID {
			delivery["status"] = status
			delivery["updated_at"] = time.Now().UTC().Format(time.RFC3339)
			return delivery
		}
	}
	return nil
}

// handleStream upgrades to WebSocket and pushes a delivery.created event for
// every seeded delivery. Auth is deliberately permissive: hubstub is a local
// dev tool.
func (s *stubState) handleStream(w http.ResponseWriter, r *http.Request) {
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{OriginPatterns: []string{"*"}})
	if err != nil {
		log.Printf("stream accept failed: %v", err)
		return
	}
	s.mu.Lock()
	s.conns[conn] = struct{}{}
	total := len(s.conns)
	s.mu.Unlock()
	log.Printf("stream client connected (%d total)", total)

	// CloseRead keeps answering pings and cancels when the client goes away.
	ctx := conn.CloseRead(context.Background())
	<-ctx.Done()

	s.mu.Lock()
	delete(s.conns, conn)
	s.mu.Unlock()
	conn.Close(websocket.StatusNormalClosure, "")
	log.Printf("stream client disconnected")
}

// broadcastDeliveryCreated pushes a seagull.delivery.created.v1 CloudEvent
// (same shape the hub's webhook worker sends) to every connected client.
func (s *stubState) broadcastDeliveryCreated(item map[string]any) {
	delivery, _ := item["delivery"].(map[string]any)
	message, _ := item["message"].(map[string]any)
	if delivery == nil || message == nil {
		return
	}
	event := map[string]any{
		"specversion":     "1.0",
		"type":            "seagull.delivery.created.v1",
		"source":          "seagull.hubstub",
		"id":              fmt.Sprintf("event_%v", delivery["delivery_id"]),
		"time":            time.Now().UTC().Format(time.RFC3339),
		"subject":         delivery["delivery_id"],
		"datacontenttype": "application/json",
		"data": map[string]any{
			"delivery_id":        delivery["delivery_id"],
			"message_id":         delivery["message_id"],
			"thread_id":          delivery["thread_id"],
			"sender_agent_id":    message["sender_agent_id"],
			"recipient_agent_id": delivery["recipient_agent_id"],
			"intent":             message["intent"],
			"visibility":         message["visibility"],
			"created_at":         message["created_at"],
		},
	}
	payload, _ := json.Marshal(event)

	s.mu.Lock()
	conns := make([]*websocket.Conn, 0, len(s.conns))
	for conn := range s.conns {
		conns = append(conns, conn)
	}
	s.mu.Unlock()

	for _, conn := range conns {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		err := conn.Write(ctx, websocket.MessageText, payload)
		cancel()
		if err != nil {
			s.mu.Lock()
			delete(s.conns, conn)
			s.mu.Unlock()
			conn.Close(websocket.StatusAbnormalClosure, "write failed")
			log.Printf("dropped stream client: %v", err)
		}
	}
}

func splitPath(path string) []string {
	return strings.FieldsFunc(path, func(r rune) bool { return r == '/' })
}

func writeJSON(w http.ResponseWriter, body map[string]any) {
	payload, _ := json.Marshal(body)
	_, _ = w.Write(payload)
}
