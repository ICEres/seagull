package agentcli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// A ".seagull/agent/env" file in the current working directory must not be
// auto-loaded: an untrusted directory could otherwise redirect SEAGULL_API_URL
// and exfiltrate the connector token. Only an explicit SEAGULL_AGENT_ENV_FILE or
// the fixed per-user path is honored.
func TestConfigFilePathIgnoresCurrentWorkingDirectory(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, ".seagull", "agent"), 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	envPath := filepath.Join(dir, ".seagull", "agent", "env")
	contents := "SEAGULL_API_URL=https://attacker.example\nSEAGULL_CONNECTOR_TOKEN=stolen\n"
	if err := os.WriteFile(envPath, []byte(contents), 0o600); err != nil {
		t.Fatalf("write env: %v", err)
	}

	cwd, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	t.Cleanup(func() { _ = os.Chdir(cwd) })
	if err := os.Chdir(dir); err != nil {
		t.Fatalf("chdir: %v", err)
	}

	if path := configFilePath(map[string]string{}); path != "" {
		t.Fatalf("expected no config file from CWD, got %q", path)
	}
}

func TestConfigFilePathHonorsExplicitEnvFile(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, "env")
	if err := os.WriteFile(envPath, []byte("SEAGULL_API_URL=https://trusted.example\n"), 0o600); err != nil {
		t.Fatalf("write env: %v", err)
	}

	got := configFilePath(map[string]string{"SEAGULL_AGENT_ENV_FILE": envPath})
	if got != envPath {
		t.Fatalf("expected explicit env file %q, got %q", envPath, got)
	}
}

func TestLoadConfigRejectsAuthenticatedPublicHTTPURLs(t *testing.T) {
	_, err := LoadConfig([]string{
		"SEAGULL_API_URL=http://api.example.test",
		"SEAGULL_AGENT_HANDLE=@worker:gulls.ai",
		"SEAGULL_CONNECTOR_TOKEN=sga_runtime",
		"SEAGULL_AGENT_ENV_FILE=" + filepath.Join(t.TempDir(), "missing-env"),
	}, ConfigOverrides{})
	if err == nil || !strings.Contains(err.Error(), "SEAGULL_API_URL") || !strings.Contains(err.Error(), "HTTPS") {
		t.Fatalf("error = %v, want secure API URL rejection", err)
	}
}

func TestLoadConfigAllowsAuthenticatedLoopbackHTTPURLs(t *testing.T) {
	config, err := LoadConfig([]string{
		"SEAGULL_API_URL=http://127.0.0.1:8200",
		"SEAGULL_SOCIAL_API_URL=http://localhost:8300",
		"SEAGULL_AGENT_HANDLE=@worker:gulls.ai",
		"SEAGULL_CONNECTOR_TOKEN=sga_runtime",
		"SEAGULL_AGENT_ENV_FILE=" + filepath.Join(t.TempDir(), "missing-env"),
	}, ConfigOverrides{})
	if err != nil {
		t.Fatal(err)
	}
	if config.APIURL != "http://127.0.0.1:8200" || config.SocialAPIURL != "http://localhost:8300" {
		t.Fatalf("unexpected URLs: %#v", config)
	}
}
