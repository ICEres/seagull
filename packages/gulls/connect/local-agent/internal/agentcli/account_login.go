package agentcli

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"os/user"
	"path/filepath"
	"reflect"
	"runtime"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"
)

const (
	defaultAccountWebsite = "https://sea.gulls.ai"
	accountSessionEnv     = "SEAGULL_ACCOUNT_SESSION_FILE"
	accountSessionLimit   = 64 * 1024
	accountCallbackLimit  = 32 * 1024
)

type accountSession struct {
	Version     int    `json:"version"`
	WebsiteURL  string `json:"website_url"`
	AccessToken string `json:"access_token"`
	ExpiresAt   int64  `json:"expires_at"`
}

type accountStatus struct {
	SignedIn   bool           `json:"signed_in"`
	WebsiteURL string         `json:"website_url"`
	ExpiresAt  int64          `json:"expires_at,omitempty"`
	Identity   map[string]any `json:"identity,omitempty"`
}

type accountRuntimeConfig struct {
	SocialAPIURL string
}

type accountCallbackSession struct {
	AccessToken string `json:"accessToken"`
	ExpiresAt   int64  `json:"expiresAt"`
	TokenType   string `json:"tokenType"`
}

type accountCallbackPayload struct {
	State   string                 `json:"state"`
	Session accountCallbackSession `json:"session"`
}

type verifiedAccountSession struct {
	Session  accountCallbackSession
	Identity map[string]any
	Expires  int64
}

var accountNow = time.Now

var errInvalidAccountSession = errors.New("account session file is invalid")

var accountOpenBrowser = func(target string) error {
	var command string
	var args []string
	switch runtime.GOOS {
	case "darwin":
		command, args = "open", []string{target}
	case "windows":
		command, args = "rundll32", []string{"url.dll,FileProtocolHandler", target}
	default:
		command, args = "xdg-open", []string{target}
	}
	if err := exec.Command(command, args...).Start(); err != nil {
		return fmt.Errorf("could not open the browser with %s: %w", command, err)
	}
	return nil
}

func runAccountLogin(commandArgs []string, global globalOptions, stdout, stderr io.Writer, env []string) (int, error) {
	fs := commandFlagSet("login", stderr)
	website := fs.String("server", defaultAccountWebsite, "Seagull website URL")
	sessionFile := fs.String("session-file", "", "account session file")
	noBrowser := fs.Bool("no-browser", false, "print the browser URL to stderr and wait")
	timeout := fs.Duration("timeout", 5*time.Minute, "maximum browser login time")
	if err := parseCommand(fs, commandArgs); err != nil {
		return 0, err
	}
	if fs.NArg() != 0 {
		return 0, usage("login does not accept positional arguments")
	}
	if *timeout <= 0 {
		return 0, usage("login timeout must be positive")
	}

	websiteURL, err := validateAccountWebsite(*website)
	if err != nil {
		return 0, err
	}
	sessionPath := accountSessionPath(env, *sessionFile)
	runtimeConfig, err := loadAccountRuntimeConfig(websiteURL)
	if err != nil {
		return 0, err
	}
	if existing, err := readAccountSession(sessionPath); err == nil && existing != nil &&
		accountWebsiteEqual(existing.WebsiteURL, websiteURL) && existing.ExpiresAt > accountNow().UnixMilli() {
		identity, verifyErr := verifyAccountToken(runtimeConfig.SocialAPIURL, existing.AccessToken)
		if verifyErr == nil {
			printAccountStatus(stdout, global.JSON, accountStatus{SignedIn: true, WebsiteURL: websiteURL, ExpiresAt: existing.ExpiresAt, Identity: identity})
			return 0, nil
		}
	} else if err != nil && !errors.Is(err, os.ErrNotExist) && !errors.Is(err, errInvalidAccountSession) {
		return 0, err
	}

	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return 0, fmt.Errorf("could not start the local login callback: %w", err)
	}
	defer listener.Close()
	stateBytes := make([]byte, 32)
	if _, err := rand.Read(stateBytes); err != nil {
		return 0, fmt.Errorf("could not create login state: %w", err)
	}
	state := base64.RawURLEncoding.EncodeToString(stateBytes)
	callbackURL := "http://" + listener.Addr().String() + "/callback"
	browserURL := strings.TrimRight(websiteURL, "/") + "/desktop/login#callback=" + url.QueryEscape(callbackURL) + "&state=" + url.QueryEscape(state)

	verified := make(chan verifiedAccountSession, 1)
	callbackDone := make(chan struct{})
	var callbackConsumed atomic.Bool
	mux := http.NewServeMux()
	finalize := func(callback accountCallbackSession) (map[string]any, int64, error) {
		if !strings.EqualFold(callback.TokenType, "bearer") {
			return nil, 0, errors.New("browser login returned an unsupported token type")
		}
		if callback.AccessToken == "" || callback.ExpiresAt <= accountNow().UnixMilli() {
			return nil, 0, errors.New("browser login returned an invalid or expired session")
		}
		expiresAt := clampJWTExpiry(callback.AccessToken, callback.ExpiresAt)
		if expiresAt <= accountNow().UnixMilli() {
			return nil, 0, errors.New("browser login returned an expired access token")
		}
		identity, err := verifyAccountToken(runtimeConfig.SocialAPIURL, callback.AccessToken)
		if err != nil {
			return nil, 0, err
		}
		if err := writeAccountSession(sessionPath, accountSession{Version: 1, WebsiteURL: websiteURL, AccessToken: callback.AccessToken, ExpiresAt: expiresAt}); err != nil {
			return nil, 0, err
		}
		return identity, expiresAt, nil
	}
	mux.HandleFunc("/callback", accountCallbackHandler(listener.Addr().String(), websiteURL, state, verified, callbackDone, &callbackConsumed, finalize))
	server := &http.Server{Handler: mux}
	serveErr := make(chan error, 1)
	go func() { serveErr <- server.Serve(listener) }()

	if *noBrowser {
		fmt.Fprintln(stderr, browserURL)
	} else if err := accountOpenBrowser(browserURL); err != nil {
		server.Close()
		return 0, err
	}

	ctx, cancel := signalContext(*timeout)
	defer cancel()
	select {
	case result := <-verified:
		shutdownAccountServer(server)
		printAccountStatus(stdout, global.JSON, accountStatus{SignedIn: true, WebsiteURL: websiteURL, ExpiresAt: result.Expires, Identity: result.Identity})
		return 0, nil
	case <-ctx.Done():
		server.Close()
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return 0, errors.New("browser login timed out")
		}
		return 0, errors.New("browser login cancelled")
	case err := <-serveErr:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			return 0, fmt.Errorf("local login callback failed: %w", err)
		}
		return 0, errors.New("local login callback closed before receiving a session")
	}
}

func runAccountStatus(commandArgs []string, global globalOptions, stdout, stderr io.Writer, env []string) (int, error) {
	fs := commandFlagSet("auth status", stderr)
	website := fs.String("server", defaultAccountWebsite, "Seagull website URL")
	sessionFile := fs.String("session-file", "", "account session file")
	if err := parseCommand(fs, commandArgs); err != nil {
		return 0, err
	}
	if fs.NArg() != 0 {
		return 0, usage("auth status does not accept positional arguments")
	}
	websiteURL, err := validateAccountWebsite(*website)
	if err != nil {
		return 0, err
	}
	status := accountStatus{WebsiteURL: websiteURL}
	session, err := readAccountSession(accountSessionPath(env, *sessionFile))
	if err != nil && !errors.Is(err, os.ErrNotExist) && !errors.Is(err, errInvalidAccountSession) {
		return 0, err
	}
	if session != nil && accountWebsiteEqual(session.WebsiteURL, websiteURL) && session.ExpiresAt > accountNow().UnixMilli() {
		if config, configErr := loadAccountRuntimeConfig(websiteURL); configErr == nil {
			if identity, verifyErr := verifyAccountToken(config.SocialAPIURL, session.AccessToken); verifyErr == nil {
				status.SignedIn = true
				status.ExpiresAt = session.ExpiresAt
				status.Identity = identity
			}
		}
	}
	printAccountStatus(stdout, global.JSON, status)
	return 0, nil
}

func runAccountLogout(commandArgs []string, global globalOptions, stdout, stderr io.Writer, env []string) (int, error) {
	fs := commandFlagSet("logout", stderr)
	website := fs.String("server", defaultAccountWebsite, "Seagull website URL")
	sessionFile := fs.String("session-file", "", "account session file")
	if err := parseCommand(fs, commandArgs); err != nil {
		return 0, err
	}
	if fs.NArg() != 0 {
		return 0, usage("logout does not accept positional arguments")
	}
	websiteURL, err := validateAccountWebsite(*website)
	if err != nil {
		return 0, err
	}
	path := accountSessionPath(env, *sessionFile)
	session, err := readAccountSession(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) && !errors.Is(err, errInvalidAccountSession) {
		return 0, err
	}
	if errors.Is(err, errInvalidAccountSession) {
		if err := removeAccountSession(path); err != nil {
			return 0, err
		}
	} else if session != nil && accountWebsiteEqual(session.WebsiteURL, websiteURL) {
		if err := removeAccountSession(path); err != nil {
			return 0, err
		}
	}
	printAccountStatus(stdout, global.JSON, accountStatus{WebsiteURL: websiteURL})
	return 0, nil
}

func shutdownAccountServer(server *http.Server) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := server.Shutdown(ctx); err != nil {
		_ = server.Close()
	}
}

func signalContext(timeout time.Duration) (context.Context, context.CancelFunc) {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	timed, timedCancel := context.WithTimeout(ctx, timeout)
	return timed, func() {
		timedCancel()
		cancel()
	}
}

func accountCallbackHandler(
	expectedHost, expectedWebsite, expectedState string,
	received chan<- verifiedAccountSession,
	done chan<- struct{},
	consumed *atomic.Bool,
	finalize func(accountCallbackSession) (map[string]any, int64, error),
) http.HandlerFunc {
	expectedOrigin := accountOrigin(expectedWebsite)
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Host != expectedHost {
			http.Error(w, "invalid callback host", http.StatusBadRequest)
			return
		}
		if r.Method == http.MethodOptions {
			if r.Header.Get("Origin") != expectedOrigin {
				http.Error(w, "invalid callback origin", http.StatusForbidden)
				return
			}
			setCallbackCORS(w, expectedOrigin)
			w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
			if strings.EqualFold(r.Header.Get("Access-Control-Request-Private-Network"), "true") {
				w.Header().Set("Access-Control-Allow-Private-Network", "true")
			}
			w.WriteHeader(http.StatusNoContent)
			return
		}
		if r.Header.Get("Origin") != expectedOrigin {
			http.Error(w, "invalid callback origin", http.StatusForbidden)
			return
		}
		setCallbackCORS(w, expectedOrigin)
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if !strings.HasPrefix(strings.ToLower(r.Header.Get("Content-Type")), "application/json") {
			http.Error(w, "content type must be application/json", http.StatusUnsupportedMediaType)
			return
		}
		body, err := io.ReadAll(io.LimitReader(r.Body, accountCallbackLimit+1))
		if err != nil || len(body) > accountCallbackLimit {
			http.Error(w, "callback body is too large", http.StatusRequestEntityTooLarge)
			return
		}
		var payload accountCallbackPayload
		decoder := json.NewDecoder(bytes.NewReader(body))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&payload); err != nil || payload.State == "" || payload.Session.AccessToken == "" || payload.Session.ExpiresAt <= 0 {
			http.Error(w, "invalid callback payload", http.StatusBadRequest)
			return
		}
		if subtle.ConstantTimeCompare([]byte(payload.State), []byte(expectedState)) != 1 {
			http.Error(w, "invalid callback state", http.StatusBadRequest)
			return
		}
		if payload.Session.ExpiresAt <= time.Now().UnixMilli() {
			http.Error(w, "callback session expired", http.StatusBadRequest)
			return
		}
		if !consumed.CompareAndSwap(false, true) {
			http.Error(w, "callback already consumed", http.StatusGone)
			return
		}
		identity, expiresAt, err := finalize(payload.Session)
		if err != nil {
			consumed.Store(false)
			http.Error(w, "login session was rejected", http.StatusBadRequest)
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"ok":true}`)
		received <- verifiedAccountSession{Session: payload.Session, Identity: identity, Expires: expiresAt}
		close(done)
	}
}

func setCallbackCORS(w http.ResponseWriter, origin string) {
	w.Header().Set("Access-Control-Allow-Origin", origin)
	w.Header().Add("Vary", "Origin")
}

func validateAccountWebsite(raw string) (string, error) {
	u, err := parseAccountURL(raw, true)
	if err != nil {
		return "", fmt.Errorf("invalid website URL: %w", err)
	}
	return accountOrigin(u.String()), nil
}

func parseAccountURL(raw string, website bool) (*url.URL, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, errors.New("URL is empty")
	}
	u, err := url.Parse(raw)
	if err != nil || u.Scheme == "" || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return nil, errors.New("URL must have no credentials, query, or fragment")
	}
	scheme := strings.ToLower(u.Scheme)
	loopback := isAccountLoopback(u.Hostname())
	if scheme != "https" && !(scheme == "http" && loopback) {
		return nil, errors.New("URL must use HTTPS, except for HTTP loopback development URLs")
	}
	if website && u.Path != "" && u.Path != "/" {
		return nil, errors.New("website URL must identify an origin")
	}
	u.Scheme = scheme
	u.Path = ""
	u.RawPath = ""
	u.ForceQuery = false
	return u, nil
}

func isAccountLoopback(host string) bool {
	host = strings.ToLower(strings.Trim(host, "[]"))
	return host == "localhost" || host == "127.0.0.1" || host == "::1"
}

func accountOrigin(raw string) string {
	u, _ := url.Parse(raw)
	return u.Scheme + "://" + u.Host
}

func accountWebsiteEqual(a, b string) bool {
	left, err1 := validateAccountWebsite(a)
	right, err2 := validateAccountWebsite(b)
	return err1 == nil && err2 == nil && left == right
}

func loadAccountRuntimeConfig(website string) (accountRuntimeConfig, error) {
	client := accountHTTPTransportClient()
	req, err := http.NewRequest(http.MethodGet, strings.TrimRight(website, "/")+"/config.js", nil)
	if err != nil {
		return accountRuntimeConfig{}, errors.New("could not request website configuration")
	}
	resp, err := client.Do(req)
	if err != nil {
		return accountRuntimeConfig{}, fmt.Errorf("could not load website configuration: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return accountRuntimeConfig{}, fmt.Errorf("website configuration request failed (%d)", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, accountSessionLimit+1))
	if err != nil || len(body) > accountSessionLimit {
		return accountRuntimeConfig{}, errors.New("website configuration is too large")
	}
	config, err := parseAccountRuntimeConfig(body)
	if err != nil {
		return accountRuntimeConfig{}, err
	}
	if _, err := parseAccountURL(config.SocialAPIURL, false); err != nil {
		return accountRuntimeConfig{}, fmt.Errorf("website social API URL: %w", err)
	}
	return config, nil
}

func parseAccountRuntimeConfig(source []byte) (accountRuntimeConfig, error) {
	const prefix = "window.SEAGULL_CONFIG"
	text := strings.TrimSpace(string(source))
	index := strings.Index(text, prefix)
	if index < 0 {
		return accountRuntimeConfig{}, errors.New("website configuration has no supported SEAGULL_CONFIG assignment")
	}
	tail := strings.TrimSpace(text[index+len(prefix):])
	if !strings.HasPrefix(tail, "=") {
		return accountRuntimeConfig{}, errors.New("website configuration has an invalid assignment")
	}
	tail = strings.TrimSpace(strings.TrimPrefix(tail, "="))
	var raw map[string]json.RawMessage
	decoder := json.NewDecoder(strings.NewReader(tail))
	if err := decoder.Decode(&raw); err != nil {
		return accountRuntimeConfig{}, errors.New("website configuration is not valid JSON")
	}
	var social string
	if err := json.Unmarshal(raw["socialApiUrl"], &social); err != nil || strings.TrimSpace(social) == "" {
		return accountRuntimeConfig{}, errors.New("website configuration is missing socialApiUrl")
	}
	return accountRuntimeConfig{SocialAPIURL: strings.TrimRight(strings.TrimSpace(social), "/")}, nil
}

func accountHTTPTransportClient() *http.Client {
	return &http.Client{Timeout: 15 * time.Second, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}
}

func verifyAccountToken(socialURL, token string) (map[string]any, error) {
	if token == "" {
		return nil, errors.New("account session is missing an access token")
	}
	req, err := http.NewRequest(http.MethodGet, strings.TrimRight(socialURL, "/")+"/me", nil)
	if err != nil {
		return nil, errors.New("could not verify account session")
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Accept", "application/json")
	resp, err := accountHTTPTransportClient().Do(req)
	if err != nil {
		return nil, errors.New("could not verify account session")
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("account session verification failed (%d)", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, accountSessionLimit+1))
	if err != nil || len(body) > accountSessionLimit {
		return nil, errors.New("account session verification response is too large")
	}
	var result map[string]any
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, errors.New("account session verification returned invalid JSON")
	}
	identity := result
	if nested, ok := result["identity"].(map[string]any); ok {
		identity = nested
	}
	userID, _ := identity["user_id"].(string)
	if strings.TrimSpace(userID) == "" {
		return nil, errors.New("account session verification returned no user identity")
	}
	safe := map[string]any{"user_id": userID}
	for _, key := range []string{"email", "display_name", "provider", "subject"} {
		if value, ok := identity[key].(string); ok && value != "" {
			safe[key] = value
		}
	}
	return safe, nil
}

func clampJWTExpiry(token string, expiry int64) int64 {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return expiry
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return expiry
	}
	var claims struct {
		Exp float64 `json:"exp"`
	}
	if json.Unmarshal(payload, &claims) != nil || claims.Exp <= 0 {
		return expiry
	}
	jwtExpiry := int64(claims.Exp * 1000)
	if jwtExpiry > 0 && jwtExpiry < expiry {
		return jwtExpiry
	}
	return expiry
}

func accountSessionPath(env []string, override string) string {
	if path := strings.TrimSpace(override); path != "" {
		return expandHome(path)
	}
	if path := strings.TrimSpace(envMap(env)[accountSessionEnv]); path != "" {
		return expandHome(path)
	}
	return expandHome("~/.config/seagull/account.json")
}

func readAccountSession(path string) (*accountSession, error) {
	if err := validateAccountSessionParent(path); err != nil {
		return nil, err
	}
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || !accountOwnedByCurrentUser(info) {
		return nil, errors.New("account session file must be a private regular file")
	}
	if info.Size() > accountSessionLimit {
		return nil, errors.New("account session file is too large")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var session accountSession
	if err := json.Unmarshal(data, &session); err != nil || session.Version != 1 || session.WebsiteURL == "" || session.AccessToken == "" || session.ExpiresAt <= 0 {
		return nil, errInvalidAccountSession
	}
	return &session, nil
}

func writeAccountSession(path string, session accountSession) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("could not create account session directory: %w", err)
	}
	if info, err := os.Lstat(dir); err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm()&0077 != 0 || !accountOwnedByCurrentUser(info) {
		return errors.New("account session directory must be private")
	}
	if info, err := os.Lstat(path); err == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || !accountOwnedByCurrentUser(info) {
			return errors.New("account session file must be a private regular file")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	data, err := json.Marshal(session)
	if err != nil {
		return err
	}
	temp, err := os.CreateTemp(dir, ".account.json-*")
	if err != nil {
		return fmt.Errorf("could not create account session file: %w", err)
	}
	tempName := temp.Name()
	defer os.Remove(tempName)
	if err := temp.Chmod(0600); err != nil {
		temp.Close()
		return err
	}
	if _, err := temp.Write(data); err != nil {
		temp.Close()
		return err
	}
	if err := temp.Sync(); err != nil {
		temp.Close()
		return err
	}
	if err := temp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tempName, path); err != nil {
		return fmt.Errorf("could not save account session: %w", err)
	}
	return nil
}

func removeAccountSession(path string) error {
	if err := validateAccountSessionParent(path); err != nil {
		return err
	}
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || !accountOwnedByCurrentUser(info) {
		return errors.New("account session file must be a private regular file")
	}
	return os.Remove(path)
}

func validateAccountSessionParent(path string) error {
	dir := filepath.Dir(path)
	info, err := os.Lstat(dir)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm()&0077 != 0 || !accountOwnedByCurrentUser(info) {
		return errors.New("account session directory must be private")
	}
	return nil
}

// accountOwnedByCurrentUser uses reflection so the package remains portable:
// Unix FileInfo values expose a Uid field while Windows values do not.
func accountOwnedByCurrentUser(info os.FileInfo) bool {
	system := info.Sys()
	if system == nil {
		return true
	}
	value := reflect.Indirect(reflect.ValueOf(system))
	uid := value.FieldByName("Uid")
	if !uid.IsValid() {
		return true
	}
	var ownerID string
	switch uid.Kind() {
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		ownerID = strconv.FormatUint(uid.Uint(), 10)
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		ownerID = strconv.FormatInt(uid.Int(), 10)
	default:
		return false
	}
	current, err := user.Current()
	return err == nil && current.Uid != "" && ownerID == current.Uid
}

func printAccountStatus(stdout io.Writer, asJSON bool, status accountStatus) {
	if asJSON {
		printJSON(stdout, map[string]any{
			"signed_in":   status.SignedIn,
			"website_url": status.WebsiteURL,
			"expires_at":  status.ExpiresAt,
			"identity":    status.Identity,
		})
		return
	}
	if status.SignedIn {
		fmt.Fprintf(stdout, "Signed in to %s.\n", status.WebsiteURL)
	} else {
		fmt.Fprintf(stdout, "Not signed in to %s.\n", status.WebsiteURL)
	}
}
