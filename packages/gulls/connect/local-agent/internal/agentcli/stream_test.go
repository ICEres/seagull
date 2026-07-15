package agentcli

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/coder/websocket"
)

func TestValidateStreamURL(t *testing.T) {
	for _, valid := range []string{"ws://localhost:8200/stream", "wss://example.test/$default"} {
		if err := ValidateStreamURL(valid); err != nil {
			t.Fatalf("ValidateStreamURL(%q) = %v", valid, err)
		}
	}
	for _, invalid := range []string{"http://example.test", "example.test", ""} {
		if err := ValidateStreamURL(invalid); err == nil {
			t.Fatalf("ValidateStreamURL(%q) should fail", invalid)
		}
	}
}

func TestRunStreamDeliversEventsAndAuthHeader(t *testing.T) {
	var gotAuth atomic.Value
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth.Store(r.Header.Get("Authorization"))
		conn, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close(websocket.StatusNormalClosure, "")
		_ = conn.Write(r.Context(), websocket.MessageText, []byte(`{"type":"seagull.delivery.created.v1","data":{"delivery_id":"delivery_9"}}`))
		<-r.Context().Done()
	}))
	defer server.Close()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	events := make(chan []byte, 1)
	connected := make(chan struct{}, 1)

	done := make(chan error, 1)
	go func() {
		done <- RunStream(ctx, "ws"+strings.TrimPrefix(server.URL, "http"), "secret-token", StreamCallbacks{
			OnConnect: func() { connected <- struct{}{} },
			OnEvent:   func(raw []byte) { events <- raw },
		})
	}()

	select {
	case <-connected:
	case <-time.After(5 * time.Second):
		t.Fatal("stream did not connect")
	}
	select {
	case raw := <-events:
		if !strings.Contains(string(raw), "delivery_9") {
			t.Fatalf("unexpected event: %s", raw)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("event not received")
	}
	if auth := gotAuth.Load(); auth != "Bearer secret-token" {
		t.Fatalf("authorization header = %v", auth)
	}

	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("RunStream returned error on cancel: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("RunStream did not stop on cancel")
	}
}

func TestRunStreamReconnects(t *testing.T) {
	var connects atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		if connects.Add(1) == 1 {
			// Drop the first connection immediately to force a reconnect.
			conn.Close(websocket.StatusGoingAway, "bye")
			return
		}
		defer conn.Close(websocket.StatusNormalClosure, "")
		<-r.Context().Done()
	}))
	defer server.Close()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	connected := make(chan struct{}, 4)
	dropped := make(chan struct{}, 4)

	go RunStream(ctx, "ws"+strings.TrimPrefix(server.URL, "http"), "", StreamCallbacks{
		OnConnect: func() { connected <- struct{}{} },
		OnDrop:    func(error) { dropped <- struct{}{} },
	})

	for _, step := range []chan struct{}{connected, dropped, connected} {
		select {
		case <-step:
		case <-time.After(10 * time.Second):
			t.Fatalf("reconnect sequence stalled (connects=%d)", connects.Load())
		}
	}
	if connects.Load() < 2 {
		t.Fatalf("expected at least 2 connects, got %d", connects.Load())
	}
}

func TestRunStreamFailsFastOnFirstAuthRejection(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "forbidden", http.StatusForbidden)
	}))
	defer server.Close()

	err := RunStream(context.Background(), "ws"+strings.TrimPrefix(server.URL, "http"), "bad-token", StreamCallbacks{})
	if err == nil || !isStreamAuthError(err) {
		t.Fatalf("expected auth error, got %v", err)
	}
}

func TestWakeCoalesces(t *testing.T) {
	wake := NewWakeChannel()
	Wake(wake)
	Wake(wake)
	Wake(wake)
	select {
	case <-wake:
	default:
		t.Fatal("expected one pending wake")
	}
	select {
	case <-wake:
		t.Fatal("wakes did not coalesce")
	default:
	}
}

func TestWatchLoopStreamingWakesTriggerImmediatePoll(t *testing.T) {
	tmp := t.TempDir()
	fake := newFakeClient()

	// Stream server: send one event right away, then hold the connection.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close(websocket.StatusNormalClosure, "")
		_ = conn.Write(r.Context(), websocket.MessageText, []byte(`{"type":"seagull.delivery.created.v1","data":{"delivery_id":"delivery_1"}}`))
		<-r.Context().Done()
	}))
	defer server.Close()

	config := Config{
		APIURL:       "https://api.example.test",
		AgentHandle:  "@worker:gulls.ai",
		ContextDir:   tmp,
		StreamURL:    "ws" + strings.TrimPrefix(server.URL, "http"),
		PollInterval: time.Hour, // timer must not be what triggers the poll
	}

	notified := make(chan string, 4)
	notifier := func(title, body string) bool {
		notified <- body
		return true
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		done <- WatchLoopStreaming(ctx, fake, config, 20, true, notifier, nil)
	}()

	// The initial poll plus the event-triggered wake both hit PollOnce; the
	// notification proves the inbox item was processed well before the 1h timer.
	select {
	case <-notified:
	case <-time.After(10 * time.Second):
		t.Fatal("no notification from stream-woken poll")
	}

	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("WatchLoopStreaming returned error: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("WatchLoopStreaming did not stop on cancel")
	}
}
