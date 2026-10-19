package agentcli

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync/atomic"
	"time"
)

type WatchResult struct {
	NewItems     []map[string]any
	ContextPaths []string
}

type Notifier func(title string, body string) bool

type watchInboxClient interface {
	GetWatchInbox(handle string, limit int, seen map[string]bool) (map[string]any, error)
}

func PollOnce(client Client, config Config, limit int, notify bool, notifier Notifier) (WatchResult, error) {
	if notifier == nil {
		notifier = DesktopNotify
	}
	state := SeenDeliveryStore{Path: filepath.Join(config.ContextDir, "seen-deliveries.json")}
	seen := state.Load()
	var inbox map[string]any
	var err error
	if resident, ok := client.(watchInboxClient); ok {
		inbox, err = resident.GetWatchInbox(config.AgentHandle, limit, seen)
	} else {
		inbox, err = getInboxForContext(client, config.AgentHandle, limit)
	}
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

// streamHealthyPollInterval is the stretched fallback cadence while the
// stream is connected: push provides the latency, poll provides the truth.
const streamHealthyPollInterval = 2 * time.Minute

// WatchLoopStreaming is WatchLoop with a WebSocket wake-up source. Every
// stream event (and every reconnect) triggers an immediate PollOnce through
// the exact same path as timed polls; the timer keeps running as a fallback,
// stretched while the stream is healthy. Stream failures never stop the
// watch — it degrades to plain polling.
func WatchLoopStreaming(ctx context.Context, client Client, config Config, limit int, notify bool, notifier Notifier, status io.Writer) error {
	if ctx == nil {
		ctx = context.Background()
	}
	if status == nil {
		status = io.Discard
	}

	wake := NewWakeChannel()
	var healthy atomic.Bool
	go func() {
		err := RunStream(ctx, config.StreamURL, config.Token, StreamCallbacks{
			OnConnect: func() {
				healthy.Store(true)
				fmt.Fprintln(status, "Stream connected.")
				Wake(wake)
			},
			OnEvent: func(raw []byte) {
				Wake(wake)
			},
			OnDrop: func(dropErr error) {
				healthy.Store(false)
				fmt.Fprintf(status, "Stream disconnected: %v\n", dropErr)
			},
		})
		healthy.Store(false)
		if err != nil {
			fmt.Fprintf(status, "Stream stopped: %v (continuing with polling)\n", err)
		}
	}()

	for {
		if _, err := PollOnce(client, config, limit, notify, notifier); err != nil {
			return err
		}
		interval := config.PollInterval
		if healthy.Load() && interval < streamHealthyPollInterval {
			interval = streamHealthyPollInterval
		}
		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil
		case <-wake:
			timer.Stop()
		case <-timer.C:
		}
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
	if err := os.MkdirAll(filepath.Dir(s.Path), 0o700); err != nil {
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
