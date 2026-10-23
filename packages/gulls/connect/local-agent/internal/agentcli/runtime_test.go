package agentcli

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

type runtimeEventSink struct{ lines chan string }

func newRuntimeEventSink() *runtimeEventSink            { return &runtimeEventSink{lines: make(chan string, 128)} }
func (s *runtimeEventSink) Write(p []byte) (int, error) { s.lines <- string(p); return len(p), nil }

func TestRuntimeProfileIdentityNormalizesConfiguredPath(t *testing.T) {
	dir := t.TempDir()
	a := RuntimeProfile{Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://api.example/", "SEAGULL_AGENT_HANDLE": "@Worker:Gulls.AI", "SEAGULL_AGENT_CONTEXT_DIR": filepath.Join(dir, ".")}}
	b := RuntimeProfile{Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://api.example", "SEAGULL_AGENT_HANDLE": "@worker:gulls.ai", "SEAGULL_AGENT_CONTEXT_DIR": dir}}
	if profileIdentity(a) != profileIdentity(b) {
		t.Fatalf("identity mismatch: %q vs %q", profileIdentity(a), profileIdentity(b))
	}
}

func TestRuntimePausedSnapshotPermissions(t *testing.T) {
	dir := t.TempDir()
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{"items":[]}`)) }))
	defer hub.Close()
	p, err := newRuntimeProfile(context.Background(), RuntimeProfile{ID: "p", Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": hub.URL, "SEAGULL_AGENT_HANDLE": "@worker:gulls.ai", "SEAGULL_AGENT_CONTEXT_DIR": dir}, Monitoring: false}, &runtimeServer{})
	if err != nil {
		t.Fatal(err)
	}
	if err := p.refresh(context.Background(), true); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "inbox-snapshot.json")
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("snapshot mode = %o", info.Mode().Perm())
	}
	dirInfo, err := os.Stat(dir)
	if err != nil {
		t.Fatal(err)
	}
	if dirInfo.Mode().Perm() != 0o700 {
		t.Fatalf("context mode = %o", dirInfo.Mode().Perm())
	}
}

func TestRuntimeStdioConfigureStatusAndEOF(t *testing.T) {
	dir := t.TempDir()
	env := map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://api.example", "SEAGULL_AGENT_HANDLE": "@worker:gulls.ai", "SEAGULL_AGENT_CONTEXT_DIR": dir}
	profile := RuntimeProfile{ID: "p1", Environment: env, Monitoring: false, Revision: "r1"}
	configure, _ := json.Marshal(RuntimeRequest{Version: 1, ID: "c", Operation: "configure", Profiles: []RuntimeProfile{profile}})
	status, _ := json.Marshal(RuntimeRequest{Version: 1, ID: "s", Operation: "status"})
	var in bytes.Buffer
	in.Write(configure)
	in.WriteByte('\n')
	in.Write(status)
	in.WriteByte('\n')
	var out bytes.Buffer
	if err := RuntimeServe(context.Background(), "", true, &in, &out, &out); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("responses = %q", out.String())
	}
	if !strings.Contains(out.String(), `"id":"s"`) || !strings.Contains(out.String(), `p1`) {
		t.Fatalf("status response missing: %s", out.String())
	}
}

func TestSameRuntimeProfileDetectsMonitoringChanges(t *testing.T) {
	a := RuntimeProfile{ID: "p", Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://a", "SEAGULL_AGENT_HANDLE": "@a"}, Monitoring: true, PollInterval: 1}
	b := a
	b.Monitoring = false
	if sameRuntimeProfile(a, b) {
		t.Fatal("monitoring change was not detected")
	}
}

func TestRuntimeConfigureReplacesAndRemovesProfiles(t *testing.T) {
	server := &runtimeServer{ctx: context.Background(), profiles: map[string]*runtimeProfile{}}
	dir := t.TempDir()
	base := func(id string) RuntimeProfile {
		return RuntimeProfile{ID: id, Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://api.example", "SEAGULL_AGENT_HANDLE": "@" + id, "SEAGULL_AGENT_CONTEXT_DIR": filepath.Join(dir, id)}, Monitoring: false, Revision: "r1"}
	}
	server.configure([]RuntimeProfile{base("one"), base("two")})
	if len(server.profiles) != 2 {
		t.Fatalf("profiles = %d, want 2", len(server.profiles))
	}
	server.configure([]RuntimeProfile{base("one")})
	if len(server.profiles) != 1 {
		t.Fatalf("profiles after removal = %d, want 1", len(server.profiles))
	}
	if _, ok := server.profiles["two"]; ok {
		t.Fatal("removed profile remained configured")
	}
}

func TestRuntimeCommandReadsSharedCache(t *testing.T) {
	p := &runtimeProfile{profile: RuntimeProfile{Monitoring: true}, inbox: map[string]any{"items": []any{map[string]any{"id": "one"}, map[string]any{"id": "two"}}}}
	got, err := p.cached(1)
	if err != nil {
		t.Fatal(err)
	}
	if len(got["items"].([]any)) != 1 {
		t.Fatalf("cached item count = %d", len(got["items"].([]any)))
	}
}

func TestRuntimeRestoresIdentityAndRevisionBoundSnapshot(t *testing.T) {
	dir := t.TempDir()
	profile := RuntimeProfile{ID: "p", Revision: "r1", Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://api.example", "SEAGULL_AGENT_HANDLE": "@p", "SEAGULL_AGENT_CONTEXT_DIR": dir}, Monitoring: false}
	if err := os.Chmod(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	snap := runtimeSnapshot{Version: 1, Identity: profileIdentity(profile), Revision: "r1", CheckedAt: time.Now().UTC().Format(time.RFC3339), Inbox: map[string]any{"items": []any{}}, Status: "paused"}
	payload, _ := json.Marshal(snap)
	if err := os.WriteFile(filepath.Join(dir, "inbox-snapshot.json"), payload, 0o600); err != nil {
		t.Fatal(err)
	}
	p, err := newRuntimeProfile(context.Background(), profile, &runtimeServer{})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := p.cached(1); err != nil {
		t.Fatalf("snapshot was not restored: %v", err)
	}
	profile.Revision = "r2"
	p2, err := newRuntimeProfile(context.Background(), profile, &runtimeServer{})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := p2.cached(1); err == nil {
		t.Fatal("snapshot restored across revision change")
	}
}

func TestRuntimeRestoredConnectedSnapshotBecomesPaused(t *testing.T) {
	dir := t.TempDir()
	profile := RuntimeProfile{ID: "p", Revision: "r1", Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://api.example", "SEAGULL_AGENT_HANDLE": "@p", "SEAGULL_AGENT_CONTEXT_DIR": dir}, Monitoring: false}
	snapshot := runtimeSnapshot{Version: 1, Identity: profileIdentity(profile), Revision: "r1", CheckedAt: time.Now().UTC().Format(time.RFC3339), Inbox: map[string]any{"items": []any{}}, Status: "connected", Error: "authorization_required"}
	payload, _ := json.Marshal(snapshot)
	if err := os.WriteFile(filepath.Join(dir, "inbox-snapshot.json"), payload, 0o600); err != nil {
		t.Fatal(err)
	}
	p, err := newRuntimeProfile(context.Background(), profile, &runtimeServer{})
	if err != nil {
		t.Fatal(err)
	}
	if p.status != "paused" || p.errText != "" {
		t.Fatalf("restored state = status %q error %q", p.status, p.errText)
	}
}

func TestRuntimeConfigureReportsInvalidProfileWhileKeepingValid(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var events bytes.Buffer
	s := &runtimeServer{ctx: ctx, cancel: cancel, profiles: map[string]*runtimeProfile{}, eventOut: &events}
	valid := RuntimeProfile{ID: "valid", Revision: "r", Monitoring: false, Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://api.example", "SEAGULL_AGENT_HANDLE": "@valid", "SEAGULL_AGENT_CONTEXT_DIR": t.TempDir()}}
	valid.Environment["SEAGULL_AGENT_ENV_FILE"] = filepath.Join(t.TempDir(), "missing-env")
	invalid := RuntimeProfile{ID: "invalid", Revision: "r", Monitoring: false, Environment: map[string]string{"SEAGULL_AGENT_HANDLE": "@invalid", "SEAGULL_AGENT_CONTEXT_DIR": t.TempDir(), "SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env")}}
	var out bytes.Buffer
	s.handle(RuntimeRequest{Version: 1, ID: "configure", Operation: "configure", Profiles: []RuntimeProfile{valid, invalid}}, &out)
	var response RuntimeResponse
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &response); err != nil {
		t.Fatal(err)
	}
	if response.ExitCode != 2 || !strings.Contains(response.Stderr, "invalid") {
		t.Fatalf("invalid profile was acknowledged: %#v", response)
	}
	if !strings.Contains(events.String(), `"profile_id":"invalid"`) || !strings.Contains(events.String(), `"status":"unavailable"`) {
		t.Fatalf("missing unavailable event: %s", events.String())
	}
	if _, ok := s.profiles["valid"]; !ok {
		t.Fatal("valid profile was discarded with invalid profile")
	}
	s.close()
}

func TestRuntimeProfilesPollIndependently(t *testing.T) {
	slowStarted, releaseSlow := make(chan struct{}), make(chan struct{})
	var releaseOnce sync.Once
	first := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(slowStarted)
		<-releaseSlow
		_, _ = w.Write([]byte(`{"items":[]}`))
	}))
	defer first.Close()
	defer releaseOnce.Do(func() { close(releaseSlow) })
	second := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{"items":[]}`)) }))
	defer second.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	events := newRuntimeEventSink()
	s := &runtimeServer{ctx: ctx, cancel: cancel, profiles: map[string]*runtimeProfile{}, eventOut: events}
	makeProfile := func(id, api string) RuntimeProfile {
		return RuntimeProfile{ID: id, Revision: id + "-r", PollInterval: 60, Monitoring: true, Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": api, "SEAGULL_AGENT_HANDLE": "@" + id, "SEAGULL_AGENT_CONTEXT_DIR": filepath.Join(t.TempDir(), id)}}
	}
	s.configure([]RuntimeProfile{makeProfile("slow", first.URL), makeProfile("fast", second.URL)})
	select {
	case <-slowStarted:
	case <-time.After(time.Second):
		t.Fatal("slow profile did not start")
	}
	fastConnected := false
	deadline := time.After(time.Second)
	for !fastConnected {
		select {
		case line := <-events.lines:
			if strings.Contains(line, `"profile_id":"slow"`) && strings.Contains(line, `"status":"connected"`) {
				t.Fatalf("slow profile connected before release: %s", line)
			}
			if strings.Contains(line, `"profile_id":"fast"`) && strings.Contains(line, `"status":"connected"`) {
				fastConnected = true
			}
		case <-deadline:
			t.Fatal("fast profile did not report while slow was blocked")
		}
	}
	releaseOnce.Do(func() { close(releaseSlow) })
	cancel()
	s.close()
}

func TestCommandMutationDetectionRequiresApproval(t *testing.T) {
	if !commandMutates([]string{"--json", "draft-reply", "--approve", "d1"}) {
		t.Fatal("approved draft was not treated as mutation")
	}
	if commandMutates([]string{"--json", "draft-reply", "d1"}) {
		t.Fatal("unapproved draft was treated as mutation")
	}
	if commandMutates([]string{"--json", "inbox", "postcard"}) {
		t.Fatal("content was mistaken for command")
	}
}

func TestRuntimeAckRefreshesSharedCache(t *testing.T) {
	acked := false
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			if acked {
				_, _ = w.Write([]byte(`{"items":[]}`))
			} else {
				_, _ = w.Write([]byte(`{"items":[{"delivery":{"delivery_id":"d1","message_id":"m1"},"message":{"message_id":"m1"}}]}`))
			}
			return
		}
		acked = true
		_, _ = w.Write([]byte(`{}`))
	}))
	defer hub.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	s := &runtimeServer{ctx: ctx, cancel: cancel, profiles: map[string]*runtimeProfile{}, eventOut: io.Discard}
	dir := t.TempDir()
	p, err := newRuntimeProfile(ctx, RuntimeProfile{ID: "p", Revision: "r", Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": hub.URL, "SEAGULL_AGENT_HANDLE": "@p", "SEAGULL_AGENT_CONTEXT_DIR": dir}, Monitoring: false}, s)
	if err != nil {
		t.Fatal(err)
	}
	p.inbox = map[string]any{"items": []any{map[string]any{"delivery": map[string]any{"delivery_id": "d1", "message_id": "m1"}, "message": map[string]any{"message_id": "m1"}}}}
	s.profiles["p"] = p
	var out bytes.Buffer
	s.handle(RuntimeRequest{Version: 1, ID: "ack", Operation: "command", ProfileID: "p", Revision: "r", Arguments: []string{"--json", "ack", "d1"}}, &out)
	if !acked {
		t.Fatal("ack endpoint was not called")
	}
	p.mu.RLock()
	defer p.mu.RUnlock()
	if items, _ := p.inbox["items"].([]any); len(items) != 0 {
		t.Fatalf("cache was not refreshed: %#v", p.inbox)
	}
}

func TestRuntimeContextInboxRequiresFreshAuthorization(t *testing.T) {
	heartbeat := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"error":"revoked"}`, http.StatusUnauthorized)
	}))
	defer heartbeat.Close()
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { t.Fatalf("inbox request bypassed heartbeat") }))
	defer api.Close()
	ctx := context.Background()
	s := &runtimeServer{ctx: ctx, profiles: map[string]*runtimeProfile{}}
	dir := t.TempDir()
	p, err := newRuntimeProfile(ctx, RuntimeProfile{ID: "p", Revision: "r", Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": api.URL, "SEAGULL_SOCIAL_API_URL": heartbeat.URL, "SEAGULL_NODE_ID": "node", "SEAGULL_CONNECTOR_TOKEN": "sga_token", "SEAGULL_AGENT_HANDLE": "@p", "SEAGULL_AGENT_CONTEXT_DIR": dir}, Monitoring: false}, s)
	if err != nil {
		t.Fatal(err)
	}
	p.inbox = map[string]any{"items": []any{map[string]any{"local_runtime": map[string]any{"instructions": "stale"}}}}
	client := p.commandClient()
	if _, err := client.(contextInboxClient).GetInboxForContext("@p", 20); err == nil {
		t.Fatal("revoked heartbeat was bypassed by cached inbox")
	}
}

func TestRuntimeWatcherUsesCacheAndAuthorizesNewHandoffs(t *testing.T) {
	p, err := newRuntimeProfile(context.Background(), RuntimeProfile{ID: "p", Revision: "r", Environment: map[string]string{
		"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://hub.example", "SEAGULL_SOCIAL_API_URL": "https://social.example",
		"SEAGULL_NODE_ID": "node", "SEAGULL_CONNECTOR_TOKEN": "sga_token",
		"SEAGULL_AGENT_HANDLE": "@p", "SEAGULL_AGENT_CONTEXT_DIR": t.TempDir(),
	}, Monitoring: false}, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer p.cancel()
	paths := []string{}
	revoked := true
	p.client.Client = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		paths = append(paths, r.URL.Path)
		status := http.StatusOK
		body := `{"items":[{"delivery":{"delivery_id":"new"},"message":{"content_inline":"hello"}}]}`
		if r.URL.Path == "/local-connections/heartbeat" {
			body = `{"local_runtime":{"instructions":"Fresh owner instructions"}}`
			if revoked {
				status, body = http.StatusUnauthorized, `{"error":"revoked"}`
			}
		}
		return &http.Response{StatusCode: status, Header: http.Header{}, Body: io.NopCloser(strings.NewReader(body))}, nil
	})}
	cache := func(id string) {
		p.inbox = map[string]any{"items": []any{map[string]any{
			"delivery":      map[string]any{"delivery_id": id},
			"local_runtime": map[string]any{"instructions": "Stale owner instructions"},
		}}}
	}
	seen := SeenDeliveryStore{Path: filepath.Join(p.config.ContextDir, "seen-deliveries.json")}
	if err := seen.Save(map[string]bool{"known": true}); err != nil {
		t.Fatal(err)
	}
	cache("known")
	client := p.commandClient()
	result, err := PollOnce(client, p.config, 20, false, nil)
	if err != nil || len(result.ContextPaths) != 0 || len(paths) != 0 {
		t.Fatalf("known delivery triggered remote work: result=%#v paths=%v err=%v", result, paths, err)
	}
	cache("new")
	if _, err := PollOnce(client, p.config, 20, false, nil); err == nil {
		t.Fatal("revoked authorization allowed a new handoff")
	}
	for _, filename := range []string{"new.md", "latest.md"} {
		if _, err := os.Stat(filepath.Join(p.config.ContextDir, filename)); !os.IsNotExist(err) {
			t.Fatalf("unauthorized handoff file %s: %v", filename, err)
		}
	}
	if seen.Load()["new"] || strings.Join(paths, ",") != "/local-connections/heartbeat" {
		t.Fatalf("revoked delivery was marked seen or read remotely: paths=%v", paths)
	}
	revoked = false
	result, err = PollOnce(client, p.config, 20, false, nil)
	if err != nil || len(result.ContextPaths) != 1 {
		t.Fatalf("authorized handoff failed: result=%#v err=%v", result, err)
	}
	content, err := os.ReadFile(result.ContextPaths[0])
	if err != nil || !strings.Contains(string(content), "Fresh owner instructions") || strings.Contains(string(content), "Stale owner instructions") {
		t.Fatalf("handoff did not use fresh owner instructions: %q err=%v", content, err)
	}
	result, err = PollOnce(client, p.config, 20, false, nil)
	if err != nil || len(result.ContextPaths) != 0 || strings.Join(paths, ",") != "/local-connections/heartbeat,/local-connections/heartbeat,/agent/inbox" {
		t.Fatalf("seen handoff polled again: result=%#v paths=%v err=%v", result, paths, err)
	}
}

func TestRuntimeRejectsStaleRevisionCommand(t *testing.T) {
	ctx := context.Background()
	s := &runtimeServer{ctx: ctx, profiles: map[string]*runtimeProfile{}}
	p, err := newRuntimeProfile(ctx, RuntimeProfile{ID: "p", Revision: "new", Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://api.example", "SEAGULL_AGENT_HANDLE": "@p", "SEAGULL_AGENT_CONTEXT_DIR": t.TempDir()}, Monitoring: false}, s)
	if err != nil {
		t.Fatal(err)
	}
	s.profiles["p"] = p
	var out bytes.Buffer
	s.handle(RuntimeRequest{Version: 1, ID: "old", Operation: "command", ProfileID: "p", Revision: "old", Arguments: []string{"--json", "inbox"}}, &out)
	var response RuntimeResponse
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &response); err != nil {
		t.Fatal(err)
	}
	if response.ExitCode == 0 || !strings.Contains(response.Stderr, "not configured") {
		t.Fatalf("stale command was accepted: %#v", response)
	}
}

func TestRuntimeUnixSocketAndDuplicateInstance(t *testing.T) {
	dir := filepath.Join("/tmp", "sgr-"+strconv.Itoa(os.Getpid()))
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	socket := filepath.Join(dir, "runtime.sock")
	_ = os.Remove(socket)
	t.Cleanup(func() { _ = os.Remove(socket); _ = os.Remove(dir) })
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stdinReader, stdinWriter := io.Pipe()
	defer stdinWriter.Close()
	var stdout bytes.Buffer
	done := make(chan error, 1)
	go func() { done <- RuntimeServe(ctx, socket, true, stdinReader, &stdout, &stdout) }()
	deadline := time.Now().Add(2 * time.Second)
	for !RuntimeSocketAvailable(socket) && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if !RuntimeSocketAvailable(socket) {
		select {
		case err := <-done:
			t.Fatalf("runtime socket did not appear: %v", err)
		default:
		}
		t.Fatal("runtime socket did not appear")
	}
	secondCtx, secondCancel := context.WithCancel(context.Background())
	defer secondCancel()
	if err := RuntimeServe(secondCtx, socket, false, nil, io.Discard, io.Discard); err == nil {
		t.Fatal("duplicate runtime instance was accepted")
	}
	conn, err := net.Dial("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	profile := RuntimeProfile{ID: "p", Environment: map[string]string{"SEAGULL_AGENT_ENV_FILE": filepath.Join(t.TempDir(), "missing-env"), "SEAGULL_API_URL": "https://api.example", "SEAGULL_AGENT_HANDLE": "@p", "SEAGULL_AGENT_CONTEXT_DIR": t.TempDir()}, Monitoring: false, Revision: "r"}
	request, _ := json.Marshal(RuntimeRequest{Version: 1, ID: "c", Operation: "configure", Profiles: []RuntimeProfile{profile}})
	_, _ = conn.Write(append(request, '\n'))
	scanner := bufio.NewScanner(conn)
	if !scanner.Scan() {
		t.Fatal("missing configure response")
	}
	request, _ = json.Marshal(RuntimeRequest{Version: 1, ID: "s", Operation: "status"})
	_, _ = conn.Write(append(request, '\n'))
	if !scanner.Scan() {
		t.Fatal("missing status response")
	}
	var statusResp RuntimeResponse
	if err := json.Unmarshal(scanner.Bytes(), &statusResp); err != nil || !strings.Contains(statusResp.Stdout, `"id":"p"`) {
		t.Fatalf("missing status response: %s", scanner.Text())
	}
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("runtime did not stop")
	}
	if RuntimeSocketAvailable(socket) {
		t.Fatal("runtime socket was not cleaned up")
	}
}
