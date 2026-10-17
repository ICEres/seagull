package agentcli

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// PairResult is deliberately secret-free. The runtime token returned by the
// Social API is written to the config file but never returned to the caller.
type PairResult struct {
	AgentHandle string
	NodeID      string
	ConfigPath  string
}

type pairResponse struct {
	APIURL       string `json:"api_url"`
	SocialAPIURL string `json:"social_api_url"`
	AgentHandle  string `json:"agent_handle"`
	NodeID       string `json:"node_id"`
	Token        string `json:"token"`
	TokenID      string `json:"token_id"`
}

// PairLocalConnection exchanges a short-lived pairing token for a scoped
// runtime token and stores the resulting local configuration with mode 0600.
func PairLocalConnection(server string, pairingToken string, force bool, envList []string) (PairResult, error) {
	server = strings.TrimRight(strings.TrimSpace(server), "/")
	if err := validatePairServerURL(server); err != nil {
		return PairResult{}, err
	}
	pairingToken = strings.TrimSpace(pairingToken)
	env := envMap(envList)
	path := configFilePath(env)
	if path == "" {
		path = expandHome("~/.config/seagull/env")
	}
	existing, err := loadEnvFile(path)
	if err != nil {
		return PairResult{}, err
	}
	// Pairing consumes the server-side one-time token. Refuse before the
	// network call when a local runtime is already configured, so a missing
	// --force can never burn a valid pairing code without changing local state.
	if existingToken := cleanString(envValue(env, existing, "SEAGULL_CONNECTOR_TOKEN")); existingToken != "" && !force {
		return PairResult{}, errors.New("a paired local runtime is already configured; pass --force to replace it")
	}

	requestBody, err := json.Marshal(map[string]string{"pair_token": pairingToken})
	if err != nil {
		return PairResult{}, err
	}
	requestContext, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(
		requestContext,
		http.MethodPost,
		server+"/local-connections/pair",
		bytes.NewReader(requestBody),
	)
	if err != nil {
		return PairResult{}, err
	}
	request.Header.Set("accept", "application/json")
	request.Header.Set("content-type", "application/json")
	request.Header.Set("user-agent", "seagull/0.1")

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return PairResult{}, fmt.Errorf("pair request failed: %w", err)
	}
	defer response.Body.Close()
	payload, err := io.ReadAll(response.Body)
	if err != nil {
		return PairResult{}, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return PairResult{}, fmt.Errorf("pair request rejected (%d)", response.StatusCode)
	}

	var paired pairResponse
	if err := json.Unmarshal(payload, &paired); err != nil {
		return PairResult{}, fmt.Errorf("pair response was not valid JSON: %w", err)
	}
	if err := validatePairResponse(paired); err != nil {
		return PairResult{}, err
	}

	existing["SEAGULL_API_URL"] = paired.APIURL
	existing["SEAGULL_SOCIAL_API_URL"] = paired.SocialAPIURL
	existing["SEAGULL_AGENT_HANDLE"] = paired.AgentHandle
	existing["SEAGULL_NODE_ID"] = paired.NodeID
	existing["SEAGULL_CONNECTOR_TOKEN"] = paired.Token
	if err := writeEnvFile(path, existing); err != nil {
		return PairResult{}, err
	}

	return PairResult{AgentHandle: paired.AgentHandle, NodeID: paired.NodeID, ConfigPath: path}, nil
}

func validatePairServerURL(raw string) error {
	if err := validateSecureURL(raw); err != nil {
		return errors.New("pair --server must use HTTPS; HTTP is allowed only for loopback development")
	}
	return nil
}

func validateSecureURL(raw string) error {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme == "" || parsed.Hostname() == "" {
		return errors.New("URL must be absolute")
	}
	if parsed.Scheme == "https" {
		return nil
	}
	if parsed.Scheme == "http" && isLoopbackHost(parsed.Hostname()) {
		return nil
	}
	return errors.New("URL must use HTTPS; HTTP is allowed only for loopback development")
}

func isLoopbackHost(host string) bool {
	host = strings.Trim(host, "[]")
	return host == "localhost" || host == "127.0.0.1" || host == "::1"
}

func validatePairResponse(response pairResponse) error {
	missing := []string{}
	if strings.TrimSpace(response.APIURL) == "" {
		missing = append(missing, "api_url")
	}
	if strings.TrimSpace(response.SocialAPIURL) == "" {
		missing = append(missing, "social_api_url")
	}
	if strings.TrimSpace(response.AgentHandle) == "" {
		missing = append(missing, "agent_handle")
	}
	if strings.TrimSpace(response.NodeID) == "" {
		missing = append(missing, "node_id")
	}
	if strings.TrimSpace(response.Token) == "" {
		missing = append(missing, "token")
	} else if !strings.HasPrefix(strings.TrimSpace(response.Token), "sga_") {
		return errors.New("pair response token is not an sga_ runtime token")
	}
	if strings.TrimSpace(response.TokenID) == "" {
		missing = append(missing, "token_id")
	}
	if len(missing) > 0 {
		return fmt.Errorf("pair response missing required fields: %s", strings.Join(missing, ", "))
	}
	for name, endpoint := range map[string]string{"api_url": response.APIURL, "social_api_url": response.SocialAPIURL} {
		if err := validatePairServerURL(strings.TrimRight(strings.TrimSpace(endpoint), "/")); err != nil {
			return fmt.Errorf("pair response %s is not a secure endpoint: %w", name, err)
		}
	}
	return nil
}

func writeEnvFile(path string, values map[string]string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	lines := []string{
		"SEAGULL_API_URL=" + shellEnvValue(values["SEAGULL_API_URL"]),
		"SEAGULL_SOCIAL_API_URL=" + shellEnvValue(values["SEAGULL_SOCIAL_API_URL"]),
		"SEAGULL_AGENT_HANDLE=" + shellEnvValue(values["SEAGULL_AGENT_HANDLE"]),
		"SEAGULL_NODE_ID=" + shellEnvValue(values["SEAGULL_NODE_ID"]),
		"SEAGULL_CONNECTOR_TOKEN=" + shellEnvValue(values["SEAGULL_CONNECTOR_TOKEN"]),
	}
	for _, name := range []string{"SEAGULL_AGENT_CONTEXT_DIR", "SEAGULL_STREAM_URL", "SEAGULL_AGENT_POLL_INTERVAL", "SEAGULL_RESPONSE_RULES_FILE", "SEAGULL_RESPONSE_RULES_JSON"} {
		if value := values[name]; value != "" {
			lines = append(lines, name+"="+shellEnvValue(value))
		}
	}
	content := strings.Join(lines, "\n") + "\n"
	temporary, err := os.CreateTemp(filepath.Dir(path), ".seagull-env-*")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.WriteString(content); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return err
	}
	return os.Chmod(path, 0o600)
}

func shellEnvValue(value string) string {
	return `"` + strings.ReplaceAll(strings.ReplaceAll(value, `\`, `\\`), `"`, `\"`) + `"`
}
