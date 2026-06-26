package agentcli

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"
)

type WatchResult struct {
	NewItems     []map[string]any
	ContextPaths []string
}

type Notifier func(title string, body string) bool

func PollOnce(client Client, config Config, limit int, notify bool, notifier Notifier) (WatchResult, error) {
	if notifier == nil {
		notifier = DesktopNotify
	}
	state := SeenDeliveryStore{Path: filepath.Join(config.ContextDir, "seen-deliveries.json")}
	seen := state.Load()
	inbox, err := client.GetInbox(config.AgentHandle, limit)
	if err != nil {
		return WatchResult{}, err
	}
	items := inboxItems(inbox)
	newItems := []map[string]any{}
	for i := len(items) - 1; i >= 0; i-- {
		item := items[i]
		deliveryID := itemDeliveryID(item)
		if deliveryID != "" && !seen[deliveryID] {
			newItems = append(newItems, item)
		}
	}

	paths := []string{}
	for _, item := range newItems {
		path, err := WriteDeliveryContext(item, config)
		if err != nil {
			return WatchResult{}, err
		}
		paths = append(paths, path)
		if notify {
			notifier("New Seagull message", itemSummary(item, 96))
		}
	}

	for _, item := range items {
		if deliveryID := itemDeliveryID(item); deliveryID != "" {
			seen[deliveryID] = true
		}
	}
	if err := state.Save(seen); err != nil {
		return WatchResult{}, err
	}
	return WatchResult{NewItems: newItems, ContextPaths: paths}, nil
}

func WatchLoop(client Client, config Config, limit int, notify bool, notifier Notifier) error {
	for {
		if _, err := PollOnce(client, config, limit, notify, notifier); err != nil {
			return err
		}
		time.Sleep(config.PollInterval)
	}
}

type SeenDeliveryStore struct {
	Path string
}

func (s SeenDeliveryStore) Load() map[string]bool {
	seen := map[string]bool{}
	payload, err := os.ReadFile(s.Path)
	if err != nil {
		return seen
	}
	var values []string
	if err := json.Unmarshal(payload, &values); err != nil {
		return seen
	}
	for _, value := range values {
		if value != "" {
			seen[value] = true
		}
	}
	return seen
}

func (s SeenDeliveryStore) Save(seen map[string]bool) error {
	if err := os.MkdirAll(filepath.Dir(s.Path), 0o755); err != nil {
		return err
	}
	values := []string{}
	for value := range seen {
		values = append(values, value)
	}
	sort.Strings(values)
	payload, err := json.MarshalIndent(values, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.Path, append(payload, '\n'), 0o644)
}

func DesktopNotify(title string, body string) bool {
	if runtime.GOOS != "darwin" {
		return false
	}
	if _, err := exec.LookPath("osascript"); err != nil {
		return false
	}
	script := "display notification " + appleScriptString(body) + " with title " + appleScriptString(title)
	return exec.Command("osascript", "-e", script).Run() == nil
}

func appleScriptString(value string) string {
	escaped := strings.ReplaceAll(value, `\`, `\\`)
	escaped = strings.ReplaceAll(escaped, `"`, `\"`)
	return `"` + escaped + `"`
}
