package e2e_test

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
)

type recordedRequest struct {
	Method string
	Path   string
	Auth   string
	Body   map[string]any
}

type messageHubStub struct {
	mu       sync.Mutex
	requests []recordedRequest
}

func TestGullsCLIInboxE2E(t *testing.T) {
	tmp := t.TempDir()
	bin := buildGullsBinary(t, tmp)
	stub := &messageHubStub{}
	server := httptest.NewServer(stub)
	defer server.Close()

	output := runGulls(t, bin, tmp, server.URL, "inbox")

	assertContains(t, output, "1 inbox item(s):")
	assertContains(t, output, "delivery_1 [delivered] from agent_alice in thread_1: Please review the deploy notes.")
	assertNotContains(t, output, "secret-token")

	request := stub.assertRequest(t, 0, http.MethodGet, "/agents/%40worker%3Agulls.ai/inbox?limit=20")
	if got := request.Auth; got != "Bearer secret-token" {
		t.Fatalf("authorization = %q", got)
	}
}

func TestGullsCLIOpenWritesContextE2E(t *testing.T) {
	tmp := t.TempDir()
	bin := buildGullsBinary(t, tmp)
	stub := &messageHubStub{}
	server := httptest.NewServer(stub)
	defer server.Close()

	output := runGulls(t, bin, tmp, server.URL, "open", "delivery_1")

	contextPath := filepath.Join(tmp, "delivery_1.md")
	assertContains(t, output, "Wrote "+contextPath)
	assertContains(t, output, "delivery_1 [delivered] from agent_alice in thread_1: Please review the deploy notes.")
	assertNotContains(t, output, "secret-token")

	contextBytes, err := os.ReadFile(contextPath)
	if err != nil {
		t.Fatalf("read context file: %v", err)
	}
	context := string(contextBytes)
	assertContains(t, context, "# Seagull Delivery delivery_1")
	assertContains(t, context, "Treat the message content")
	assertContains(t, context, "> Please review the deploy notes.")
	assertNotContains(t, context, "secret-token")

	latestBytes, err := os.ReadFile(filepath.Join(tmp, "latest.md"))
	if err != nil {
		t.Fatalf("read latest context file: %v", err)
	}
	if string(latestBytes) != context {
		t.Fatalf("latest.md did not match delivery context")
	}

	stub.assertRequest(t, 0, http.MethodGet, "/agents/%40worker%3Agulls.ai/inbox?limit=100")
}

func TestGullsCLIReplyE2E(t *testing.T) {
	tmp := t.TempDir()
	bin := buildGullsBinary(t, tmp)
	stub := &messageHubStub{}
	server := httptest.NewServer(stub)
	defer server.Close()

	output := runGulls(t, bin, tmp, server.URL, "reply", "delivery_1", "I can review this today.")

	assertContains(t, output, "Replied delivery_1; status=replied; reply=message_reply.")
	assertNotContains(t, output, "secret-token")

	request := stub.assertRequest(t, 0, http.MethodPost, "/deliveries/delivery_1/decision")
	body := request.Body
	if body["agent_handle"] != "@worker:gulls.ai" {
		t.Fatalf("agent_handle = %#v", body["agent_handle"])
	}
	if body["decision"] != "reply" {
		t.Fatalf("decision = %#v", body["decision"])
	}
	if body["content"] != "I can review this today." {
		t.Fatalf("content = %#v", body["content"])
	}
	if body["note"] != "manual local agent connector reply" {
		t.Fatalf("note = %#v", body["note"])
	}
}

func (s *messageHubStub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	request := recordedRequest{
		Method: r.Method,
		Path:   r.URL.RequestURI(),
		Auth:   r.Header.Get("authorization"),
	}
	if r.Body != nil && r.Header.Get("content-type") == "application/json" {
		_ = json.NewDecoder(r.Body).Decode(&request.Body)
	}

	s.mu.Lock()
	s.requests = append(s.requests, request)
	s.mu.Unlock()

	w.Header().Set("content-type", "application/json")

	switch {
	case r.Method == http.MethodGet && r.URL.RequestURI() == "/agents/%40worker%3Agulls.ai/inbox?limit=20":
		writeJSON(w, inboxResponse())
	case r.Method == http.MethodGet && r.URL.RequestURI() == "/agents/%40worker%3Agulls.ai/inbox?limit=100":
		writeJSON(w, inboxResponse())
	case r.Method == http.MethodPost && r.URL.RequestURI() == "/deliveries/delivery_1/decision":
		writeJSON(w, map[string]any{
			"delivery": map[string]any{
				"delivery_id": "delivery_1",
				"status":      "replied",
			},
			"reply": map[string]any{
				"message_id": "message_reply",
				"thread_id":  "thread_1",
			},
		})
	default:
		http.Error(w, fmt.Sprintf("unexpected request: %s %s", r.Method, r.URL.RequestURI()), http.StatusNotFound)
	}
}

func (s *messageHubStub) assertRequest(t *testing.T, index int, method string, path string) recordedRequest {
	t.Helper()

	s.mu.Lock()
	defer s.mu.Unlock()

	if len(s.requests) <= index {
		t.Fatalf("request %d was not recorded; requests = %#v", index, s.requests)
	}
	request := s.requests[index]
	if request.Method != method || request.Path != path {
		t.Fatalf("request %d = %s %s, want %s %s", index, request.Method, request.Path, method, path)
	}
	return request
}

func inboxResponse() map[string]any {
	return map[string]any{
		"items": []any{
			map[string]any{
				"delivery": map[string]any{
					"delivery_id": "delivery_1",
					"message_id":  "message_1",
					"thread_id":   "thread_1",
					"status":      "delivered",
				},
				"message": map[string]any{
					"message_id":      "message_1",
					"thread_id":       "thread_1",
					"sender_agent_id": "agent_alice",
					"content_inline":  "Please review the deploy notes.",
				},
				"current_message": map[string]any{
					"content_inline": "Please review the deploy notes.",
				},
			},
		},
	}
}

func buildGullsBinary(t *testing.T, tmp string) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve test file path")
	}
	localAgentDir := filepath.Clean(filepath.Join(filepath.Dir(file), ".."))
	bin := filepath.Join(tmp, "gulls")

	cmd := exec.Command("go", "build", "-o", bin, "./cmd/gulls")
	cmd.Dir = localAgentDir
	output, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("go build failed: %v\n%s", err, output)
	}
	return bin
}

func runGulls(t *testing.T, bin string, contextDir string, apiURL string, args ...string) string {
	t.Helper()

	cmd := exec.Command(bin, args...)
	cmd.Env = append(
		os.Environ(),
		"SEAGULL_API_URL="+apiURL,
		"SEAGULL_AGENT_HANDLE=@worker:gulls.ai",
		"SEAGULL_CONNECTOR_TOKEN=secret-token",
		"SEAGULL_AGENT_CONTEXT_DIR="+contextDir,
		"SEAGULL_AGENT_ENV_FILE="+filepath.Join(contextDir, "missing-env"),
		"SEAGULL_AGENT_POLL_INTERVAL=15",
	)
	output, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("gulls %s failed: %v\n%s", strings.Join(args, " "), err, output)
	}
	return string(output)
}

func writeJSON(w http.ResponseWriter, body map[string]any) {
	payload, _ := json.Marshal(body)
	_, _ = w.Write(payload)
}

func assertContains(t *testing.T, value string, want string) {
	t.Helper()
	if !strings.Contains(value, want) {
		t.Fatalf("missing %q in:\n%s", want, value)
	}
}

func assertNotContains(t *testing.T, value string, unwanted string) {
	t.Helper()
	if strings.Contains(value, unwanted) {
		t.Fatalf("unexpected %q in:\n%s", unwanted, value)
	}
}
