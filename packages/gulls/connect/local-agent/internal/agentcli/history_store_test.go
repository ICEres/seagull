package agentcli

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"testing"
)

func testHistoryItem(id string, n int, status string) map[string]any {
	when := fmt.Sprintf("2026-01-01T00:00:%02dZ", n%60)
	return map[string]any{
		"delivery":        map[string]any{"delivery_id": id, "message_id": "m-" + id, "thread_id": "thread-" + fmt.Sprint(n%3), "status": status, "created_at": when},
		"message":         map[string]any{"message_id": "m-" + id, "thread_id": "thread-" + fmt.Sprint(n%3), "sender_agent_id": "agent-" + fmt.Sprint(n%4), "content_inline": fmt.Sprintf("hello item %d", n), "created_at": when},
		"current_message": map[string]any{"content_inline": fmt.Sprintf("hello item %d", n)},
	}
}

func openTestHistory(t *testing.T, scope string) *HistoryStore {
	t.Helper()
	s, err := OpenHistoryStore(filepath.Join(t.TempDir(), "history.sqlite3"), scope)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s
}

func TestHistoryStoreDurabilityAndIsolation(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "history.sqlite3")
	s, err := OpenHistoryStore(path, "scope-a")
	if err != nil {
		t.Fatal(err)
	}
	items := make([]map[string]any, 0, 125)
	for i := 0; i < 125; i++ {
		items = append(items, testHistoryItem(fmt.Sprintf("d-%03d", i), i, "delivered"))
	}
	if err := s.ImportInboxPage(items, "server-cursor", false); err != nil {
		t.Fatal(err)
	}
	page, err := s.Query(HistoryQuery{Limit: 20})
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 20 || page.Total != 125 || page.NextCursor == "" {
		t.Fatalf("first page = len %d total %d cursor %q", len(page.Items), page.Total, page.NextCursor)
	}
	seen := len(page.Items)
	cursor := page.NextCursor
	for cursor != "" {
		page, err = s.Query(HistoryQuery{Limit: 20, Cursor: cursor})
		if err != nil {
			t.Fatal(err)
		}
		if page.Total != 125 {
			t.Fatalf("cursor page total = %d", page.Total)
		}
		seen += len(page.Items)
		cursor = page.NextCursor
	}
	if seen != 125 {
		t.Fatalf("paged rows = %d", seen)
	}
	state, err := s.SyncState()
	if err != nil || state.Cursor != "server-cursor" || state.Complete {
		t.Fatalf("state=%+v err=%v", state, err)
	}
	if _, err := s.GetDelivery("d-020"); err != nil {
		t.Fatal(err)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = OpenHistoryStore(path, "scope-a")
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	page, err = s.Query(HistoryQuery{Limit: 2, Status: "delivered"})
	if err != nil || page.Total != 125 || len(page.Items) != 2 {
		t.Fatalf("reopen page=%+v err=%v", page, err)
	}
	other, err := OpenHistoryStore(path, "scope-b")
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	page, err = other.Query(HistoryQuery{Limit: 5})
	if err != nil || page.Total != 0 {
		t.Fatalf("scope isolation page=%+v err=%v", page, err)
	}
}

func TestHistoryStoreDuplicateStatusAndSearch(t *testing.T) {
	s := openTestHistory(t, "scope")
	item := testHistoryItem("d-1", 1, "pending")
	if err := s.ImportInboxPage([]map[string]any{item}, "", false); err != nil {
		t.Fatal(err)
	}
	item["delivery"].(map[string]any)["status"] = "acked"
	if err := s.ImportInboxPage([]map[string]any{item}, "", false); err != nil {
		t.Fatal(err)
	}
	page, err := s.Query(HistoryQuery{Limit: 10, Status: "acked"})
	if err != nil || page.Total != 1 {
		t.Fatalf("status query page=%+v err=%v", page, err)
	}
	page, err = s.Query(HistoryQuery{Limit: 10, Query: "hello (item)"})
	if err != nil || page.Total != 1 {
		t.Fatalf("fts query page=%+v err=%v", page, err)
	}
	if _, err = s.Query(HistoryQuery{Limit: 10, Cursor: "bad"}); err == nil {
		t.Fatal("invalid cursor accepted")
	}
	if err := s.SaveThread("thread-1", map[string]any{"thread_id": "thread-1", "messages": []any{map[string]any{"message_id": "tm-1", "content_inline": "cached thread", "sender_handle": "human"}}}, "thread-cursor"); err != nil {
		t.Fatal(err)
	}
	thread, err := s.Thread("thread-1")
	if err != nil || thread.Cursor != "thread-cursor" || thread.Payload["thread_id"] != "thread-1" {
		t.Fatalf("thread=%+v err=%v", thread, err)
	}
	page, err = s.Query(HistoryQuery{Limit: 10, Query: "cached thread"})
	if err != nil || page.Total != 0 {
		t.Fatalf("thread-only query should not expose delivery rows: %+v %v", page, err)
	}
}

func TestHistoryStoreEmptySummaryAndLiteralSenderSearch(t *testing.T) {
	s := openTestHistory(t, "scope")
	empty, err := s.Summary(7)
	if err != nil || empty.TotalDeliveries != 0 || empty.PendingDeliveries != 0 {
		t.Fatalf("empty summary=%+v err=%v", empty, err)
	}
	encoded, err := json.Marshal(empty)
	if err != nil || strings.Contains(string(encoded), `"daily_received":null`) || strings.Contains(string(encoded), `"relationships":null`) {
		t.Fatalf("empty summary arrays=%s err=%v", encoded, err)
	}
	item := map[string]any{
		"delivery": map[string]any{"delivery_id": "d-search", "message_id": "m-search", "status": "delivered", "created_at": "2026-01-01T00:00:00Z"},
		"message":  map[string]any{"message_id": "m-search", "sender_agent_id": "agent-id", "sender_handle": "alice@example.com", "content_inline": "你好世界", "created_at": "2026-01-01T00:00:00Z"},
	}
	if err := s.ImportInboxPage([]map[string]any{item}, "", false); err != nil {
		t.Fatal(err)
	}
	for _, query := range []string{"你好", "alice@example.com", "agent-id"} {
		page, err := s.Query(HistoryQuery{Query: query, Limit: 10})
		if err != nil || page.Total != 1 {
			t.Fatalf("literal query %q page=%+v err=%v", query, page, err)
		}
	}
}

func TestHistoryStoreThreadPersistenceFiltersPrivateFields(t *testing.T) {
	s := openTestHistory(t, "scope")
	payload := map[string]any{
		"thread_id":     "thread-private",
		"local_runtime": map[string]any{"instructions": "do not persist"},
		"next_cursor":   "next",
		"messages": []any{map[string]any{
			"message_id":     "m-private",
			"content_inline": "visible",
			"local_runtime":  map[string]any{"token": "secret"},
		}},
	}
	if err := s.SaveThread("thread-private", payload, "next"); err != nil {
		t.Fatal(err)
	}
	thread, err := s.Thread("thread-private")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(mustJSON(thread.Payload), "do not persist") || strings.Contains(mustJSON(thread.Payload), "secret") {
		t.Fatalf("private thread fields persisted: %#v", thread.Payload)
	}
	page, err := s.QueryThread("thread-private", 10, "")
	if err != nil || strings.Contains(mustJSON(page), "secret") {
		t.Fatalf("private message fields persisted: page=%#v err=%v", page, err)
	}
}

func TestHistoryStoreTransactionalImportAndSummary(t *testing.T) {
	s := openTestHistory(t, "scope")
	if err := s.ImportInboxPage([]map[string]any{testHistoryItem("d-1", 1, "pending"), map[string]any{"bad": true}}, "must-not-advance", true); err == nil {
		t.Fatal("invalid page accepted")
	}
	state, err := s.SyncState()
	if err != nil {
		t.Fatal(err)
	}
	if state.Cursor != "" || state.Complete {
		t.Fatalf("partial transaction committed: %+v", state)
	}
	for i := 0; i < 3; i++ {
		if err := s.ImportInboxPage([]map[string]any{testHistoryItem(fmt.Sprintf("d-%d", i), i, "delivered")}, "", false); err != nil {
			t.Fatal(err)
		}
	}
	summary, err := s.Summary(30)
	if err != nil {
		t.Fatal(err)
	}
	if summary.TotalDeliveries != 3 || summary.DistinctThreads != 3 || summary.DistinctSenders != 3 || len(summary.Relationships) != 3 {
		t.Fatalf("summary=%+v", summary)
	}
	if err := s.ImportInboxPageNamed("catchup", nil, "catch-cursor", true); err != nil {
		t.Fatal(err)
	}
	state, err = s.SyncStateNamed("catchup")
	if err != nil || state.Cursor != "catch-cursor" || !state.Complete {
		t.Fatalf("named state=%+v err=%v", state, err)
	}
	if _, err = s.GetDelivery("none"); !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("missing delivery err=%v", err)
	}
}
