package agentcli

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

type historyRoundTrip func(*http.Request) (*http.Response, error)

func (f historyRoundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func historyHTTPResponse(value any) *http.Response {
	payload, _ := json.Marshal(value)
	return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(payload)), Header: http.Header{}}
}

func runtimeHistoryItems(count int) []map[string]any {
	items := make([]map[string]any, 0, count)
	for i := count - 1; i >= 0; i-- {
		id := fmt.Sprintf("%06d", i)
		created := time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC).Add(time.Duration(i) * time.Second).Format(time.RFC3339)
		items = append(items, map[string]any{
			"delivery": map[string]any{"delivery_id": "d" + id, "message_id": "m" + id, "thread_id": "t" + id, "status": "delivered", "created_at": created},
			"message":  map[string]any{"message_id": "m" + id, "thread_id": "t" + id, "sender_handle": "@other:gulls.ai", "content_inline": "message needle " + id, "created_at": created},
		})
	}
	return items
}

func newHistoryRuntimeTestProfile(t *testing.T) (*runtimeProfile, *runtimeServer, RuntimeProfile) {
	t.Helper()
	dir := t.TempDir()
	store, err := OpenHistoryStore(filepath.Join(dir, "history.sqlite3"), "runtime")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	server := &runtimeServer{ctx: context.Background(), profiles: map[string]*runtimeProfile{}, history: store}
	profile := RuntimeProfile{ID: "gull-one", Revision: "r1", Monitoring: true, Environment: map[string]string{
		"SEAGULL_API_URL": "https://history.example", "SEAGULL_AGENT_HANDLE": "@one:gulls.ai",
		"SEAGULL_AGENT_CONTEXT_DIR": filepath.Join(dir, "context"), "SEAGULL_AGENT_ENV_FILE": filepath.Join(dir, "no-env"),
	}}
	p, err := newRuntimeProfile(context.Background(), profile, server)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(p.cancel)
	server.profiles[profile.ID] = p
	return p, server, profile
}

func setHistoryInboxTransport(p *runtimeProfile, source *[]map[string]any, calls *int, paged bool) {
	p.client.Client = &http.Client{Transport: historyRoundTrip(func(r *http.Request) (*http.Response, error) {
		*calls++
		items := *source
		start := 0
		if cursor := r.URL.Query().Get("cursor"); cursor != "" {
			for i, item := range items {
				if itemDeliveryID(item) == cursor {
					start = i + 1
					break
				}
			}
		}
		limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
		if limit <= 0 {
			limit = 100
		}
		end := min(start+limit, len(items))
		result := map[string]any{"items": historyItems(items[start:end])}
		if paged {
			result["has_more"] = end < len(items)
			if end < len(items) {
				result["next_cursor"] = itemDeliveryID(items[end-1])
			}
		}
		return historyHTTPResponse(result), nil
	})}
}

func finishHistorySync(t *testing.T, p *runtimeProfile) {
	t.Helper()
	for i := 0; i < 20; i++ {
		more, err := p.syncNextHistoryPage(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		if !more {
			return
		}
	}
	t.Fatal("history sync did not finish within the fixture page count")
}

func TestHistoryRuntimeBackfillsAndResumesAcrossCredentialRotation(t *testing.T) {
	p, server, profile := newHistoryRuntimeTestProfile(t)
	items := runtimeHistoryItems(245)
	calls := 0
	setHistoryInboxTransport(p, &items, &calls, true)
	if err := p.refresh(context.Background(), true); err != nil {
		t.Fatal(err)
	}
	if got, _ := p.history.Query(HistoryQuery{Limit: 1}); got.Total != 100 {
		t.Fatalf("initial total = %d", got.Total)
	}
	more, err := p.syncNextHistoryPage(context.Background())
	if err != nil || !more {
		t.Fatalf("first page = more %v, error %v", more, err)
	}

	profile.Revision = "r2"
	restarted, err := newRuntimeProfile(context.Background(), profile, server)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.cancel()
	setHistoryInboxTransport(restarted, &items, &calls, true)
	finishHistorySync(t, restarted)
	got, err := restarted.history.Query(HistoryQuery{Limit: 1, Query: "needle"})
	if err != nil || got.Total != 245 || !restarted.historyComplete() {
		t.Fatalf("resumed = %d complete %v error %v", got.Total, restarted.historyComplete(), err)
	}
	if len(inboxItems(restarted.inbox)) != 100 {
		t.Fatal("backfill expanded the notification snapshot")
	}

	// A burst larger than one poll page must not leave a gap before the old
	// completed anchor, even when the next poll occurs partway through catchup.
	items = runtimeHistoryItems(480)
	if err := restarted.refresh(context.Background(), true); err != nil {
		t.Fatal(err)
	}
	if more, err := restarted.syncNextHistoryPage(context.Background()); err != nil || !more {
		t.Fatalf("catchup start = %v %v", more, err)
	}
	items = runtimeHistoryItems(610)
	if err := restarted.refresh(context.Background(), true); err != nil {
		t.Fatal(err)
	}
	finishHistorySync(t, restarted)
	finishHistorySync(t, restarted)
	got, err = restarted.history.Query(HistoryQuery{Limit: 1})
	if err != nil || got.Total != 610 {
		t.Fatalf("burst total = %d, error %v", got.Total, err)
	}
}

func TestHistoryRuntimeQueryWorksOfflineAndScopesConnections(t *testing.T) {
	p, server, profile := newHistoryRuntimeTestProfile(t)
	if err := p.history.ImportInboxPageNamed("inbox", runtimeHistoryItems(135), "", true); err != nil {
		t.Fatal(err)
	}
	calls := 0
	p.client.Client = &http.Client{Transport: historyRoundTrip(func(*http.Request) (*http.Response, error) {
		calls++
		return nil, fmt.Errorf("offline")
	})}
	var output bytes.Buffer
	server.handle(RuntimeRequest{Version: 1, ID: "history", Operation: "command", ProfileID: profile.ID, Revision: profile.Revision,
		Arguments: []string{"--json", "history", "--limit", "50", "--query", "needle"}}, &output)
	var response RuntimeResponse
	if err := json.Unmarshal(output.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if response.ExitCode != 0 || calls != 0 {
		t.Fatalf("offline history: %#v calls=%d", response, calls)
	}
	var page struct {
		Items      []any
		Total      int
		NextCursor string `json:"next_cursor"`
	}
	if err := json.Unmarshal([]byte(response.Stdout), &page); err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 50 || page.Total != 135 || page.NextCursor == "" {
		t.Fatalf("history page = %#v", page)
	}

	other := profile
	other.ID = "gull-two"
	other.Environment = map[string]string{}
	for key, value := range profile.Environment {
		other.Environment[key] = value
	}
	other.Environment["SEAGULL_NODE_ID"] = "another-owner-node"
	second, err := newRuntimeProfile(context.Background(), other, server)
	if err != nil {
		t.Fatal(err)
	}
	defer second.cancel()
	if got, _ := second.history.Query(HistoryQuery{Limit: 1}); got.Total != 0 {
		t.Fatal("another connection saw cached messages")
	}
	if _, err := second.history.Query(HistoryQuery{Cursor: page.NextCursor, Query: "needle"}); err == nil {
		t.Fatal("cross-scope cursor accepted")
	}
}

func TestHistoryRuntimeLegacyServerDoesNotClaimFullSync(t *testing.T) {
	p, _, _ := newHistoryRuntimeTestProfile(t)
	items := runtimeHistoryItems(200)
	calls := 0
	setHistoryInboxTransport(p, &items, &calls, false)
	if err := p.refresh(context.Background(), true); err != nil {
		t.Fatal(err)
	}
	finishHistorySync(t, p)
	if p.historyComplete() {
		t.Fatal("legacy truncated server marked complete")
	}
	if calls != 1 {
		t.Fatalf("legacy polling calls = %d", calls)
	}
}

func TestHistoryRuntimeSharesConnectionAcrossProfileIDs(t *testing.T) {
	p, server, profile := newHistoryRuntimeTestProfile(t)
	if err := p.history.ImportInboxPageNamed("inbox", runtimeHistoryItems(135), "", true); err != nil {
		t.Fatal(err)
	}
	// The Mac uses a stored UUID while the standalone CLI derives its profile
	// ID from the same connection. Both must retain the same durable history.
	cliID, err := RuntimeProfileID(flattenEnv(profile.Environment))
	if err != nil {
		t.Fatal(err)
	}
	profile.ID, profile.Revision = cliID, "cli-revision"
	standalone, err := newRuntimeProfile(context.Background(), profile, server)
	if err != nil {
		t.Fatal(err)
	}
	defer standalone.cancel()
	got, err := standalone.history.Query(HistoryQuery{Limit: 1})
	if err != nil || got.Total != 135 || standalone.history.Scope() != p.history.Scope() {
		t.Fatalf("CLI history = %d, same scope %v, error %v", got.Total, standalone.history.Scope() == p.history.Scope(), err)
	}
	changed := p.config
	changed.AgentHandle = "@another:gulls.ai"
	if historyProfileScope(changed) == p.history.Scope() {
		t.Fatal("different Gull reused a history scope")
	}
	changed = p.config
	changed.APIURL = "https://another-server.example"
	if historyProfileScope(changed) == p.history.Scope() {
		t.Fatal("different server reused a history scope")
	}
}

func TestHistoryRuntimeServiceReopensDatabaseOffline(t *testing.T) {
	dir := t.TempDir()
	profile := RuntimeProfile{ID: "mac-profile", Revision: "r1", Monitoring: false, Environment: map[string]string{
		"SEAGULL_API_URL": "https://history.example", "SEAGULL_AGENT_HANDLE": "@one:gulls.ai",
		"SEAGULL_AGENT_CONTEXT_DIR": dir, "SEAGULL_AGENT_ENV_FILE": filepath.Join(dir, "no-env"),
	}}
	cfg, err := LoadConfig(flattenEnv(profile.Environment), ConfigOverrides{})
	if err != nil {
		t.Fatal(err)
	}
	store, err := OpenHistoryStore(filepath.Join(dir, "history.sqlite3"), historyProfileScope(cfg))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.ImportInboxPageNamed("inbox", runtimeHistoryItems(135), "", true); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"mac-profile", "standalone-cli"} {
		profile.ID = id
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		input, writer := io.Pipe()
		events := newRuntimeEventSink()
		done := make(chan error, 1)
		go func() {
			done <- runtimeServeWithProfiles(ctx, "", true, input, events, io.Discard, []RuntimeProfile{profile})
		}()
		request := RuntimeRequest{Version: 1, ID: "history-summary", Operation: "command", ProfileID: id,
			Revision: profile.Revision, Arguments: []string{"--json", "history", "summary"}}
		if err := writeRuntimeLine(writer, request); err != nil {
			cancel()
			t.Fatal(err)
		}
		var response RuntimeResponse
		for response.ID != request.ID {
			select {
			case line := <-events.lines:
				if err := json.Unmarshal([]byte(line), &response); err != nil {
					cancel()
					t.Fatal(err)
				}
			case <-ctx.Done():
				cancel()
				t.Fatal("offline history request did not finish")
			}
		}
		var summary HistorySummary
		decodeErr := json.Unmarshal([]byte(response.Stdout), &summary)
		cancel()
		_ = writer.Close()
		if err := <-done; err != nil {
			t.Fatal(err)
		}
		if response.ExitCode != 0 || decodeErr != nil || summary.TotalDeliveries != 135 {
			t.Fatalf("%s summary = %#v, decode %v, response %#v", id, summary, decodeErr, response)
		}
	}
}

func TestHistoryRuntimeOldDeliveryUsesFreshInstructions(t *testing.T) {
	p, _, _ := newHistoryRuntimeTestProfile(t)
	old := runtimeHistoryItems(1)[0]
	old["local_runtime"] = map[string]any{"instructions": "stale private instructions"}
	if err := p.history.ImportInboxPageNamed("inbox", []map[string]any{old}, "", true); err != nil {
		t.Fatal(err)
	}
	p.client.Client = &http.Client{Transport: historyRoundTrip(func(*http.Request) (*http.Response, error) {
		return historyHTTPResponse(map[string]any{"items": []any{}, "local_runtime": map[string]any{"instructions": "fresh private instructions"}}), nil
	})}
	item, err := requireInboxDelivery(p.commandClient(), p.config, "d000000", 100)
	if err != nil || item == nil {
		t.Fatalf("historical open = %v %v", item, err)
	}
	if strings.Contains(mustJSON(item), "stale private instructions") {
		t.Fatal("cached private instructions leaked into a context")
	}
	if stringValue(objectValue(item, "local_runtime"), "instructions") != "fresh private instructions" {
		t.Fatal("historical delivery did not use freshly authenticated instructions")
	}
}

func TestHistoryRuntimeThreadPagesAndOfflineFallback(t *testing.T) {
	p, _, _ := newHistoryRuntimeTestProfile(t)
	messages := make([]map[string]any, 205)
	for i := range messages {
		messages[i] = map[string]any{"message_id": fmt.Sprintf("m%06d", i), "thread_id": "thread", "content_inline": fmt.Sprintf("body %d", i),
			"created_at": time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC).Add(time.Duration(i) * time.Second).Format(time.RFC3339)}
	}
	calls := 0
	p.client.Client = &http.Client{Transport: historyRoundTrip(func(r *http.Request) (*http.Response, error) {
		calls++
		end := len(messages)
		if raw := r.URL.Query().Get("cursor"); raw != "" {
			end, _ = strconv.Atoi(raw)
		}
		start := max(0, end-100)
		result := map[string]any{"thread_id": "thread", "messages": messages[start:end], "has_more": start > 0}
		if start > 0 {
			result["next_cursor"] = strconv.Itoa(start)
		}
		return historyHTTPResponse(result), nil
	})}
	client := p.commandClient().(*runtimeProfileClient)
	seen := map[string]bool{}
	cursor := ""
	for i := 0; i < 10; i++ {
		page, err := client.GetThreadPage("thread", 50, cursor)
		if err != nil {
			t.Fatal(err)
		}
		previous := ""
		for _, raw := range threadMessages(page) {
			message := raw.(map[string]any)
			id := stringValue(message, "message_id")
			if seen[id] || (previous != "" && id <= previous) {
				t.Fatalf("duplicate or unordered message %s", id)
			}
			seen[id], previous = true, id
		}
		cursor = stringValue(page, "next_cursor")
		if cursor == "" {
			break
		}
	}
	if len(seen) != 205 {
		t.Fatalf("thread pages contain %d messages", len(seen))
	}
	beforeInvalid := calls
	if _, err := client.GetThreadPage("thread", 50, "invalid"); err == nil || calls != beforeInvalid {
		t.Fatal("invalid cursor used network")
	}
	p.client.Client = &http.Client{Transport: historyRoundTrip(func(*http.Request) (*http.Response, error) { return nil, fmt.Errorf("offline") })}
	page, err := client.GetThreadPage("thread", 50, "")
	if err != nil || len(threadMessages(page)) != 50 || page["offline"] != true {
		t.Fatalf("offline thread = %v %v", page, err)
	}
	p.client.Client = &http.Client{Transport: historyRoundTrip(func(*http.Request) (*http.Response, error) {
		response := historyHTTPResponse(map[string]any{"error": "forbidden"})
		response.StatusCode = http.StatusForbidden
		return response, nil
	})}
	if _, err := client.GetThreadPage("thread", 50, ""); !isRuntimeAuthorizationError(err) {
		t.Fatalf("cached thread bypassed revoked authorization: %v", err)
	}
}

func TestHistoryRuntimeDecisionUpdatesOlderCachedDelivery(t *testing.T) {
	p, _, _ := newHistoryRuntimeTestProfile(t)
	if err := p.history.ImportInboxPageNamed("inbox", runtimeHistoryItems(1), "", true); err != nil {
		t.Fatal(err)
	}
	p.client.Client = &http.Client{Transport: historyRoundTrip(func(*http.Request) (*http.Response, error) {
		return historyHTTPResponse(map[string]any{"delivery": map[string]any{"delivery_id": "d000000", "status": "replied"}}), nil
	})}
	_, err := p.commandClient().DecideDelivery("d000000", p.config.AgentHandle, "reply", "approved reply", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	item, err := p.history.GetDelivery("d000000")
	if err != nil || stringValue(objectValue(item, "delivery"), "status") != "replied" || itemMessageID(item) != "m000000" {
		t.Fatalf("updated older delivery = %v %v", item, err)
	}
}
