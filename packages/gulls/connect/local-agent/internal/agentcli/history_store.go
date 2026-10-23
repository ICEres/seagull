package agentcli

// HistoryStore is the local, per-profile message history. It deliberately
// stores only server payloads and derived search fields; credentials and local
// runtime instructions never enter this database.

import (
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	_ "modernc.org/sqlite"
)

const historySchemaVersion = 1

type HistoryQuery struct {
	Limit    int
	Cursor   string
	Query    string
	Status   string
	ThreadID string
}

type HistoryPage struct {
	Items      []map[string]any `json:"items"`
	NextCursor string           `json:"next_cursor,omitempty"`
	Total      int              `json:"total"`
}

type HistorySyncState struct {
	Cursor    string `json:"cursor,omitempty"`
	Complete  bool   `json:"complete"`
	UpdatedAt string `json:"updated_at"`
}

type HistoryThread struct {
	Payload map[string]any
	Cursor  string
}

type HistoryDailyCount struct {
	Day   string `json:"day"`
	Count int    `json:"count"`
}

type HistoryRelationshipCount struct {
	Sender string `json:"sender"`
	Count  int    `json:"count"`
}

type HistorySummary struct {
	TotalDeliveries   int                        `json:"total_deliveries"`
	PendingDeliveries int                        `json:"pending_deliveries"`
	DistinctThreads   int                        `json:"distinct_threads"`
	DistinctSenders   int                        `json:"distinct_senders"`
	DailyReceived     []HistoryDailyCount        `json:"daily_received"`
	Relationships     []HistoryRelationshipCount `json:"relationships"`
}

type historyCursor struct {
	Version   int    `json:"v"`
	Scope     string `json:"s"`
	Query     string `json:"q,omitempty"`
	Status    string `json:"st,omitempty"`
	ThreadID  string `json:"t,omitempty"`
	SortNanos int64  `json:"n"`
	MessageID string `json:"m"`
	Delivery  string `json:"d"`
}

type threadCursor struct {
	Version   int    `json:"v"`
	Scope     string `json:"s"`
	ThreadID  string `json:"t"`
	SortNanos int64  `json:"n"`
	MessageID string `json:"m"`
}

type HistoryStore struct {
	db    *sql.DB
	scope string
	path  string
	owner bool
}

// OpenHistoryStore opens or creates a private SQLite database at path. scope
// must be a stable, non-secret identity chosen by the caller (typically a
// hash of server/account/profile identity).
func OpenHistoryStore(path, scope string) (*HistoryStore, error) {
	if strings.TrimSpace(path) == "" {
		return nil, errors.New("history database path is required")
	}
	if strings.TrimSpace(scope) == "" || strings.ContainsRune(scope, '\x00') {
		return nil, errors.New("history scope is required")
	}
	path, err := filepath.Abs(path)
	if err != nil {
		return nil, fmt.Errorf("history database path: %w", err)
	}
	if err := ensurePrivateHistoryDir(filepath.Dir(path)); err != nil {
		return nil, err
	}
	if err := ensureHistoryFile(path); err != nil {
		return nil, err
	}
	// PathEscape keeps spaces and query characters out of the SQLite URI while
	// preserving an absolute path for the driver.
	dsn := "file:" + url.PathEscape(path) + "?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=foreign_keys(1)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open history database: %w", err)
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	store := &HistoryStore{db: db, scope: scope, path: path, owner: true}
	if err := store.initialize(); err != nil {
		_ = db.Close()
		return nil, err
	}
	_ = os.Chmod(path, 0o600)
	return store, nil
}

func ensureHistoryFile(path string) error {
	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|syscall.O_NOFOLLOW, 0o600)
	if err != nil {
		return fmt.Errorf("open history database file: %w", err)
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
		return errors.New("history database file must be private and regular")
	}
	if st, ok := info.Sys().(*syscall.Stat_t); ok && int(st.Uid) != os.Getuid() {
		return errors.New("history database file is not owned by current user")
	}
	return f.Chmod(0o600)
}

func ensurePrivateHistoryDir(dir string) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("create history database directory: %w", err)
	}
	if err := os.Chmod(dir, 0o700); err != nil {
		return err
	}
	info, err := os.Stat(dir)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode().Perm()&0o077 != 0 {
		return errors.New("history database directory must be private")
	}
	return nil
}

func (s *HistoryStore) initialize() error {
	const schema = `
CREATE TABLE IF NOT EXISTS messages (
  scope TEXT NOT NULL,
  message_id TEXT NOT NULL,
  thread_id TEXT NOT NULL DEFAULT '',
  sender_agent_id TEXT NOT NULL DEFAULT '',
  sender_handle TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  raw_json BLOB NOT NULL,
  sort_nanos INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (scope, message_id)
);
CREATE TABLE IF NOT EXISTS deliveries (
  scope TEXT NOT NULL,
  delivery_id TEXT NOT NULL,
  message_id TEXT NOT NULL DEFAULT '',
  thread_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  item_json BLOB NOT NULL,
  raw_json BLOB NOT NULL,
  current_json BLOB,
  sort_nanos INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (scope, delivery_id)
);
CREATE INDEX IF NOT EXISTS deliveries_order ON deliveries(scope, sort_nanos DESC, delivery_id DESC);
CREATE INDEX IF NOT EXISTS deliveries_status ON deliveries(scope, status, sort_nanos DESC, delivery_id DESC);
CREATE INDEX IF NOT EXISTS deliveries_thread ON deliveries(scope, thread_id, sort_nanos DESC, delivery_id DESC);
CREATE TABLE IF NOT EXISTS threads (
  scope TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  raw_json BLOB NOT NULL,
  cursor TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (scope, thread_id)
);
CREATE TABLE IF NOT EXISTS sync_state (
  scope TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT 'backfill',
  cursor TEXT NOT NULL DEFAULT '',
  complete INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (scope, name)
);
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
  scope UNINDEXED, message_id UNINDEXED, thread_id UNINDEXED, body
);`
	if _, err := s.db.Exec(schema); err != nil {
		return fmt.Errorf("initialize history database: %w", err)
	}
	if err := s.ensureMessageSenderHandleColumn(); err != nil {
		return err
	}
	if _, err := s.db.Exec(fmt.Sprintf("PRAGMA user_version = %d", historySchemaVersion)); err != nil {
		return fmt.Errorf("set history schema version: %w", err)
	}
	_, err := s.db.Exec(`INSERT INTO sync_state(scope, name, cursor, complete, updated_at)
VALUES (?, 'backfill', '', 0, ?) ON CONFLICT(scope,name) DO NOTHING`, s.scope, time.Now().UTC().Format(time.RFC3339Nano))
	return err
}

func (s *HistoryStore) ensureMessageSenderHandleColumn() error {
	rows, err := s.db.Query(`PRAGMA table_info(messages)`)
	if err != nil {
		return err
	}
	hasColumn := false
	for rows.Next() {
		var cid int
		var name, typ string
		var notNull, primary int
		var defaultValue any
		if err := rows.Scan(&cid, &name, &typ, &notNull, &defaultValue, &primary); err != nil {
			_ = rows.Close()
			return err
		}
		if name == "sender_handle" {
			hasColumn = true
		}
	}
	if err := rows.Close(); err != nil {
		return err
	}
	if hasColumn {
		return nil
	}
	_, err = s.db.Exec(`ALTER TABLE messages ADD COLUMN sender_handle TEXT NOT NULL DEFAULT ''`)
	return err
}

func (s *HistoryStore) Close() error {
	if s == nil || s.db == nil || !s.owner {
		return nil
	}
	return s.db.Close()
}

// ForScope creates a lightweight view over the same database connection. The
// parent runtime owns the connection and must close the original store only.
func (s *HistoryStore) ForScope(scope string) (*HistoryStore, error) {
	if s == nil || s.db == nil {
		return nil, errors.New("history store is closed")
	}
	if strings.TrimSpace(scope) == "" || strings.ContainsRune(scope, '\x00') {
		return nil, errors.New("history scope is required")
	}
	view := &HistoryStore{db: s.db, scope: scope, path: s.path}
	_, err := s.db.Exec(`INSERT INTO sync_state(scope,name,cursor,complete,updated_at) VALUES(?, 'backfill', '', 0, ?) ON CONFLICT(scope,name) DO NOTHING`, scope, time.Now().UTC().Format(time.RFC3339Nano))
	if err != nil {
		return nil, err
	}
	return view, nil
}

func (s *HistoryStore) Path() string  { return s.path }
func (s *HistoryStore) Scope() string { return s.scope }

// ImportInboxPage atomically upserts a server page and advances its cursor.
// Replaying a page is safe: delivery_id and message_id are stable keys.
func (s *HistoryStore) ImportInboxPage(items []map[string]any, nextCursor string, complete bool) error {
	return s.ImportInboxPageNamed("backfill", items, nextCursor, complete)
}

// ImportInboxPageNamed is the same atomic import for a named sync stream. A
// runtime can use independent "backfill" and "catchup" cursors.
func (s *HistoryStore) ImportInboxPageNamed(name string, items []map[string]any, nextCursor string, complete bool) error {
	if strings.TrimSpace(name) == "" {
		return errors.New("history sync name is required")
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	rollback := func(e error) error { _ = tx.Rollback(); return e }
	now := time.Now().UTC().Format(time.RFC3339Nano)
	for _, item := range items {
		if err := s.upsertItem(tx, item, now); err != nil {
			return rollback(err)
		}
	}
	if _, err := tx.Exec(`INSERT INTO sync_state(scope,name,cursor,complete,updated_at) VALUES(?,?,?,?,?)
ON CONFLICT(scope,name) DO UPDATE SET cursor=excluded.cursor, complete=excluded.complete, updated_at=excluded.updated_at`,
		s.scope, name, nextCursor, boolInt(complete), now); err != nil {
		return rollback(err)
	}
	if err := tx.Commit(); err != nil {
		return err
	}
	return nil
}

func (s *HistoryStore) upsertItem(tx *sql.Tx, item map[string]any, now string) error {
	delivery := objectValue(item, "delivery")
	message := objectValue(item, "message")
	current := objectValue(item, "current_message")
	deliveryID := firstClean(stringValue(delivery, "delivery_id"), stringValue(item, "delivery_id"))
	if deliveryID == "" {
		return errors.New("history item delivery_id is required")
	}
	messageID := firstClean(stringValue(delivery, "message_id"), stringValue(message, "message_id"), stringValue(item, "message_id"))
	threadID := firstClean(stringValue(delivery, "thread_id"), stringValue(message, "thread_id"), stringValue(item, "thread_id"))
	status := stringValue(delivery, "status")
	// Inbox responses may be enriched with private authenticated runtime
	// instructions. Persist only message/delivery fields, never that envelope.
	persisted := map[string]any{"delivery": delivery}
	if message != nil {
		persisted["message"] = message
	}
	if current != nil {
		persisted["current_message"] = current
	}
	itemJSON, err := json.Marshal(persisted)
	if err != nil {
		return err
	}
	deliveryJSON, err := json.Marshal(delivery)
	if err != nil {
		return err
	}
	messageJSON, err := json.Marshal(message)
	if err != nil {
		return err
	}
	var currentJSON []byte
	if current != nil {
		currentJSON, err = json.Marshal(current)
		if err != nil {
			return err
		}
	}
	sortNanos := payloadTime(message, delivery, item)
	if messageID != "" {
		body := firstClean(stringValue(current, "content_inline"), stringValue(message, "content_inline"), stringValue(message, "content"))
		senderID := stringValue(message, "sender_agent_id")
		senderHandle := stringValue(message, "sender_handle")
		if _, err = tx.Exec(`INSERT INTO messages(scope,message_id,thread_id,sender_agent_id,sender_handle,body,raw_json,sort_nanos,updated_at)
VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(scope,message_id) DO UPDATE SET thread_id=excluded.thread_id,
sender_agent_id=excluded.sender_agent_id,sender_handle=excluded.sender_handle,body=excluded.body,raw_json=excluded.raw_json,
sort_nanos=excluded.sort_nanos,updated_at=excluded.updated_at`, s.scope, messageID, threadID, senderID, senderHandle, body, messageJSON, sortNanos, now); err != nil {
			return err
		}
		if _, err = tx.Exec(`DELETE FROM message_fts WHERE scope=? AND message_id=?`, s.scope, messageID); err != nil {
			return err
		}
		if _, err = tx.Exec(`INSERT INTO message_fts(scope,message_id,thread_id,body) VALUES(?,?,?,?)`, s.scope, messageID, threadID, strings.TrimSpace(senderID+" "+senderHandle+" "+body)); err != nil {
			return err
		}
	}
	_, err = tx.Exec(`INSERT INTO deliveries(scope,delivery_id,message_id,thread_id,status,item_json,raw_json,current_json,sort_nanos,updated_at)
VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(scope,delivery_id) DO UPDATE SET message_id=excluded.message_id,
thread_id=excluded.thread_id,status=excluded.status,item_json=excluded.item_json,raw_json=excluded.raw_json,
current_json=excluded.current_json,sort_nanos=excluded.sort_nanos,updated_at=excluded.updated_at`,
		s.scope, deliveryID, messageID, threadID, status, itemJSON, deliveryJSON, currentJSON, sortNanos, now)
	return err
}

func (s *HistoryStore) Query(q HistoryQuery) (HistoryPage, error) {
	if q.Limit <= 0 {
		q.Limit = 50
	}
	if q.Limit > 500 {
		q.Limit = 500
	}
	cur, err := decodeHistoryCursor(q.Cursor, s.scope, q)
	if err != nil {
		return HistoryPage{}, err
	}
	where, args := s.queryWhere(q, nil)
	var total int
	if err := s.db.QueryRow("SELECT COUNT(*) FROM deliveries d LEFT JOIN messages m ON m.scope=d.scope AND m.message_id=d.message_id"+where, args...).Scan(&total); err != nil {
		return HistoryPage{}, err
	}
	where, args = s.queryWhere(q, cur)
	rows, err := s.db.Query(`SELECT d.item_json,d.raw_json,d.current_json,m.raw_json,d.sort_nanos,d.message_id,d.delivery_id
FROM deliveries d LEFT JOIN messages m ON m.scope=d.scope AND m.message_id=d.message_id`+where+` ORDER BY d.sort_nanos DESC,d.delivery_id DESC LIMIT ?`, append(args, q.Limit+1)...)
	if err != nil {
		return HistoryPage{}, err
	}
	defer rows.Close()
	page := HistoryPage{Items: make([]map[string]any, 0, q.Limit), Total: total}
	var lastSort int64
	var lastMessageID, lastDeliveryID string
	for rows.Next() {
		var itemJSON, deliveryJSON, currentJSON, messageJSON []byte
		var sortNanos int64
		var messageID, deliveryID string
		if err := rows.Scan(&itemJSON, &deliveryJSON, &currentJSON, &messageJSON, &sortNanos, &messageID, &deliveryID); err != nil {
			return HistoryPage{}, err
		}
		var item map[string]any
		if json.Unmarshal(itemJSON, &item) != nil {
			item = map[string]any{}
		}
		var delivery, message, current map[string]any
		_ = json.Unmarshal(deliveryJSON, &delivery)
		_ = json.Unmarshal(messageJSON, &message)
		if len(currentJSON) > 0 {
			_ = json.Unmarshal(currentJSON, &current)
		}
		if delivery != nil {
			item["delivery"] = delivery
		}
		if message != nil {
			item["message"] = message
		}
		if current != nil {
			item["current_message"] = current
		}
		if len(page.Items) < q.Limit {
			page.Items = append(page.Items, item)
			lastSort, lastMessageID, lastDeliveryID = sortNanos, messageID, deliveryID
		} else if page.NextCursor == "" {
			page.NextCursor = encodeHistoryCursor(historyCursor{1, s.scope, q.Query, q.Status, q.ThreadID, lastSort, lastMessageID, lastDeliveryID})
		}
	}
	if err := rows.Err(); err != nil {
		return HistoryPage{}, err
	}
	return page, nil
}

func (s *HistoryStore) queryWhere(q HistoryQuery, cur *historyCursor) (string, []any) {
	parts := []string{"d.scope = ?"}
	args := []any{s.scope}
	if q.Status != "" {
		parts = append(parts, "d.status = ?")
		args = append(args, q.Status)
	}
	if q.ThreadID != "" {
		parts = append(parts, "d.thread_id = ?")
		args = append(args, q.ThreadID)
	}
	if strings.TrimSpace(q.Query) != "" {
		like := historyLikePattern(q.Query)
		parts = append(parts, "(d.message_id IN (SELECT message_id FROM message_fts WHERE scope=? AND message_fts MATCH ?) OR m.body LIKE ? ESCAPE '\\' OR m.sender_agent_id LIKE ? ESCAPE '\\' OR m.sender_handle LIKE ? ESCAPE '\\')")
		args = append(args, s.scope, safeFTSQuery(q.Query), like, like, like)
	}
	if cur != nil {
		parts = append(parts, "(d.sort_nanos < ? OR (d.sort_nanos = ? AND d.delivery_id < ?))")
		args = append(args, cur.SortNanos, cur.SortNanos, cur.Delivery)
	}
	return " WHERE " + strings.Join(parts, " AND "), args
}

func safeFTSQuery(q string) string {
	return `"` + strings.ReplaceAll(strings.TrimSpace(q), `"`, `""`) + `"`
}

func historyLikePattern(q string) string {
	var b strings.Builder
	b.WriteByte('%')
	for _, r := range q {
		if r == '\\' || r == '%' || r == '_' {
			b.WriteByte('\\')
		}
		b.WriteRune(r)
	}
	b.WriteByte('%')
	return b.String()
}

func (s *HistoryStore) SyncState() (HistorySyncState, error) {
	return s.SyncStateNamed("backfill")
}

func (s *HistoryStore) SyncStateNamed(name string) (HistorySyncState, error) {
	var state HistorySyncState
	var complete int
	err := s.db.QueryRow(`SELECT cursor,complete,updated_at FROM sync_state WHERE scope=? AND name=?`, s.scope, name).Scan(&state.Cursor, &complete, &state.UpdatedAt)
	state.Complete = complete != 0
	return state, err
}

func (s *HistoryStore) SaveThread(threadID string, payload map[string]any, cursor string) error {
	if strings.TrimSpace(threadID) == "" {
		return errors.New("thread id is required")
	}
	persisted := persistedThreadPayload(threadID, payload)
	raw, err := json.Marshal(persisted)
	if err != nil {
		return err
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	_, err = tx.Exec(`INSERT INTO threads(scope,thread_id,raw_json,cursor,updated_at) VALUES(?,?,?,?,?)
ON CONFLICT(scope,thread_id) DO UPDATE SET raw_json=excluded.raw_json,cursor=excluded.cursor,updated_at=excluded.updated_at`, s.scope, threadID, raw, cursor, time.Now().UTC().Format(time.RFC3339Nano))
	if err != nil {
		_ = tx.Rollback()
		return err
	}
	// Thread responses commonly carry messages even when there is no inbox
	// delivery. Cache them in the same transaction for offline thread search.
	for _, key := range []string{"messages", "recent_messages"} {
		if list, ok := payload[key].([]any); ok {
			for _, value := range list {
				message, ok := value.(map[string]any)
				if !ok {
					continue
				}
				message, _ = sanitizeHistoryValue(message).(map[string]any)
				if err := s.upsertMessage(tx, message, threadID, time.Now().UTC().Format(time.RFC3339Nano)); err != nil {
					_ = tx.Rollback()
					return err
				}
			}
		}
	}
	return tx.Commit()
}

func persistedThreadPayload(threadID string, payload map[string]any) map[string]any {
	result := map[string]any{"thread_id": threadID}
	for _, key := range []string{"next_cursor", "has_more", "messages", "recent_messages"} {
		if value, ok := payload[key]; ok {
			result[key] = sanitizeHistoryValue(value)
		}
	}
	return result
}

func sanitizeHistoryValue(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		result := make(map[string]any, len(typed))
		for key, item := range typed {
			switch strings.ToLower(key) {
			case "local_runtime", "private_prompt", "connector_token", "token", "instructions":
				continue
			}
			result[key] = sanitizeHistoryValue(item)
		}
		return result
	case []any:
		result := make([]any, len(typed))
		for index, item := range typed {
			result[index] = sanitizeHistoryValue(item)
		}
		return result
	default:
		return value
	}
}

// GetDelivery returns the last locally persisted delivery in InboxItem shape.
// It returns sql.ErrNoRows when the delivery has not been synchronized.
func (s *HistoryStore) GetDelivery(deliveryID string) (map[string]any, error) {
	var itemJSON, deliveryJSON, currentJSON, messageJSON []byte
	err := s.db.QueryRow(`SELECT d.item_json,d.raw_json,d.current_json,m.raw_json
FROM deliveries d LEFT JOIN messages m ON m.scope=d.scope AND m.message_id=d.message_id
WHERE d.scope=? AND d.delivery_id=?`, s.scope, deliveryID).Scan(&itemJSON, &deliveryJSON, &currentJSON, &messageJSON)
	if err != nil {
		return nil, err
	}
	var item map[string]any
	if err := json.Unmarshal(itemJSON, &item); err != nil {
		item = map[string]any{}
	}
	var delivery, message, current map[string]any
	_ = json.Unmarshal(deliveryJSON, &delivery)
	_ = json.Unmarshal(messageJSON, &message)
	if len(currentJSON) > 0 {
		_ = json.Unmarshal(currentJSON, &current)
	}
	if delivery != nil {
		item["delivery"] = delivery
	}
	if message != nil {
		item["message"] = message
	}
	if current != nil {
		item["current_message"] = current
	}
	return item, nil
}

func (s *HistoryStore) Summary(days int) (HistorySummary, error) {
	if days <= 0 {
		days = 30
	}
	if days > 3660 {
		days = 3660
	}
	out := HistorySummary{
		DailyReceived: []HistoryDailyCount{},
		Relationships: []HistoryRelationshipCount{},
	}
	if err := s.db.QueryRow(`SELECT COUNT(*), COALESCE(SUM(CASE WHEN status IN ('pending','delivered','received','unread') THEN 1 ELSE 0 END), 0), COUNT(DISTINCT NULLIF(thread_id,'')) FROM deliveries WHERE scope=?`, s.scope).Scan(&out.TotalDeliveries, &out.PendingDeliveries, &out.DistinctThreads); err != nil {
		return out, err
	}
	if err := s.db.QueryRow(`SELECT COUNT(DISTINCT COALESCE(NULLIF(m.sender_agent_id,''), NULLIF(m.sender_handle,''))) FROM deliveries d JOIN messages m ON m.scope=d.scope AND m.message_id=d.message_id WHERE d.scope=?`, s.scope).Scan(&out.DistinctSenders); err != nil {
		return out, err
	}
	cutoff := time.Now().UTC().AddDate(0, 0, -days).UnixNano()
	rows, err := s.db.Query(`SELECT strftime('%Y-%m-%d', sort_nanos/1000000000, 'unixepoch'), COUNT(*) FROM deliveries WHERE scope=? AND sort_nanos>=? GROUP BY 1 ORDER BY 1`, s.scope, cutoff)
	if err != nil {
		return out, err
	}
	for rows.Next() {
		var v HistoryDailyCount
		if err := rows.Scan(&v.Day, &v.Count); err != nil {
			_ = rows.Close()
			return out, err
		}
		out.DailyReceived = append(out.DailyReceived, v)
	}
	if err := rows.Close(); err != nil {
		return out, err
	}
	rows, err = s.db.Query(`SELECT COALESCE(NULLIF(m.sender_agent_id,''), NULLIF(m.sender_handle,'')), COUNT(*) FROM deliveries d JOIN messages m ON m.scope=d.scope AND m.message_id=d.message_id WHERE d.scope=? AND (m.sender_agent_id<>'' OR m.sender_handle<>'') GROUP BY 1 ORDER BY COUNT(*) DESC,1`, s.scope)
	if err != nil {
		return out, err
	}
	for rows.Next() {
		var v HistoryRelationshipCount
		if err := rows.Scan(&v.Sender, &v.Count); err != nil {
			_ = rows.Close()
			return out, err
		}
		out.Relationships = append(out.Relationships, v)
	}
	return out, rows.Close()
}

func (s *HistoryStore) upsertMessage(tx *sql.Tx, message map[string]any, threadID, now string) error {
	id := firstClean(stringValue(message, "message_id"), stringValue(message, "id"))
	if id == "" {
		return nil
	}
	raw, err := json.Marshal(message)
	if err != nil {
		return err
	}
	body := firstClean(stringValue(message, "content_inline"), stringValue(message, "content"))
	senderID := stringValue(message, "sender_agent_id")
	senderHandle := stringValue(message, "sender_handle")
	if threadID == "" {
		threadID = stringValue(message, "thread_id")
	}
	tm := payloadTime(message, nil, nil)
	if _, err = tx.Exec(`INSERT INTO messages(scope,message_id,thread_id,sender_agent_id,sender_handle,body,raw_json,sort_nanos,updated_at) VALUES(?,?,?,?,?,?,?,?,?)
ON CONFLICT(scope,message_id) DO UPDATE SET thread_id=excluded.thread_id,sender_agent_id=excluded.sender_agent_id,sender_handle=excluded.sender_handle,body=excluded.body,raw_json=excluded.raw_json,sort_nanos=excluded.sort_nanos,updated_at=excluded.updated_at`, s.scope, id, threadID, senderID, senderHandle, body, raw, tm, now); err != nil {
		return err
	}
	if _, err = tx.Exec(`DELETE FROM message_fts WHERE scope=? AND message_id=?`, s.scope, id); err != nil {
		return err
	}
	_, err = tx.Exec(`INSERT INTO message_fts(scope,message_id,thread_id,body) VALUES(?,?,?,?)`, s.scope, id, threadID, strings.TrimSpace(senderID+" "+senderHandle+" "+body))
	return err
}

func (s *HistoryStore) Thread(threadID string) (HistoryThread, error) {
	var raw []byte
	var cursor string
	err := s.db.QueryRow(`SELECT raw_json,cursor FROM threads WHERE scope=? AND thread_id=?`, s.scope, threadID).Scan(&raw, &cursor)
	if err != nil {
		return HistoryThread{}, err
	}
	var payload map[string]any
	if err := json.Unmarshal(raw, &payload); err != nil {
		return HistoryThread{}, err
	}
	return HistoryThread{Payload: payload, Cursor: cursor}, nil
}

// QueryThread returns the locally cached portion of a thread. It selects the
// newest messages first and returns an opaque cursor for older pages.
func (s *HistoryStore) QueryThread(threadID string, limit int, cursor string) (map[string]any, error) {
	if strings.TrimSpace(threadID) == "" {
		return nil, errors.New("thread id is required")
	}
	if limit <= 0 {
		limit = 50
	}
	if limit > 500 {
		limit = 500
	}
	var after *threadCursor
	if cursor != "" {
		b, err := base64.RawURLEncoding.DecodeString(cursor)
		if err != nil {
			return nil, errors.New("invalid thread cursor")
		}
		var c threadCursor
		if json.Unmarshal(b, &c) != nil || c.Version != 1 || c.Scope != s.scope || c.ThreadID != threadID {
			return nil, errors.New("thread cursor does not match query")
		}
		after = &c
	}
	where := ` WHERE scope=? AND thread_id=?`
	args := []any{s.scope, threadID}
	if after != nil {
		where += ` AND (sort_nanos < ? OR (sort_nanos = ? AND message_id < ?))`
		args = append(args, after.SortNanos, after.SortNanos, after.MessageID)
	}
	rows, err := s.db.Query(`SELECT raw_json,sort_nanos,message_id FROM messages`+where+` ORDER BY sort_nanos DESC,message_id DESC LIMIT ?`, append(args, limit+1)...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	messages := make([]any, 0, limit)
	var end string
	var next string
	for rows.Next() {
		var raw []byte
		var sort int64
		var id string
		if err := rows.Scan(&raw, &sort, &id); err != nil {
			return nil, err
		}
		var msg map[string]any
		if json.Unmarshal(raw, &msg) != nil {
			continue
		}
		if len(messages) < limit {
			messages = append(messages, msg)
			c := threadCursor{1, s.scope, threadID, sort, id}
			b, _ := json.Marshal(c)
			end = base64.RawURLEncoding.EncodeToString(b)
		} else {
			next = end
			break
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for left, right := 0, len(messages)-1; left < right; left, right = left+1, right-1 {
		messages[left], messages[right] = messages[right], messages[left]
	}
	return map[string]any{"thread_id": threadID, "messages": messages, "next_cursor": next, "end_cursor": end}, nil
}

func encodeHistoryCursor(c historyCursor) string {
	b, _ := json.Marshal(c)
	return base64.RawURLEncoding.EncodeToString(b)
}
func decodeHistoryCursor(raw, scope string, q HistoryQuery) (*historyCursor, error) {
	if strings.TrimSpace(raw) == "" {
		return nil, nil
	}
	b, err := base64.RawURLEncoding.DecodeString(raw)
	if err != nil {
		return nil, errors.New("invalid history cursor")
	}
	var c historyCursor
	if json.Unmarshal(b, &c) != nil || c.Version != 1 || c.Scope != scope || c.Query != q.Query || c.Status != q.Status || c.ThreadID != q.ThreadID {
		return nil, errors.New("history cursor does not match query")
	}
	return &c, nil
}

func payloadTime(m, d, item map[string]any) int64 {
	for _, x := range []map[string]any{m, d, item} {
		for _, k := range []string{"created_at", "updated_at", "sent_at", "delivered_at", "createdAt", "updatedAt"} {
			if v, ok := x[k].(string); ok {
				if t, e := time.Parse(time.RFC3339Nano, v); e == nil {
					return t.UnixNano()
				}
			}
		}
	}
	return time.Now().UnixNano()
}
func boolInt(v bool) int {
	if v {
		return 1
	}
	return 0
}
