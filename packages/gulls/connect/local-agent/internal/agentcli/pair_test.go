package agentcli

import (
	"bytes"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPairLocalConnectionWritesSecretFree0600Config(t *testing.T) {
	oldClient := http.DefaultClient
	t.Cleanup(func() { http.DefaultClient = oldClient })
	var requestPath string
	http.DefaultClient = &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		requestPath = request.URL.Path
		return jsonResponse(http.StatusOK, `{"api_url":"https://fishing.gulls.ai","social_api_url":"https://api.gulls.ai","agent_handle":"@codex:gulls.ai","node_id":"node_1","token":"sga_secret_runtime","token_id":"token_1"}`), nil
	})}

	envPath := filepath.Join(t.TempDir(), "env")
	result, err := PairLocalConnection(
		"https://api.gulls.ai",
		"pair_short_lived",
		false,
		[]string{"SEAGULL_AGENT_ENV_FILE=" + envPath},
	)
	if err != nil {
		t.Fatal(err)
	}
	if requestPath != "/local-connections/pair" {
		t.Fatalf("request path = %q", requestPath)
	}
	if result.AgentHandle != "@codex:gulls.ai" || result.NodeID != "node_1" || result.ConfigPath != envPath {
		t.Fatalf("unexpected result: %#v", result)
	}
	info, err := os.Stat(envPath)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("config mode = %o, want 600", info.Mode().Perm())
	}
	contents, err := os.ReadFile(envPath)
	if err != nil {
		t.Fatal(err)
	}
	text := string(contents)
	for _, expected := range []string{
		`SEAGULL_API_URL="https://fishing.gulls.ai"`,
		`SEAGULL_SOCIAL_API_URL="https://api.gulls.ai"`,
		`SEAGULL_AGENT_HANDLE="@codex:gulls.ai"`,
		`SEAGULL_NODE_ID="node_1"`,
		`SEAGULL_CONNECTOR_TOKEN="sga_secret_runtime"`,
	} {
		if !strings.Contains(text, expected) {
			t.Fatalf("config missing %q: %s", expected, text)
		}
	}
}

func TestPairLocalConnectionDoesNotOverwriteDifferentAgent(t *testing.T) {
	oldClient := http.DefaultClient
	t.Cleanup(func() { http.DefaultClient = oldClient })
	requestCalled := false
	http.DefaultClient = &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		requestCalled = true
		return jsonResponse(http.StatusOK, `{"api_url":"https://fishing.gulls.ai","social_api_url":"https://api.gulls.ai","agent_handle":"@new:gulls.ai","node_id":"node_2","token":"sga_new"}`), nil
	})}

	envPath := filepath.Join(t.TempDir(), "env")
	if err := os.WriteFile(envPath, []byte("SEAGULL_AGENT_HANDLE=\"@old:gulls.ai\"\nSEAGULL_CONNECTOR_TOKEN=\"sga_old\"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	_, err := PairLocalConnection("https://api.gulls.ai", "pair_short_lived", false, []string{"SEAGULL_AGENT_ENV_FILE=" + envPath})
	if err == nil || !strings.Contains(err.Error(), "already configured") {
		t.Fatalf("error = %v", err)
	}
	if requestCalled {
		t.Fatal("pair request was sent before the overwrite guard")
	}
	contents, readErr := os.ReadFile(envPath)
	if readErr != nil {
		t.Fatal(readErr)
	}
	if !strings.Contains(string(contents), "@old:gulls.ai") || strings.Contains(string(contents), "sga_new") {
		t.Fatalf("existing config changed: %s", contents)
	}
}

func TestPairLocalConnectionRejectsNonLoopbackHTTP(t *testing.T) {
	_, err := PairLocalConnection("http://api.gulls.ai", "pair_short_lived", false, nil)
	if err == nil || !strings.Contains(err.Error(), "must use HTTPS") {
		t.Fatalf("error = %v", err)
	}
}

func TestPairLocalConnectionRequiresTokenID(t *testing.T) {
	oldClient := http.DefaultClient
	t.Cleanup(func() { http.DefaultClient = oldClient })
	http.DefaultClient = &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return jsonResponse(http.StatusOK, `{"api_url":"https://fishing.gulls.ai","social_api_url":"https://api.gulls.ai","agent_handle":"@codex:gulls.ai","node_id":"node_1","token":"sga_runtime"}`), nil
	})}

	_, err := PairLocalConnection(
		"https://api.gulls.ai",
		"pair_short_lived",
		false,
		[]string{"SEAGULL_AGENT_ENV_FILE=" + filepath.Join(t.TempDir(), "env")},
	)
	if err == nil || !strings.Contains(err.Error(), "token_id") {
		t.Fatalf("error = %v, want missing token_id", err)
	}
}

func TestPairLocalConnectionDoesNotDumpErrorBody(t *testing.T) {
	oldClient := http.DefaultClient
	t.Cleanup(func() { http.DefaultClient = oldClient })
	http.DefaultClient = &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return jsonResponse(http.StatusBadRequest, `{"error":"sga_runtime_secret pair_short_lived"}`), nil
	})}

	_, err := PairLocalConnection(
		"https://api.gulls.ai",
		"pair_short_lived",
		false,
		[]string{"SEAGULL_AGENT_ENV_FILE=" + filepath.Join(t.TempDir(), "env")},
	)
	if err == nil {
		t.Fatal("expected pair rejection")
	}
	if strings.Contains(err.Error(), "sga_runtime_secret") || strings.Contains(err.Error(), "pair_short_lived") {
		t.Fatalf("error leaked response secret: %v", err)
	}
}

func TestPairLocalConnectionChecksEffectiveEnvironmentToken(t *testing.T) {
	oldClient := http.DefaultClient
	t.Cleanup(func() { http.DefaultClient = oldClient })
	requestCalled := false
	http.DefaultClient = &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		requestCalled = true
		return jsonResponse(http.StatusOK, `{"api_url":"https://fishing.gulls.ai","social_api_url":"https://api.gulls.ai","agent_handle":"@new:gulls.ai","node_id":"node_2","token":"sga_new","token_id":"token_2"}`), nil
	})}

	_, err := PairLocalConnection(
		"https://api.gulls.ai",
		"pair_short_lived",
		false,
		[]string{
			"SEAGULL_CONNECTOR_TOKEN=sga_existing",
			"SEAGULL_AGENT_ENV_FILE=" + filepath.Join(t.TempDir(), "env"),
		},
	)
	if err == nil || !strings.Contains(err.Error(), "already configured") {
		t.Fatalf("error = %v, want existing-token guard", err)
	}
	if requestCalled {
		t.Fatal("pair request was sent before the effective-token guard")
	}
}

func TestPairCommandNeverPrintsRuntimeToken(t *testing.T) {
	oldClient := http.DefaultClient
	t.Cleanup(func() { http.DefaultClient = oldClient })
	http.DefaultClient = &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return jsonResponse(http.StatusOK, `{"api_url":"https://fishing.gulls.ai","social_api_url":"https://api.gulls.ai","agent_handle":"@codex:gulls.ai","node_id":"node_1","token":"sga_secret_runtime","token_id":"token_1"}`), nil
	})}

	envPath := filepath.Join(t.TempDir(), "env")
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	code := Main([]string{"--json", "pair", "--server", "https://api.gulls.ai", "--token", "pair_short_lived"}, &stdout, &stderr, []string{"SEAGULL_AGENT_ENV_FILE=" + envPath}, nil)
	if code != 0 {
		t.Fatalf("code = %d, stderr = %s", code, stderr.String())
	}
	if strings.Contains(stdout.String(), "sga_secret_runtime") || strings.Contains(stdout.String(), "pair_short_lived") {
		t.Fatalf("secret leaked in output: %s", stdout.String())
	}
}

func jsonResponse(status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Header:     http.Header{"content-type": []string{"application/json"}},
		Body:       io.NopCloser(strings.NewReader(body)),
	}
}
