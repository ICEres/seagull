package agentcli

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type fakeClient struct {
	decisions             []map[string]any
	acks                  []map[string]any
	sentMessages          []map[string]any
	threadContextRequests []string
	inbox                 map[string]any
}

func newFakeClient() *fakeClient {
	return &fakeClient{
		inbox: map[string]any{
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
		},
	}
}

func (f *fakeClient) GetAgent(handle string) (map[string]any, error) {
	return map[string]any{"agent": map[string]any{"handle": handle, "status": "active", "trigger_mode": "manual"}}, nil
}

func (f *fakeClient) GetInbox(handle string, limit int) (map[string]any, error) {
	items := f.inbox["items"].([]any)
	if limit > len(items) {
		limit = len(items)
	}
	return map[string]any{"items": items[:limit]}, nil
}

func (f *fakeClient) GetThread(threadID string, limit int) (map[string]any, error) {
	return map[string]any{"thread_id": threadID, "messages": []any{}}, nil
}

func (f *fakeClient) GetThreadContext(threadID string) (map[string]any, error) {
	f.threadContextRequests = append(f.threadContextRequests, threadID)
	return map[string]any{"thread": map[string]any{"thread_id": threadID}, "recent_messages": []any{}}, nil
}

func (f *fakeClient) SendMessage(senderHandle string, recipientHandles []string, content string, threadID string, intent string, visibility string) (map[string]any, error) {
	body := map[string]any{
		"sender_handle":     senderHandle,
		"recipient_handles": recipientHandles,
		"content":           content,
		"thread_id":         threadID,
		"intent":            intent,
		"visibility":        visibility,
	}
	f.sentMessages = append(f.sentMessages, body)
	return map[string]any{"message_id": "message_sent", "thread_id": firstClean(threadID, "thread_new")}, nil
}

func (f *fakeClient) AckMessage(messageID string, recipientHandle string) (map[string]any, error) {
	body := map[string]any{"message_id": messageID, "recipient_handle": recipientHandle}
	f.acks = append(f.acks, body)
	return map[string]any{"deliveries": []any{map[string]any{"message_id": messageID, "recipient_handle": recipientHandle, "status": "acked"}}}, nil
}

func (f *fakeClient) DecideDelivery(deliveryID string, agentHandle string, decision string, content string, note string) (map[string]any, error) {
	body := map[string]any{
		"delivery_id":  deliveryID,
		"agent_handle": agentHandle,
		"decision":     decision,
		"content":      content,
		"note":         note,
	}
	f.decisions = append(f.decisions, body)
	reply := any(nil)
	if decision == "reply" {
		reply = map[string]any{"message_id": "message_reply", "thread_id": "thread_1"}
	}
	status := "ignored"
	if decision == "reply" {
		status = "replied"
	}
	return map[string]any{"delivery": map[string]any{"delivery_id": deliveryID, "status": status}, "reply": reply}, nil
}

func testEnv(tmp string) []string {
	return []string{
		"SEAGULL_API_URL=https://api.example.test",
		"SEAGULL_AGENT_HANDLE=@worker:gulls.ai",
		"SEAGULL_CONNECTOR_TOKEN=secret-token",
		"SEAGULL_AGENT_CONTEXT_DIR=" + tmp,
	}
}

func responseRulesJSON(overrides map[string]any) string {
	rules := map[string]any{
		"schema_version":  SchemaVersion,
		"persona":         "Pragmatic test responder.",
		"style":           "Short and factual.",
		"reply_posture":   OutcomeDraftReply,
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
	}
	for key, value := range overrides {
		rules[key] = value
	}
	payload, _ := json.Marshal(rules)
	return string(payload)
}

func TestDraftReplyGeneratesDraftWithoutDeliveryDecision(t *testing.T) {
	tmp := t.TempDir()
	fake := newFakeClient()
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	env := append(testEnv(tmp), "SEAGULL_RESPONSE_RULES_JSON="+responseRulesJSON(nil))

	code := Main([]string{"draft-reply", "delivery_1"}, &stdout, &stderr, env, fake)

	if code != 0 {
		t.Fatalf("code = %d, stderr = %s", code, stderr.String())
	}
	if len(fake.decisions) != 0 || len(fake.acks) != 0 || len(fake.sentMessages) != 0 {
		t.Fatalf("draft-reply caused side effects: decisions=%v acks=%v sent=%v", fake.decisions, fake.acks, fake.sentMessages)
	}
	if got := strings.Join(fake.threadContextRequests, ","); got != "thread_1" {
		t.Fatalf("thread context requests = %q", got)
	}
	output := stdout.String()
	for _, want := range []string{"Outcome: draft_reply", "Draft (not sent):", "Please review the deploy notes.", "No delivery decision was submitted."} {
		if !strings.Contains(output, want) {
			t.Fatalf("output missing %q:\n%s", want, output)
		}
	}
	if strings.Contains(output, "secret-token") || strings.Contains(stderr.String(), "secret-token") {
		t.Fatalf("token leaked in output")
	}
}

func TestDraftReplyJSONIncludesSafeMetadata(t *testing.T) {
	tmp := t.TempDir()
	fake := newFakeClient()
	var stdout bytes.Buffer
	env := append(testEnv(tmp), "SEAGULL_RESPONSE_RULES_JSON="+responseRulesJSON(nil))

	code := Main([]string{"--json", "draft-reply", "delivery_1"}, &stdout, &bytes.Buffer{}, env, fake)

	if code != 0 {
		t.Fatalf("code = %d", code)
	}
	var payload map[string]any
	if err := json.Unmarshal(stdout.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload["outcome"] != OutcomeDraftReply || payload["delivery_id"] != "delivery_1" {
		t.Fatalf("unexpected payload: %#v", payload)
	}
	if payload["draft_sent"] != false || payload["delivery_decision_submitted"] != false {
		t.Fatalf("draft payload did not preserve no-send metadata: %#v", payload)
	}
	if len(fake.decisions) != 0 {
		t.Fatalf("decisions = %#v", fake.decisions)
	}
	if strings.Contains(stdout.String(), "secret-token") {
		t.Fatalf("token leaked in json")
	}
}

func TestDraftReplyAskHumanAndNoReplyDoNotSend(t *testing.T) {
	tmp := t.TempDir()
	for _, tc := range []struct {
		name string
		env  []string
		want string
	}{
		{name: "default", env: testEnv(tmp), want: "Outcome: ask_human"},
		{name: "no_reply", env: append(testEnv(tmp), "SEAGULL_RESPONSE_RULES_JSON="+responseRulesJSON(map[string]any{"reply_posture": OutcomeNoReply})), want: "Outcome: no_reply"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			fake := newFakeClient()
			var stdout bytes.Buffer
			code := Main([]string{"draft-reply", "delivery_1"}, &stdout, &bytes.Buffer{}, tc.env, fake)
			if code != 0 {
				t.Fatalf("code = %d", code)
			}
			if len(fake.decisions) != 0 || len(fake.acks) != 0 || len(fake.sentMessages) != 0 {
				t.Fatalf("unexpected side effects")
			}
			if !strings.Contains(stdout.String(), tc.want) || !strings.Contains(stdout.String(), "No draft generated. No reply sent.") {
				t.Fatalf("unexpected output:\n%s", stdout.String())
			}
		})
	}
}

func TestOpenWritesContextFileAndLatest(t *testing.T) {
	tmp := t.TempDir()
	fake := newFakeClient()
	var stdout bytes.Buffer

	code := Main([]string{"open", "delivery_1"}, &stdout, &bytes.Buffer{}, testEnv(tmp), fake)

	if code != 0 {
		t.Fatalf("code = %d", code)
	}
	deliveryPath := filepath.Join(tmp, "delivery_1.md")
	deliveryText, err := os.ReadFile(deliveryPath)
	if err != nil {
		t.Fatal(err)
	}
	latestText, err := os.ReadFile(filepath.Join(tmp, "latest.md"))
	if err != nil {
		t.Fatal(err)
	}
	if string(deliveryText) != string(latestText) {
		t.Fatal("latest.md does not match delivery context")
	}
	if !strings.Contains(string(deliveryText), "untrusted input") || !strings.Contains(string(deliveryText), "Please review the deploy notes.") {
		t.Fatalf("unexpected context:\n%s", string(deliveryText))
	}
}

func TestWatchOnceDedupes(t *testing.T) {
	tmp := t.TempDir()
	fake := newFakeClient()
	env := testEnv(tmp)

	var first bytes.Buffer
	firstCode := Main([]string{"watch", "--once"}, &first, &bytes.Buffer{}, env, fake)
	var second bytes.Buffer
	secondCode := Main([]string{"watch", "--once"}, &second, &bytes.Buffer{}, env, fake)

	if firstCode != 0 || secondCode != 0 {
		t.Fatalf("codes = %d, %d", firstCode, secondCode)
	}
	if !strings.Contains(first.String(), "1 new delivery item(s).") {
		t.Fatalf("first output: %s", first.String())
	}
	if !strings.Contains(second.String(), "No new deliveries.") {
		t.Fatalf("second output: %s", second.String())
	}
}

func TestHTTPClientUsesMessageHubPathsAndBearerToken(t *testing.T) {
	var method string
	var path string
	var auth string
	transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		method = r.Method
		path = r.URL.RequestURI()
		auth = r.Header.Get("authorization")
		return &http.Response{
			StatusCode: http.StatusOK,
			Header:     http.Header{"content-type": []string{"application/json"}},
			Body:       io.NopCloser(strings.NewReader(`{"items":[]}`)),
		}, nil
	})

	client := NewHTTPClient("https://api.example.test", "secret-token")
	client.Timeout = 0
	client.Client = &http.Client{Transport: transport}
	result, err := client.GetInbox("@worker:gulls.ai", 5)

	if err != nil {
		t.Fatal(err)
	}
	if len(inboxItems(result)) != 0 {
		t.Fatalf("unexpected result: %#v", result)
	}
	if method != http.MethodGet || path != "/agents/%40worker%3Agulls.ai/inbox?limit=5" {
		t.Fatalf("request = %s %s", method, path)
	}
	if auth != "Bearer secret-token" {
		t.Fatalf("authorization = %q", auth)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req)
}
