package agentcli

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestAccountCallbackValidatesOriginHostStateAndReplay(t *testing.T) {
	state := "state-123"
	received := make(chan verifiedAccountSession, 1)
	done := make(chan struct{})
	var consumed atomic.Bool
	handler := accountCallbackHandler(
		"127.0.0.1:43122", "https://sea.gulls.ai", state, received, done, &consumed,
		func(session accountCallbackSession) (map[string]any, int64, error) {
			return map[string]any{"user_id": "user-1"}, session.ExpiresAt, nil
		},
	)

	request := func(origin, host, callbackState string) *httptest.ResponseRecorder {
		body, _ := json.Marshal(accountCallbackPayload{
			State: callbackState,
			Session: accountCallbackSession{
				AccessToken: "access-token",
				ExpiresAt:   time.Now().Add(time.Minute).UnixMilli(),
				TokenType:   "Bearer",
			},
		})
		req := httptest.NewRequest(http.MethodPost, "http://127.0.0.1:43122/callback", bytes.NewReader(body))
		req.Host = host
		req.Header.Set("Origin", origin)
		req.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		handler(recorder, req)
		return recorder
	}

	if response := request("https://evil.example", "127.0.0.1:43122", state); response.Code != http.StatusForbidden {
		t.Fatalf("origin status = %d", response.Code)
	}
	if response := request("https://sea.gulls.ai", "127.0.0.1:43123", state); response.Code != http.StatusBadRequest {
		t.Fatalf("host status = %d", response.Code)
	}
	if response := request("https://sea.gulls.ai", "127.0.0.1:43122", "wrong"); response.Code != http.StatusBadRequest {
		t.Fatalf("state status = %d", response.Code)
	}
	if response := request("https://sea.gulls.ai", "127.0.0.1:43122", state); response.Code != http.StatusOK {
		t.Fatalf("valid status = %d", response.Code)
	} else if response.Header().Get("Access-Control-Allow-Origin") != "https://sea.gulls.ai" {
		t.Fatal("valid response did not include the exact allowed origin")
	}
	if response := request("https://sea.gulls.ai", "127.0.0.1:43122", state); response.Code != http.StatusGone {
		t.Fatalf("replay status = %d", response.Code)
	}
	select {
	case result := <-received:
		if result.Identity["user_id"] != "user-1" {
			t.Fatalf("identity = %#v", result.Identity)
		}
	default:
		t.Fatal("valid callback was not delivered")
	}
}

func TestAccountSessionIsPrivateAndAtomic(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "nested", "account.json")
	session := accountSession{Version: 1, WebsiteURL: "https://sea.gulls.ai", AccessToken: "secret", ExpiresAt: time.Now().Add(time.Hour).UnixMilli()}
	if err := writeAccountSession(path, session); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("session mode = %o", info.Mode().Perm())
	}
	loaded, err := readAccountSession(path)
	if err != nil || loaded.AccessToken != "secret" {
		t.Fatalf("loaded session = %#v, err=%v", loaded, err)
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := readAccountSession(path); err == nil {
		t.Fatal("expected non-private session to be rejected")
	}
}

func TestAccountCallbackReservesConcurrentExchange(t *testing.T) {
	received := make(chan verifiedAccountSession, 1)
	done := make(chan struct{})
	var consumed atomic.Bool
	started := make(chan struct{})
	release := make(chan struct{})
	var startOnce sync.Once
	handler := accountCallbackHandler(
		"127.0.0.1:43123", "https://sea.gulls.ai", "state", received, done, &consumed,
		func(session accountCallbackSession) (map[string]any, int64, error) {
			startOnce.Do(func() { close(started) })
			<-release
			return map[string]any{"user_id": "user-1"}, session.ExpiresAt, nil
		},
	)

	request := func() *httptest.ResponseRecorder {
		body, _ := json.Marshal(accountCallbackPayload{
			State: "state",
			Session: accountCallbackSession{
				AccessToken: "access-token",
				ExpiresAt:   time.Now().Add(time.Minute).UnixMilli(),
				TokenType:   "Bearer",
			},
		})
		req := httptest.NewRequest(http.MethodPost, "http://127.0.0.1:43123/callback", bytes.NewReader(body))
		req.Host = "127.0.0.1:43123"
		req.Header.Set("Origin", "https://sea.gulls.ai")
		req.Header.Set("Content-Type", "application/json")
		response := httptest.NewRecorder()
		handler(response, req)
		return response
	}

	first := make(chan *httptest.ResponseRecorder, 1)
	go func() { first <- request() }()
	<-started
	second := request()
	if second.Code != http.StatusGone {
		t.Fatalf("concurrent callback status = %d", second.Code)
	}
	close(release)
	if response := <-first; response.Code != http.StatusOK {
		t.Fatalf("first callback status = %d", response.Code)
	}
}

func TestAccountRuntimeConfigParsesTrustedAssignment(t *testing.T) {
	config, err := parseAccountRuntimeConfig([]byte(`window.SEAGULL_CONFIG = {"socialApiUrl":"http://127.0.0.1:8300"};`))
	if err != nil {
		t.Fatal(err)
	}
	if config.SocialAPIURL != "http://127.0.0.1:8300" {
		t.Fatalf("social API URL = %q", config.SocialAPIURL)
	}
	if _, err := parseAccountRuntimeConfig([]byte(`window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test"};`)); err != nil {
		t.Fatal(err)
	}
}

func TestAccountCLILoginStatusAndLogoutEndToEnd(t *testing.T) {
	var socialURL string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/config.js":
			w.Header().Set("Content-Type", "application/javascript")
			_, _ = io.WriteString(w, `window.SEAGULL_CONFIG = {"socialApiUrl":"`+socialURL+`"};`)
		case "/me":
			if r.Header.Get("Authorization") != "Bearer browser-token" {
				http.Error(w, "unauthorized", http.StatusUnauthorized)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(w, `{"identity":{"user_id":"user-1","email":"owner@example.test"}}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	socialURL = server.URL

	oldOpenBrowser := accountOpenBrowser
	defer func() { accountOpenBrowser = oldOpenBrowser }()
	opened := make(chan string, 1)
	accountOpenBrowser = func(target string) error {
		opened <- target
		return nil
	}

	sessionPath := filepath.Join(t.TempDir(), "account.json")
	if err := os.Chmod(filepath.Dir(sessionPath), 0700); err != nil {
		t.Fatal(err)
	}
	type commandResult struct {
		code int
		out  string
		err  string
	}
	result := make(chan commandResult, 1)
	go func() {
		var stdout, stderr bytes.Buffer
		code, runErr := runAccountLogin(
			[]string{"--server", server.URL, "--session-file", sessionPath, "--timeout", "5s"},
			globalOptions{JSON: true, ProgramName: "gulls"}, &stdout, &stderr, nil,
		)
		result <- commandResult{code: code, out: stdout.String(), err: stderr.String() + " / " + fmt.Sprint(runErr)}
	}()

	var openedURL string
	select {
	case openedURL = <-opened:
	case finished := <-result:
		t.Fatalf("login finished before opening browser: code=%d stdout=%q stderr=%q", finished.code, finished.out, finished.err)
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for browser opener")
	}
	parsed, err := url.Parse(openedURL)
	if err != nil {
		t.Fatal(err)
	}
	fragment, err := url.ParseQuery(parsed.Fragment)
	if err != nil {
		t.Fatal(err)
	}
	callbackURL := fragment.Get("callback")
	state := fragment.Get("state")
	if callbackURL == "" || state == "" {
		t.Fatalf("browser URL fragment = %q", parsed.Fragment)
	}

	payload, _ := json.Marshal(accountCallbackPayload{
		State: state,
		Session: accountCallbackSession{
			AccessToken: "browser-token",
			ExpiresAt:   time.Now().Add(time.Minute).UnixMilli(),
			TokenType:   "Bearer",
		},
	})
	callback, err := url.Parse(callbackURL)
	if err != nil {
		t.Fatal(err)
	}
	request, err := http.NewRequest(http.MethodPost, callbackURL, bytes.NewReader(payload))
	if err != nil {
		t.Fatal(err)
	}
	request.Host = callback.Host
	request.Header.Set("Origin", server.URL)
	request.Header.Set("Content-Type", "application/json")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	responseBody, readErr := io.ReadAll(response.Body)
	_ = response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("callback status = %d", response.StatusCode)
	}
	var callbackResult map[string]bool
	if readErr != nil || json.Unmarshal(responseBody, &callbackResult) != nil || !callbackResult["ok"] {
		t.Fatalf("callback response = %q", responseBody)
	}

	login := <-result
	if login.code != 0 {
		t.Fatalf("login code=%d stdout=%q stderr=%q", login.code, login.out, login.err)
	}
	var loginPayload struct {
		Identity map[string]any `json:"identity"`
	}
	if err := json.Unmarshal([]byte(login.out), &loginPayload); err != nil || loginPayload.Identity["user_id"] != "user-1" || bytes.Contains([]byte(login.out), []byte("browser-token")) {
		t.Fatalf("login output leaked or omitted identity: %s", login.out)
	}
	info, err := os.Stat(sessionPath)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("session mode = %o", info.Mode().Perm())
	}

	var statusOut bytes.Buffer
	statusCode, err := runAccountStatus(
		[]string{"--server", server.URL, "--session-file", sessionPath},
		globalOptions{JSON: true, ProgramName: "gulls"}, &statusOut, &bytes.Buffer{}, nil,
	)
	var statusPayload struct {
		SignedIn bool `json:"signed_in"`
	}
	if err != nil || statusCode != 0 || json.Unmarshal(statusOut.Bytes(), &statusPayload) != nil || !statusPayload.SignedIn {
		t.Fatalf("status code=%d err=%v output=%s", statusCode, err, statusOut.String())
	}

	var logoutOut bytes.Buffer
	logoutCode, err := runAccountLogout(
		[]string{"--server", server.URL, "--session-file", sessionPath},
		globalOptions{JSON: true, ProgramName: "gulls"}, &logoutOut, &bytes.Buffer{}, nil,
	)
	if err != nil || logoutCode != 0 {
		t.Fatalf("logout code=%d err=%v output=%s", logoutCode, err, logoutOut.String())
	}
	if _, err := os.Stat(sessionPath); !os.IsNotExist(err) {
		t.Fatalf("session file after logout: %v", err)
	}
}

func TestAccountLogoutRemovesCorruptPrivateSessionButPreservesOtherWebsite(t *testing.T) {
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "account.json")
	if err := os.WriteFile(path, []byte(`{"version":1,"website_url":`), 0600); err != nil {
		t.Fatal(err)
	}
	code, err := runAccountLogout(
		[]string{"--server", "https://sea.gulls.ai", "--session-file", path},
		globalOptions{JSON: true, ProgramName: "gulls"}, &bytes.Buffer{}, &bytes.Buffer{}, nil,
	)
	if err != nil || code != 0 {
		t.Fatalf("corrupt logout code=%d err=%v", code, err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("corrupt session after logout: %v", err)
	}

	if err := writeAccountSession(path, accountSession{
		Version: 1, WebsiteURL: "https://other.example", AccessToken: "other", ExpiresAt: time.Now().Add(time.Hour).UnixMilli(),
	}); err != nil {
		t.Fatal(err)
	}
	code, err = runAccountLogout(
		[]string{"--server", "https://sea.gulls.ai", "--session-file", path},
		globalOptions{JSON: true, ProgramName: "gulls"}, &bytes.Buffer{}, &bytes.Buffer{}, nil,
	)
	if err != nil || code != 0 {
		t.Fatalf("other website logout code=%d err=%v", code, err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("other website session was removed: %v", err)
	}
}

func TestClampJWTExpiryUsesEarlierClaim(t *testing.T) {
	token := "header.eyJleHAiOjEwMH0.signature"
	if got := clampJWTExpiry(token, 200_000); got != 100_000 {
		t.Fatalf("expiry = %d", got)
	}
}
