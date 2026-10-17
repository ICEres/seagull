package agentcli

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	APIURL       string
	SocialAPIURL string
	NodeID       string
	AgentHandle  string
	Token        string
	ContextDir   string
	StreamURL    string
	PollInterval time.Duration
	ResponseRule ResponseRuleResolution
}

type ConfigOverrides struct {
	APIURL              string
	AgentHandle         string
	ContextDir          string
	StreamURL           string
	PollIntervalSeconds *float64
}

func LoadConfig(envList []string, overrides ConfigOverrides) (Config, error) {
	env := envMap(envList)
	fileEnv, err := loadEnvFile(configFilePath(env))
	if err != nil {
		return Config{}, err
	}

	apiURL := firstClean(overrides.APIURL, envValue(env, fileEnv, "SEAGULL_API_URL"))
	socialAPIURL := envValue(env, fileEnv, "SEAGULL_SOCIAL_API_URL")
	nodeID := envValue(env, fileEnv, "SEAGULL_NODE_ID")
	agentHandle := firstClean(overrides.AgentHandle, envValue(env, fileEnv, "SEAGULL_AGENT_HANDLE"))
	contextDir := firstClean(overrides.ContextDir, envValue(env, fileEnv, "SEAGULL_AGENT_CONTEXT_DIR"))
	streamURL := firstClean(overrides.StreamURL, envValue(env, fileEnv, "SEAGULL_STREAM_URL"))
	if streamURL != "" {
		if err := ValidateStreamURL(streamURL); err != nil {
			return Config{}, err
		}
	}

	missing := []string{}
	if apiURL == "" {
		missing = append(missing, "SEAGULL_API_URL")
	}
	if agentHandle == "" {
		missing = append(missing, "SEAGULL_AGENT_HANDLE")
	}
	if len(missing) > 0 {
		return Config{}, fmt.Errorf("missing required config: %s", strings.Join(missing, ", "))
	}

	intervalSeconds := 15.0
	if raw := envValue(env, fileEnv, "SEAGULL_AGENT_POLL_INTERVAL"); raw != "" {
		parsed, err := strconv.ParseFloat(raw, 64)
		if err != nil {
			return Config{}, errors.New("SEAGULL_AGENT_POLL_INTERVAL must be a number")
		}
		intervalSeconds = parsed
	}
	if overrides.PollIntervalSeconds != nil {
		intervalSeconds = *overrides.PollIntervalSeconds
	}
	if intervalSeconds <= 0 {
		return Config{}, errors.New("SEAGULL_AGENT_POLL_INTERVAL must be positive")
	}

	if contextDir == "" {
		contextDir = ".seagull/agent"
	}
	contextDir = expandHome(contextDir)

	token := envValue(env, fileEnv, "SEAGULL_CONNECTOR_TOKEN")
	if token != "" {
		if err := validateSecureURL(apiURL); err != nil {
			return Config{}, fmt.Errorf("SEAGULL_API_URL: %w", err)
		}
		if socialAPIURL != "" {
			if err := validateSecureURL(socialAPIURL); err != nil {
				return Config{}, fmt.Errorf("SEAGULL_SOCIAL_API_URL: %w", err)
			}
		}
	}

	responseRules := ResolveConnectorResponseRules(
		envValue(env, fileEnv, "SEAGULL_RESPONSE_RULES_FILE"),
		envValue(env, fileEnv, "SEAGULL_RESPONSE_RULES_JSON"),
	)

	return Config{
		APIURL:       strings.TrimRight(apiURL, "/"),
		SocialAPIURL: strings.TrimRight(socialAPIURL, "/"),
		NodeID:       nodeID,
		AgentHandle:  agentHandle,
		Token:        token,
		ContextDir:   contextDir,
		StreamURL:    streamURL,
		PollInterval: time.Duration(intervalSeconds * float64(time.Second)),
		ResponseRule: responseRules,
	}, nil
}

func envMap(envList []string) map[string]string {
	values := map[string]string{}
	for _, item := range envList {
		name, value, ok := strings.Cut(item, "=")
		if ok && name != "" {
			values[name] = value
		}
	}
	return values
}

func configFilePath(env map[string]string) string {
	// Only load config from an explicitly configured path or the fixed per-user
	// path. Auto-discovering ".seagull/agent/env" from the current working
	// directory would let an untrusted directory (e.g. a cloned repo) redirect
	// SEAGULL_API_URL and exfiltrate the connector token, or inject response
	// rules and a context dir. The install wrapper sets SEAGULL_AGENT_ENV_FILE to
	// the trusted repo path explicitly.
	if explicit := cleanString(env["SEAGULL_AGENT_ENV_FILE"]); explicit != "" {
		return expandHome(explicit)
	}

	user := expandHome("~/.config/seagull/env")
	if _, err := os.Stat(user); err == nil {
		return user
	}

	return ""
}

func loadEnvFile(path string) (map[string]string, error) {
	values := map[string]string{}
	if path == "" {
		return values, nil
	}
	bytes, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return values, nil
		}
		return values, err
	}
	for _, rawLine := range strings.Split(string(bytes), "\n") {
		line := strings.TrimSpace(rawLine)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimSpace(strings.TrimPrefix(line, "export "))
		name, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		name = strings.TrimSpace(name)
		if name == "" {
			continue
		}
		values[name] = unquoteEnvValue(strings.TrimSpace(value))
	}
	return values, nil
}

func envValue(env map[string]string, fileEnv map[string]string, name string) string {
	if value := cleanString(env[name]); value != "" {
		return value
	}
	return cleanString(fileEnv[name])
}

func firstClean(values ...string) string {
	for _, value := range values {
		if cleaned := cleanString(value); cleaned != "" {
			return cleaned
		}
	}
	return ""
}

func cleanString(value string) string {
	return strings.TrimSpace(value)
}

func unquoteEnvValue(value string) string {
	if len(value) >= 2 {
		first := value[0]
		last := value[len(value)-1]
		if first == last && (first == '\'' || first == '"') {
			return value[1 : len(value)-1]
		}
	}
	return value
}

func expandHome(path string) string {
	if path == "~" {
		if home, err := os.UserHomeDir(); err == nil {
			return home
		}
	}
	if strings.HasPrefix(path, "~/") {
		if home, err := os.UserHomeDir(); err == nil {
			return filepath.Join(home, path[2:])
		}
	}
	return path
}
