package agentcli

// The resident runtime is deliberately small. It owns polling and a durable
// inbox snapshot and SQLite history; command behavior remains in cli.go and local-action
// requests remain files for the Mac app to approve.

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

const runtimeProtocolVersion = 1

type RuntimeProfile struct {
	ID           string            `json:"id"`
	Environment  map[string]string `json:"environment"`
	PollInterval float64           `json:"poll_interval"`
	Monitoring   bool              `json:"monitoring"`
	Revision     string            `json:"revision,omitempty"`
}

type RuntimeRequest struct {
	Version   int              `json:"version"`
	ID        string           `json:"id"`
	Operation string           `json:"operation"`
	Profiles  []RuntimeProfile `json:"profiles,omitempty"`
	ProfileID string           `json:"profile_id,omitempty"`
	Revision  string           `json:"revision,omitempty"`
	Arguments []string         `json:"arguments,omitempty"`
}

type RuntimeResponse struct {
	Version  int    `json:"version"`
	ID       string `json:"id"`
	ExitCode int    `json:"exit_code"`
	Stdout   string `json:"stdout"`
	Stderr   string `json:"stderr"`
}

type RuntimeInboxEvent struct {
	Version   int            `json:"version"`
	Event     string         `json:"event"`
	ProfileID string         `json:"profile_id"`
	Revision  string         `json:"revision,omitempty"`
	Inbox     map[string]any `json:"inbox,omitempty"`
	CheckedAt string         `json:"checked_at,omitempty"`
	Status    string         `json:"status"`
	Error     string         `json:"error,omitempty"`
}

type runtimeSnapshot struct {
	Version   int            `json:"version"`
	Identity  string         `json:"identity"`
	Revision  string         `json:"revision,omitempty"`
	CheckedAt string         `json:"checked_at"`
	Inbox     map[string]any `json:"inbox,omitempty"`
	Status    string         `json:"status"`
	Error     string         `json:"error,omitempty"`
}

type runtimeProfile struct {
	profile           RuntimeProfile
	config            Config
	client            *HTTPClient
	ctx               context.Context
	server            *runtimeServer
	cancel            context.CancelFunc
	mu                sync.RWMutex
	inbox             map[string]any
	status            string
	errText           string
	checked           time.Time
	opMu              sync.Mutex
	opSlots           chan struct{}
	history           *HistoryStore
	historyWake       chan struct{}
	historyGeneration int64
}

func RuntimeSocketPath(env []string) string {
	for _, item := range env {
		if k, v, ok := strings.Cut(item, "="); ok && k == "SEAGULL_RUNTIME_SOCKET" && strings.TrimSpace(v) != "" {
			return expandHome(strings.TrimSpace(v))
		}
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".config", "seagull", "runtime", "runtime.sock")
}

func profileIdentity(p RuntimeProfile) string {
	env := p.Environment
	api := strings.TrimRight(strings.TrimSpace(env["SEAGULL_API_URL"]), "/")
	handle := strings.ToLower(strings.TrimSpace(env["SEAGULL_AGENT_HANDLE"]))
	dir := expandHome(strings.TrimSpace(env["SEAGULL_AGENT_CONTEXT_DIR"]))
	if dir == "" {
		dir = ".seagull/agent"
	}
	if abs, err := filepath.Abs(dir); err == nil {
		dir = filepath.Clean(abs)
	}
	return handle + "\x00" + api + "\x00" + dir
}

func RuntimeProfileID(env []string) (string, error) {
	return runtimeProfileIdentity(env, ConfigOverrides{})
}

func runtimeProfileIdentity(env []string, overrides ConfigOverrides) (string, error) {
	cfg, err := LoadConfig(env, overrides)
	if err != nil {
		return "", err
	}
	m := map[string]string{"SEAGULL_API_URL": cfg.APIURL, "SEAGULL_AGENT_HANDLE": cfg.AgentHandle, "SEAGULL_AGENT_CONTEXT_DIR": cfg.ContextDir}
	return profileIdentity(RuntimeProfile{Environment: m}), nil
}

func RuntimeSocketAvailable(path string) bool {
	if path == "" {
		return false
	}
	info, err := os.Lstat(path)
	return err == nil && info.Mode()&os.ModeSocket != 0 && info.Mode()&os.ModeSymlink == 0
}

func secureRuntimeSocketDir(path string) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() || info.Mode().Perm()&0o077 != 0 {
		return errors.New("runtime socket directory must be a private non-symlink directory")
	}
	return nil
}

func listenRuntimeSocket(path string) (net.Listener, error) {
	lockPath := path + ".lock"
	lock, lockErr := os.OpenFile(lockPath, os.O_RDWR|os.O_CREATE|syscall.O_NOFOLLOW, 0o600)
	if lockErr != nil {
		return nil, lockErr
	}
	if err := syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		_ = lock.Close()
		return nil, errors.New("runtime socket is already in use")
	}
	if info, err := os.Lstat(path); err == nil {
		if info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 {
			_ = syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
			_ = lock.Close()
			return nil, errors.New("runtime socket path is not a socket")
		}
	} else if !os.IsNotExist(err) {
		_ = syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
		_ = lock.Close()
		return nil, err
	}
	ln, err := net.Listen("unix", path)
	if err == nil {
		return &lockedListener{Listener: ln, lock: lock}, nil
	}
	if !strings.Contains(err.Error(), "address already in use") && !errors.Is(err, syscall.EADDRINUSE) {
		_ = syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
		_ = lock.Close()
		return nil, err
	}
	probe, probeErr := net.DialTimeout("unix", path, 150*time.Millisecond)
	if probeErr == nil {
		_ = probe.Close()
		_ = syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
		_ = lock.Close()
		return nil, errors.New("runtime socket is already in use")
	}
	if info, statErr := os.Lstat(path); statErr != nil || info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 {
		_ = syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
		_ = lock.Close()
		return nil, errors.New("runtime socket path is not a stale socket")
	}
	if err := os.Remove(path); err != nil {
		_ = syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
		_ = lock.Close()
		return nil, err
	}
	ln, err = net.Listen("unix", path)
	if err != nil {
		_ = syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
		_ = lock.Close()
		return nil, err
	}
	return &lockedListener{Listener: ln, lock: lock}, nil
}

type lockedListener struct {
	net.Listener
	lock *os.File
	once sync.Once
}

func (l *lockedListener) Close() error {
	var err error
	l.once.Do(func() {
		err = l.Listener.Close()
		_ = syscall.Flock(int(l.lock.Fd()), syscall.LOCK_UN)
		_ = l.lock.Close()
	})
	return err
}

func RuntimeServe(ctx context.Context, socket string, stdio bool, stdin io.Reader, stdout, stderr io.Writer) error {
	return runtimeServeWithProfiles(ctx, socket, stdio, stdin, stdout, stderr, nil)
}

func runtimeServeWithProfiles(ctx context.Context, socket string, stdio bool, stdin io.Reader, stdout, stderr io.Writer, seed []RuntimeProfile) error {
	if ctx == nil {
		ctx = context.Background()
	}
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	s := &runtimeServer{ctx: ctx, cancel: cancel, profiles: map[string]*runtimeProfile{}, eventOut: stdout, historyEnabled: true}
	defer func() {
		s.close()
		s.wg.Wait()
		if s.history != nil {
			_ = s.history.Close()
		}
	}()
	if socket == "" && !stdio {
		return errors.New("runtime serve requires --socket or --stdio")
	}
	var ln net.Listener
	if socket != "" {
		if err := secureRuntimeSocketDir(socket); err != nil {
			return err
		}
		var err error
		ln, err = listenRuntimeSocket(socket)
		if err != nil {
			return fmt.Errorf("runtime socket: %w", err)
		}
		_ = os.Chmod(socket, 0o600)
		defer func() { _ = ln.Close() }()
		s.historyPath = filepath.Join(filepath.Dir(socket), "history.sqlite3")
	}
	if len(seed) > 0 {
		if err := s.configure(seed); err != nil {
			return err
		}
	}
	if ln != nil {
		go func() {
			for {
				conn, err := ln.Accept()
				if err != nil {
					if ctx.Err() != nil || errors.Is(err, net.ErrClosed) {
						return
					}
					continue
				}
				go s.serveConn(conn)
			}
		}()
	}
	if stdio {
		go func() {
			scanner := bufio.NewScanner(stdin)
			scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
			for scanner.Scan() {
				var req RuntimeRequest
				if err := json.Unmarshal(scanner.Bytes(), &req); err != nil {
					s.writeResponse(RuntimeResponse{Version: runtimeProtocolVersion, ExitCode: 2, Stderr: "invalid runtime request"})
					continue
				}
				s.dispatch(req, stdout)
			}
			s.close()
		}()
	}
	<-ctx.Done()
	s.close()
	if stdio {
		if input, ok := stdin.(io.Closer); ok {
			_ = input.Close()
		}
	}
	s.wg.Wait()
	return nil
}

type runtimeServer struct {
	ctx            context.Context
	cancel         context.CancelFunc
	mu             sync.Mutex
	writeMu        sync.Mutex
	wg             sync.WaitGroup
	profiles       map[string]*runtimeProfile
	eventOut       io.Writer
	closed         bool
	connections    map[net.Conn]struct{}
	history        *HistoryStore
	historyPath    string
	historyEnabled bool
}

func (s *runtimeServer) serveConn(conn net.Conn) {
	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		_ = conn.Close()
		return
	}
	if s.connections == nil {
		s.connections = map[net.Conn]struct{}{}
	}
	s.connections[conn] = struct{}{}
	s.mu.Unlock()
	defer func() {
		s.mu.Lock()
		delete(s.connections, conn)
		s.mu.Unlock()
		_ = conn.Close()
	}()
	out := &runtimeSocketOutput{Conn: conn}
	scanner := bufio.NewScanner(conn)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		var req RuntimeRequest
		if json.Unmarshal(scanner.Bytes(), &req) != nil {
			s.write(out, RuntimeResponse{Version: runtimeProtocolVersion, ExitCode: 2, Stderr: "invalid runtime request"})
			continue
		}
		s.dispatch(req, out)
	}
}

func (s *runtimeServer) dispatch(req RuntimeRequest, out io.Writer) {
	if req.Operation == "configure" || req.Operation == "status" || req.Operation == "shutdown" {
		s.handle(req, out)
		return
	}
	p := s.profile(req.ProfileID, req.Revision)
	if p == nil {
		s.write(out, RuntimeResponse{Version: runtimeProtocolVersion, ID: req.ID, ExitCode: 2, Stderr: "profile is not configured"})
		return
	}
	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		s.write(out, RuntimeResponse{Version: runtimeProtocolVersion, ID: req.ID, ExitCode: 1, Stderr: "runtime is stopping"})
		return
	}
	select {
	case p.opSlots <- struct{}{}:
	default:
		s.mu.Unlock()
		s.write(out, RuntimeResponse{Version: runtimeProtocolVersion, ID: req.ID, ExitCode: 1, Stderr: "profile operation queue is full"})
		return
	}
	s.wg.Add(1)
	s.mu.Unlock()
	go func() {
		defer s.wg.Done()
		defer func() { <-p.opSlots }()
		s.handle(req, out)
	}()
}

type runtimeSocketOutput struct {
	net.Conn
	mu sync.Mutex
}

func (w *runtimeSocketOutput) Write(payload []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	_ = w.SetWriteDeadline(time.Now().Add(5 * time.Second))
	return w.Conn.Write(payload)
}

func writeRuntimeLine(w io.Writer, value any) error {
	payload, err := json.Marshal(value)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(w, string(payload))
	return err
}

func (s *runtimeServer) writeResponse(resp RuntimeResponse) { s.write(s.eventOut, resp) }
func (s *runtimeServer) write(out io.Writer, value any) {
	if _, ok := out.(*runtimeSocketOutput); ok {
		_ = writeRuntimeLine(out, value)
		return
	}
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	writeRuntimeLine(out, value)
}

func (s *runtimeServer) handle(req RuntimeRequest, out io.Writer) {
	resp := RuntimeResponse{Version: runtimeProtocolVersion, ID: req.ID}
	if req.Version != runtimeProtocolVersion {
		resp.ExitCode, resp.Stderr = 2, "unsupported runtime protocol version"
		s.write(out, resp)
		return
	}
	switch req.Operation {
	case "configure":
		if err := s.configure(req.Profiles); err != nil {
			resp.ExitCode, resp.Stderr = 1, err.Error()
			if errors.Is(err, errConfig) {
				resp.ExitCode = 2
			}
		}
	case "status":
		resp.Stdout = s.statusJSON(req.ProfileID)
	case "refresh":
		if p := s.profile(req.ProfileID, req.Revision); p != nil {
			if err := p.refresh(p.ctx, true); err != nil {
				resp.ExitCode, resp.Stderr = 1, safeRuntimeError(err)
			}
		} else {
			resp.ExitCode, resp.Stderr = 2, "profile is not configured"
		}
	case "context_inbox":
		if p := s.profile(req.ProfileID, req.Revision); p != nil {
			p.opMu.Lock()
			limit := 100
			if len(req.Arguments) > 0 {
				if parsed, err := strconv.Atoi(req.Arguments[0]); err == nil && parsed > 0 {
					limit = parsed
				}
			}
			result, err := p.client.withContext(p.ctx).GetInboxForContext(p.config.AgentHandle, limit)
			if err != nil {
				resp.ExitCode, resp.Stderr = 1, safeRuntimeError(err)
			} else {
				payload, _ := json.Marshal(result)
				resp.Stdout = string(payload)
			}
			p.opMu.Unlock()
		} else {
			resp.ExitCode, resp.Stderr = 2, "profile is not configured"
		}
	case "command":
		p := s.profile(req.ProfileID, req.Revision)
		if p == nil {
			resp.ExitCode, resp.Stderr = 2, "profile is not configured"
			break
		}
		p.opMu.Lock()
		if !isHistoryCommand(req.Arguments) {
			if err := p.ensureReadyLocked(); err != nil {
				p.opMu.Unlock()
				resp.ExitCode, resp.Stderr = 1, safeRuntimeError(err)
				break
			}
		}
		if err := p.ctx.Err(); err != nil {
			p.opMu.Unlock()
			resp.ExitCode, resp.Stderr = 1, "profile was canceled"
			break
		}
		var stdout, stderr strings.Builder
		var runErr error
		resp.ExitCode, runErr = runWithRouting("gulls", req.Arguments, &stdout, &stderr, flattenEnv(p.profile.Environment), p.commandClient(), false)
		if runErr != nil {
			if resp.ExitCode == 0 {
				resp.ExitCode = 1
			}
			if errors.Is(runErr, errUsage) || errors.Is(runErr, errConfig) {
				resp.ExitCode = 2
			}
			if stderr.Len() == 0 {
				stderr.WriteString(runErr.Error())
			}
		}
		if resp.ExitCode == 0 && commandMutates(req.Arguments) {
			_ = p.refreshLocked(p.ctx, true)
		}
		p.opMu.Unlock()
		resp.Stdout, resp.Stderr = stdout.String(), stderr.String()
	case "shutdown":
		s.write(out, resp)
		s.close()
		return
	default:
		resp.ExitCode, resp.Stderr = 2, "unknown runtime operation"
	}
	s.write(out, resp)
}

func (s *runtimeServer) configure(profiles []RuntimeProfile) error {
	desired := map[string]RuntimeProfile{}
	for _, p := range profiles {
		if p.ID != "" {
			desired[p.ID] = p
		}
	}
	var configErrors []string
	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		return errors.New("runtime is stopping")
	}
	for id, old := range s.profiles {
		if next, ok := desired[id]; !ok || !sameRuntimeProfile(old.profile, next) {
			old.cancel()
			delete(s.profiles, id)
			s.emit(RuntimeInboxEvent{Version: runtimeProtocolVersion, Event: "inbox", ProfileID: id, Revision: old.profile.Revision, Status: "paused"})
		}
	}
	for id, p := range desired {
		if _, ok := s.profiles[id]; ok {
			continue
		}
		rp, err := newRuntimeProfile(s.ctx, p, s)
		if err != nil {
			s.emit(RuntimeInboxEvent{Version: runtimeProtocolVersion, Event: "inbox", ProfileID: id, Revision: p.Revision, Status: "unavailable", Error: safeRuntimeError(err)})
			configErrors = append(configErrors, id+": "+safeRuntimeError(err))
			continue
		}
		s.profiles[id] = rp
		s.emit(RuntimeInboxEvent{Version: runtimeProtocolVersion, Event: "inbox", ProfileID: id, Revision: p.Revision, Inbox: rp.historyEnvelope(rp.inbox), CheckedAt: rp.checked.UTC().Format(time.RFC3339), Status: "paused"})
		s.wg.Add(1)
		go func() {
			defer s.wg.Done()
			rp.run(s.ctx)
		}()
	}
	s.mu.Unlock()
	if len(configErrors) > 0 {
		return fmt.Errorf("%w: %s", errConfig, strings.Join(configErrors, "; "))
	}
	return nil
}

func sameRuntimeProfile(a, b RuntimeProfile) bool {
	if a.ID != b.ID || a.PollInterval != b.PollInterval || a.Monitoring != b.Monitoring || a.Revision != b.Revision || profileIdentity(a) != profileIdentity(b) || len(a.Environment) != len(b.Environment) {
		return false
	}
	for k, v := range a.Environment {
		if b.Environment[k] != v {
			return false
		}
	}
	return true
}

func (s *runtimeServer) profile(id, revision string) *runtimeProfile {
	s.mu.Lock()
	defer s.mu.Unlock()
	p := s.profiles[id]
	if p == nil || (revision != "" && p.profile.Revision != revision) {
		return nil
	}
	return p
}

func (s *runtimeServer) emit(event RuntimeInboxEvent) {
	if s.eventOut != nil {
		s.write(s.eventOut, event)
	}
}

func (s *runtimeServer) emitProfile(p *runtimeProfile, event RuntimeInboxEvent) {
	s.mu.Lock()
	current := s.profiles[p.profile.ID]
	s.mu.Unlock()
	if current != p {
		return
	}
	s.emit(event)
}

func (s *runtimeServer) statusJSON(id string) string {
	s.mu.Lock()
	profiles := make(map[string]*runtimeProfile, len(s.profiles))
	for key, p := range s.profiles {
		profiles[key] = p
	}
	s.mu.Unlock()
	items := []map[string]any{}
	for key, p := range profiles {
		if id != "" && id != key {
			continue
		}
		p.mu.RLock()
		items = append(items, map[string]any{"id": key, "revision": p.profile.Revision, "status": p.status, "checked_at": p.checked.UTC().Format(time.RFC3339), "monitoring": p.profile.Monitoring, "error": p.errText, "identity": profileIdentity(p.profile)})
		p.mu.RUnlock()
	}
	payload, _ := json.Marshal(map[string]any{"profiles": items})
	return string(payload)
}

func (s *runtimeServer) close() {
	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		return
	}
	s.closed = true
	for _, p := range s.profiles {
		p.cancel()
	}
	s.profiles = map[string]*runtimeProfile{}
	connections := make([]net.Conn, 0, len(s.connections))
	for conn := range s.connections {
		connections = append(connections, conn)
	}
	s.mu.Unlock()
	if s.cancel != nil {
		s.cancel()
	}
	for _, conn := range connections {
		_ = conn.Close()
	}
}

func newRuntimeProfile(parent context.Context, p RuntimeProfile, s *runtimeServer) (*runtimeProfile, error) {
	interval := p.PollInterval
	if interval <= 0 {
		interval = 15
	}
	env := flattenEnv(p.Environment)
	cfg, err := LoadConfig(env, ConfigOverrides{PollIntervalSeconds: &interval})
	if err != nil {
		return nil, err
	}
	if s != nil && s.history == nil && s.historyEnabled {
		path := s.historyPath
		if path == "" {
			path = filepath.Join(cfg.ContextDir, "history.sqlite3")
		}
		s.history, err = OpenHistoryStore(path, "runtime")
		if err != nil {
			return nil, err
		}
	}
	profileCtx, cancel := context.WithCancel(parent)
	hc := NewHTTPClient(cfg.APIURL, cfg.Token)
	hc.SocialAPIURL, hc.NodeID = cfg.SocialAPIURL, cfg.NodeID
	hc.Client = &http.Client{Timeout: 10 * time.Second, Transport: &http.Transport{}}
	rp := &runtimeProfile{profile: p, config: cfg, client: hc, ctx: profileCtx, server: s, cancel: cancel, status: "paused", opSlots: make(chan struct{}, 32)}
	rp.loadSnapshot()
	if s != nil && s.history != nil {
		rp.history, err = s.history.ForScope(historyProfileScope(cfg))
		if err != nil {
			cancel()
			return nil, err
		}
		rp.historyWake = make(chan struct{}, 1)
		if err := rp.restoreHistory(); err != nil {
			cancel()
			return nil, err
		}
	}
	return rp, nil
}

func (p *runtimeProfile) run(ctx context.Context) {
	if p.history != nil {
		done := make(chan struct{})
		go func() { defer close(done); p.syncHistoryLoop() }()
		defer func() { p.cancel(); <-done }()
		if !p.profile.Monitoring {
			select {
			case <-ctx.Done():
			case <-p.ctx.Done():
			}
			return
		}
	}
	if !p.profile.Monitoring {
		return
	}
	interval := time.Duration(p.profile.PollInterval * float64(time.Second))
	if interval <= 0 {
		interval = 15 * time.Second
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		if err := p.refresh(p.ctx, false); err != nil && isRuntimeAuthorizationError(err) {
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-p.ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func isRuntimeAuthorizationError(err error) bool {
	var se *statusError
	return errors.As(err, &se) && (se.code == 401 || se.code == 403)
}

func safeRuntimeError(err error) string {
	if err == nil {
		return ""
	}
	msg := err.Error()
	for _, part := range strings.Fields(msg) {
		if strings.HasPrefix(part, "sga_") {
			msg = strings.ReplaceAll(msg, part, "[redacted]")
		}
	}
	return msg
}

func (p *runtimeProfile) refresh(ctx context.Context, force bool) error {
	p.opMu.Lock()
	defer p.opMu.Unlock()
	return p.refreshLocked(ctx, force)
}

func (p *runtimeProfile) refreshLocked(ctx context.Context, force bool) error {
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if !p.profile.Monitoring && !force {
		p.mu.Lock()
		p.status, p.errText, p.checked = "paused", "", time.Now()
		p.emitLocked()
		if err := p.saveSnapshotLocked(); err != nil {
			p.errText = "snapshot persistence failed: " + safeRuntimeError(err)
			p.emitLocked()
			p.mu.Unlock()
			return err
		}
		p.mu.Unlock()
		return nil
	}
	p.mu.Lock()
	p.status = "connecting"
	p.emitLocked()
	p.mu.Unlock()
	inbox, err := p.client.withContext(ctx).GetInbox(p.config.AgentHandle, 100)
	if err == nil && p.history != nil {
		err = p.history.ImportInboxPageNamed("recent", inboxItems(inbox), "", false)
	}
	if err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		p.mu.Lock()
		p.checked = time.Now()
		p.errText = safeRuntimeError(err)
		if isRuntimeAuthorizationError(err) {
			p.status = "authorization_required"
		} else {
			p.status = "reconnecting"
		}
		p.emitLocked()
		if saveErr := p.saveSnapshotLocked(); saveErr != nil {
			p.errText = "snapshot persistence failed: " + safeRuntimeError(saveErr)
			p.emitLocked()
		}
		p.mu.Unlock()
		return err
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	status := "connected"
	if !p.profile.Monitoring {
		status = "paused"
	}
	p.mu.Lock()
	p.checked = time.Now()
	p.inbox, p.errText, p.status = inbox, "", status
	p.emitLocked()
	if saveErr := p.saveSnapshotLocked(); saveErr != nil {
		p.errText = "snapshot persistence failed: " + safeRuntimeError(saveErr)
		p.emitLocked()
		p.mu.Unlock()
		return saveErr
	}
	p.mu.Unlock()
	p.wakeHistorySync()
	return nil
}

func (p *runtimeProfile) ensureReadyLocked() error {
	p.mu.RLock()
	ready, monitoring := p.inbox != nil, p.profile.Monitoring
	p.mu.RUnlock()
	if ready {
		return nil
	}
	if !monitoring {
		return nil
	}
	return p.refreshLocked(p.ctx, true)
}

func commandMutates(args []string) bool {
	command := ""
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if strings.HasPrefix(arg, "-") {
			if arg == "--json" || arg == "--approve" {
				continue
			}
			if !strings.Contains(arg, "=") && i+1 < len(args) {
				i++
			}
			continue
		}
		command = arg
		break
	}
	switch command {
	case "reply", "ack", "ignore", "post", "route":
		return true
	case "draft-reply":
		for _, arg := range args {
			if arg == "--approve" {
				return true
			}
		}
	}
	return false
}

func (p *runtimeProfile) emitLocked() {
	if p.server == nil {
		return
	}
	p.server.emitProfile(p, RuntimeInboxEvent{Version: runtimeProtocolVersion, Event: "inbox", ProfileID: p.profile.ID, Revision: p.profile.Revision, Inbox: p.historyEnvelope(p.inbox), CheckedAt: p.checked.UTC().Format(time.RFC3339), Status: p.status, Error: p.errText})
}

func (p *runtimeProfile) snapshotPath() string {
	return filepath.Join(p.config.ContextDir, "inbox-snapshot.json")
}

func (p *runtimeProfile) loadSnapshot() {
	payload, err := os.ReadFile(p.snapshotPath())
	if err != nil {
		return
	}
	var snap runtimeSnapshot
	if json.Unmarshal(payload, &snap) != nil || snap.Version != runtimeProtocolVersion || snap.Identity != profileIdentity(p.profile) || snap.Revision != p.profile.Revision || snap.Inbox == nil {
		return
	}
	p.inbox = snap.Inbox
	p.errText = ""
	if p.profile.Monitoring {
		p.status = "connecting"
	} else {
		p.status = "paused"
	}
	if parsed, err := time.Parse(time.RFC3339, snap.CheckedAt); err == nil {
		p.checked = parsed
	}
}

func (p *runtimeProfile) saveSnapshotLocked() error {
	if err := os.MkdirAll(p.config.ContextDir, 0o700); err != nil {
		return err
	}
	if err := os.Chmod(p.config.ContextDir, 0o700); err != nil {
		return err
	}
	s := runtimeSnapshot{Version: runtimeProtocolVersion, Identity: profileIdentity(p.profile), Revision: p.profile.Revision, CheckedAt: p.checked.UTC().Format(time.RFC3339), Inbox: p.inbox, Status: p.status, Error: p.errText}
	payload, _ := json.MarshalIndent(s, "", "  ")
	payload = append(payload, '\n')
	tmp, err := os.CreateTemp(p.config.ContextDir, ".inbox-snapshot-*")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)
	if err := tmp.Chmod(0o600); err != nil {
		_ = tmp.Close()
		return err
	}
	if _, err := tmp.Write(payload); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpPath, p.snapshotPath()); err != nil {
		return err
	}
	return os.Chmod(p.snapshotPath(), 0o600)
}

func (p *runtimeProfile) cached(limit int) (map[string]any, error) {
	p.mu.RLock()
	defer p.mu.RUnlock()
	if p.inbox == nil {
		return nil, errors.New("inbox snapshot is not ready")
	}
	return limitInbox(p.inbox, limit), nil
}

func limitInbox(inbox map[string]any, limit int) map[string]any {
	if limit <= 0 {
		return inbox
	}
	items, ok := inbox["items"].([]any)
	if !ok || len(items) <= limit {
		return inbox
	}
	copy := map[string]any{}
	for k, v := range inbox {
		copy[k] = v
	}
	copy["items"] = items[:limit]
	return copy
}

type runtimeProfileClient struct {
	Client
	profile *runtimeProfile
}

type runtimeIPCInboxClient struct {
	Client
	socket, profileID, revision string
}

func (c *runtimeIPCInboxClient) GetInbox(handle string, limit int) (map[string]any, error) {
	args := []string{"--json", "inbox", "--limit", fmt.Sprint(limit)}
	resp, err := RuntimeClientRequest(c.socket, RuntimeRequest{Version: runtimeProtocolVersion, ID: runtimeCommandID(args), Operation: "command", ProfileID: c.profileID, Revision: c.revision, Arguments: args})
	if err != nil {
		return nil, err
	}
	if resp.ExitCode != 0 {
		return nil, errors.New(resp.Stderr)
	}
	var inbox map[string]any
	if err := json.Unmarshal([]byte(resp.Stdout), &inbox); err != nil {
		return nil, err
	}
	return inbox, nil
}
func (c *runtimeIPCInboxClient) GetInboxForContext(handle string, limit int) (map[string]any, error) {
	args := []string{fmt.Sprint(limit)}
	resp, err := RuntimeClientRequest(c.socket, RuntimeRequest{Version: runtimeProtocolVersion, ID: runtimeCommandID(args), Operation: "context_inbox", ProfileID: c.profileID, Revision: c.revision, Arguments: args})
	if err != nil {
		return nil, err
	}
	if resp.ExitCode != 0 {
		return nil, errors.New(resp.Stderr)
	}
	var inbox map[string]any
	if err := json.Unmarshal([]byte(resp.Stdout), &inbox); err != nil {
		return nil, err
	}
	return inbox, nil
}

func (c *runtimeIPCInboxClient) GetWatchInbox(handle string, limit int, seen map[string]bool) (map[string]any, error) {
	return runtimeWatchInbox(c, handle, limit, seen)
}

func (c *runtimeProfileClient) GetWatchInbox(handle string, limit int, seen map[string]bool) (map[string]any, error) {
	return runtimeWatchInbox(c, handle, limit, seen)
}

func runtimeWatchInbox(client Client, handle string, limit int, seen map[string]bool) (map[string]any, error) {
	inbox, err := client.GetInbox(handle, limit)
	if err != nil {
		return nil, err
	}
	for _, item := range inboxItems(inbox) {
		if id := itemDeliveryID(item); id != "" && !seen[id] {
			// Only a new handoff needs fresh authenticated owner instructions.
			return getInboxForContext(client, handle, limit)
		}
	}
	return inbox, nil
}

func (c *runtimeProfileClient) GetInbox(handle string, limit int) (map[string]any, error) {
	return c.profile.cached(limit)
}
func (c *runtimeProfileClient) GetInboxForContext(handle string, limit int) (map[string]any, error) {
	// Context handoff files require the authenticated owner instruction set;
	// never satisfy that path from the resident cache.
	return c.profile.client.withContext(c.profile.ctx).GetInboxForContext(handle, limit)
}

func (p *runtimeProfile) commandClient() Client {
	return &runtimeProfileClient{Client: p.client.withContext(p.ctx), profile: p}
}

func flattenEnv(values map[string]string) []string {
	out := make([]string, 0, len(values))
	for k, v := range values {
		out = append(out, k+"="+v)
	}
	return out
}

func RuntimeClientRequest(path string, req RuntimeRequest) (RuntimeResponse, error) {
	if path == "" {
		return RuntimeResponse{}, errors.New("runtime socket is not configured")
	}
	conn, err := net.DialTimeout("unix", path, 2*time.Second)
	if err != nil {
		return RuntimeResponse{}, err
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(30 * time.Second))
	if err := writeRuntimeLine(conn, req); err != nil {
		return RuntimeResponse{}, err
	}
	scanner := bufio.NewScanner(conn)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		var resp RuntimeResponse
		var event RuntimeInboxEvent
		line := scanner.Bytes()
		if json.Unmarshal(line, &resp) == nil && resp.Version != 0 {
			if resp.Version != runtimeProtocolVersion {
				return RuntimeResponse{}, errors.New("unsupported runtime response version")
			}
			if resp.ID != req.ID {
				return RuntimeResponse{}, errors.New("runtime response id mismatch")
			}
			return resp, nil
		}
		_ = json.Unmarshal(line, &event)
	}
	if err := scanner.Err(); err != nil {
		return RuntimeResponse{}, err
	}
	return RuntimeResponse{}, errors.New("runtime closed without response")
}

func runtimeCommandID(args []string) string {
	sum := sha256.Sum256([]byte(strings.Join(args, "\x00")))
	return hex.EncodeToString(sum[:8])
}
func runRuntimeCommand(args []string, global globalOptions, stdout, stderr io.Writer, env []string) (int, error) {
	if len(args) == 0 {
		return 0, usage("runtime requires subcommand: serve or status")
	}
	switch args[0] {
	case "serve":
		fs := commandFlagSet("runtime serve", stderr)
		socket := fs.String("socket", RuntimeSocketPath(env), "private Unix socket path")
		stdio := fs.Bool("stdio", false, "serve newline JSON over stdin/stdout")
		if err := parseCommand(fs, args[1:]); err != nil {
			return 0, err
		}
		if !*stdio {
			if _, err := LoadConfig(env, ConfigOverrides{APIURL: global.APIURL, AgentHandle: global.AgentHandle, ContextDir: global.ContextDir}); err != nil {
				return 0, fmt.Errorf("%w: %w", errConfig, err)
			}
		}
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		if !*stdio {
			cfg, err := LoadConfig(env, ConfigOverrides{APIURL: global.APIURL, AgentHandle: global.AgentHandle, ContextDir: global.ContextDir})
			if err != nil {
				return 0, err
			}
			profile := RuntimeProfile{ID: profileIdentity(RuntimeProfile{Environment: map[string]string{"SEAGULL_API_URL": cfg.APIURL, "SEAGULL_AGENT_HANDLE": cfg.AgentHandle, "SEAGULL_AGENT_CONTEXT_DIR": cfg.ContextDir}}), Environment: map[string]string{}, PollInterval: cfg.PollInterval.Seconds(), Monitoring: true}
			for _, item := range env {
				k, v, ok := strings.Cut(item, "=")
				if ok && strings.HasPrefix(k, "SEAGULL_") {
					profile.Environment[k] = v
				}
			}
			if profile.Environment["SEAGULL_API_URL"] == "" {
				profile.Environment["SEAGULL_API_URL"] = cfg.APIURL
			}
			if profile.Environment["SEAGULL_AGENT_HANDLE"] == "" {
				profile.Environment["SEAGULL_AGENT_HANDLE"] = cfg.AgentHandle
			}
			if profile.Environment["SEAGULL_AGENT_CONTEXT_DIR"] == "" {
				profile.Environment["SEAGULL_AGENT_CONTEXT_DIR"] = cfg.ContextDir
			}
			profile.Environment["SEAGULL_API_URL"] = cfg.APIURL
			profile.Environment["SEAGULL_AGENT_HANDLE"] = cfg.AgentHandle
			profile.Environment["SEAGULL_AGENT_CONTEXT_DIR"] = cfg.ContextDir
			if cfg.SocialAPIURL != "" {
				profile.Environment["SEAGULL_SOCIAL_API_URL"] = cfg.SocialAPIURL
			}
			if cfg.NodeID != "" {
				profile.Environment["SEAGULL_NODE_ID"] = cfg.NodeID
			}
			if cfg.Token != "" {
				profile.Environment["SEAGULL_CONNECTOR_TOKEN"] = cfg.Token
			}
			// The server accepts configure through the same protocol; seed the
			// direct mode profile before it begins serving requests.
			return 0, runtimeServeSeeded(ctx, *socket, profile)
		}
		return 0, RuntimeServe(ctx, *socket, true, os.Stdin, stdout, stderr)
	case "status":
		if err := parseCommand(commandFlagSet("runtime status", stderr), args[1:]); err != nil {
			return 0, err
		}
		path := RuntimeSocketPath(env)
		if !RuntimeSocketAvailable(path) {
			return 0, errors.New("runtime is not running")
		}
		resp, err := RuntimeClientRequest(path, RuntimeRequest{Version: runtimeProtocolVersion, ID: runtimeCommandID(args), Operation: "status"})
		if err != nil {
			return 0, err
		}
		if resp.Stderr != "" && resp.ExitCode != 0 {
			return resp.ExitCode, errors.New(resp.Stderr)
		}
		if global.JSON {
			fmt.Fprintln(stdout, resp.Stdout)
		} else {
			fmt.Fprintln(stdout, resp.Stdout)
		}
		return resp.ExitCode, nil
	default:
		return 0, usage("unknown runtime subcommand: " + args[0])
	}
}

func runtimeServeSeeded(ctx context.Context, socket string, profile RuntimeProfile) error {
	// RuntimeServe owns its server lifecycle. Seed through a tiny in-process
	// wrapper so direct mode still uses exactly the v1 configure path.
	return runtimeServeWithProfiles(ctx, socket, false, os.Stdin, io.Discard, io.Discard, []RuntimeProfile{profile})
}

func tryRuntimeRoute(global globalOptions, remaining []string, stdout, stderr io.Writer, env []string) (int, bool, error) {
	command := remaining[0]
	if command == "runtime" || command == "stream" || command == "version" || command == "login" || command == "auth" || command == "logout" || command == "pair" || command == "local-action" {
		return 0, false, nil
	}
	if command == "watch" {
		once := false
		for _, arg := range remaining[1:] {
			if arg == "--once" {
				once = true
				break
			}
		}
		if !once {
			return 0, false, nil
		}
	}
	path := RuntimeSocketPath(env)
	if !RuntimeSocketAvailable(path) {
		return 0, false, nil
	}
	identity, err := runtimeProfileIdentity(env, ConfigOverrides{APIURL: global.APIURL, AgentHandle: global.AgentHandle, ContextDir: global.ContextDir})
	if err != nil {
		return 0, false, nil
	}
	status, err := RuntimeClientRequest(path, RuntimeRequest{Version: runtimeProtocolVersion, ID: runtimeCommandID([]string{"status", identity}), Operation: "status"})
	if err != nil {
		return 0, true, err
	}
	var payload struct {
		Profiles []struct{ ID, Revision, Identity string } `json:"profiles"`
	}
	if json.Unmarshal([]byte(status.Stdout), &payload) != nil {
		return 0, true, errors.New("runtime returned invalid status")
	}
	var match *struct{ ID, Revision, Identity string }
	for i := range payload.Profiles {
		if payload.Profiles[i].Identity == identity {
			match = &payload.Profiles[i]
			break
		}
	}
	if match == nil {
		return 0, false, nil
	}
	args := append([]string{}, remaining...)
	if global.JSON {
		args = append([]string{"--json"}, args...)
	}
	req := RuntimeRequest{Version: runtimeProtocolVersion, ID: runtimeCommandID(args), Operation: "command", ProfileID: match.ID, Revision: match.Revision, Arguments: args}
	resp, err := RuntimeClientRequest(path, req)
	if err != nil {
		return 0, true, err
	}
	if resp.Stdout != "" {
		_, _ = io.WriteString(stdout, resp.Stdout)
		if !strings.HasSuffix(resp.Stdout, "\n") {
			_, _ = io.WriteString(stdout, "\n")
		}
	}
	if resp.Stderr != "" {
		_, _ = io.WriteString(stderr, resp.Stderr)
		if !strings.HasSuffix(resp.Stderr, "\n") {
			_, _ = io.WriteString(stderr, "\n")
		}
	}
	return resp.ExitCode, true, nil
}

func runtimeManagedInboxClient(global globalOptions, env []string) (*runtimeIPCInboxClient, bool) {
	path := RuntimeSocketPath(env)
	if !RuntimeSocketAvailable(path) {
		return nil, false
	}
	identity, err := runtimeProfileIdentity(env, ConfigOverrides{APIURL: global.APIURL, AgentHandle: global.AgentHandle, ContextDir: global.ContextDir})
	if err != nil {
		return nil, false
	}
	resp, err := RuntimeClientRequest(path, RuntimeRequest{Version: runtimeProtocolVersion, ID: runtimeCommandID([]string{"status", identity}), Operation: "status"})
	if err != nil {
		return nil, false
	}
	var payload struct {
		Profiles []struct{ ID, Revision, Identity string } `json:"profiles"`
	}
	if json.Unmarshal([]byte(resp.Stdout), &payload) != nil {
		return nil, false
	}
	for _, p := range payload.Profiles {
		if p.Identity == identity {
			return &runtimeIPCInboxClient{socket: path, profileID: p.ID, revision: p.Revision}, true
		}
	}
	return nil, false
}
