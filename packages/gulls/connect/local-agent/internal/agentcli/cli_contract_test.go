package agentcli

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

var updateContract = flag.Bool("update", false, "rewrite JSON contract golden fixtures")

// TestJSONContractFixtures pins the --json output of every command the Gulls
// macOS app consumes. The app's Swift decoding tests read the same fixture
// files (testdata/contract/), so a shape change here fails both sides of the
// contract in the same commit. Regenerate with:
//
//	go test ./internal/agentcli -run TestJSONContractFixtures -update
func TestJSONContractFixtures(t *testing.T) {
	rulesEnv := "SEAGULL_RESPONSE_RULES_JSON=" + responseRulesJSON(nil)

	cases := []struct {
		name     string
		args     []string
		extraEnv []string
	}{
		{name: "version", args: []string{"--json", "version"}},
		{name: "whoami", args: []string{"--json", "whoami"}},
		{name: "inbox", args: []string{"--json", "inbox"}},
		{name: "open", args: []string{"--json", "open", "delivery_1"}},
		{name: "draft_reply", args: []string{"--json", "draft-reply", "delivery_1"}, extraEnv: []string{rulesEnv}},
		{name: "draft_reply_approved", args: []string{"--json", "draft-reply", "--approve", "delivery_1"}, extraEnv: []string{rulesEnv}},
		{name: "reply", args: []string{"--json", "reply", "delivery_1", "I can review this today."}},
		{name: "ack", args: []string{"--json", "ack", "delivery_1"}},
		{name: "ignore", args: []string{"--json", "ignore", "delivery_1"}},
		{name: "watch_once", args: []string{"--json", "watch", "--once"}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			tmp := t.TempDir()
			fake := newFakeClient()
			var stdout bytes.Buffer
			var stderr bytes.Buffer
			env := append(testEnv(tmp), tc.extraEnv...)

			code := Main(tc.args, &stdout, &stderr, env, fake)
			if code != 0 {
				t.Fatalf("code = %d, stderr = %s", code, stderr.String())
			}

			got := normalizeContractOutput(stdout.String(), tmp)
			if !json.Valid([]byte(got)) {
				t.Fatalf("output is not valid JSON:\n%s", got)
			}

			fixture := filepath.Join("testdata", "contract", tc.name+".json")
			if *updateContract {
				if err := os.MkdirAll(filepath.Dir(fixture), 0o755); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(fixture, []byte(got), 0o644); err != nil {
					t.Fatal(err)
				}
				return
			}

			want, err := os.ReadFile(fixture)
			if err != nil {
				t.Fatalf("read fixture (run with -update to generate): %v", err)
			}
			if got != string(want) {
				t.Fatalf("JSON contract drift for %s.\nGot:\n%s\nWant:\n%s\nIf intentional, rerun with -update and update the Gulls app models.", tc.name, got, string(want))
			}
		})
	}
}

func normalizeContractOutput(output string, contextDir string) string {
	return strings.ReplaceAll(output, contextDir, "<CONTEXT_DIR>")
}

// TestStreamLineContractFixtures pins the NDJSON lines `gulls stream --json`
// emits. The command is long-lived so the full-command harness can't run it;
// the line builders are pure functions, fixtured directly.
func TestStreamLineContractFixtures(t *testing.T) {
	sampleEvent := []byte(`{"type":"seagull.delivery.created.v1","data":{"delivery_id":"delivery_1","message_id":"message_1","thread_id":"thread_1"}}`)
	cases := []struct {
		name string
		line map[string]any
	}{
		{name: "stream_connected", line: streamConnectedLine("ws://localhost:8200/stream")},
		{name: "stream_event", line: streamEventLine(sampleEvent)},
		{name: "stream_disconnected", line: streamDisconnectedLine(errors.New("read: connection reset"))},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var stdout bytes.Buffer
			printStreamLine(&stdout, true, tc.line, "")
			got := stdout.String()

			fixture := filepath.Join("testdata", "contract", tc.name+".json")
			if *updateContract {
				if err := os.WriteFile(fixture, []byte(got), 0o644); err != nil {
					t.Fatal(err)
				}
				return
			}
			want, err := os.ReadFile(fixture)
			if err != nil {
				t.Fatalf("read fixture (run with -update to generate): %v", err)
			}
			if got != string(want) {
				t.Fatalf("stream line contract drift for %s.\nGot:\n%s\nWant:\n%s", tc.name, got, string(want))
			}
		})
	}
}

func TestStreamEventLineDegradesGracefully(t *testing.T) {
	line := streamEventLine([]byte("not json"))
	if line["type"] != "stream.event" || line["event_type"] != "unknown" {
		t.Fatalf("unexpected line: %#v", line)
	}
}
