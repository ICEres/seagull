package agentcli

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"
)

type globalOptions struct {
	APIURL      string
	AgentHandle string
	ContextDir  string
	StreamURL   string
	JSON        bool
	ProgramName string
}

const generatedApprovedReplyNote = "generated local agent connector reply approved by explicit draft-reply --approve"

// Version is the connector build version, overridable at build time via
// -ldflags "-X seagull/packages/gulls/connect/local-agent/internal/agentcli.Version=...".
var Version = "dev"

func Main(args []string, stdout io.Writer, stderr io.Writer, env []string, client Client) int {
	return MainWithProgram("gulls", args, stdout, stderr, env, client)
}

func MainWithProgram(programName string, args []string, stdout io.Writer, stderr io.Writer, env []string, client Client) int {
	if programName == "" {
		programName = "gulls"
	}
	code, err := run(programName, args, stdout, stderr, env, client)
	if err == nil {
		return code
	}
	if errors.Is(err, flag.ErrHelp) {
		return 0
	}
	if errors.Is(err, errUsage) {
		fmt.Fprintln(stderr, err)
		return 2
	}
	if errors.Is(err, errConfig) {
		fmt.Fprintln(stderr, err)
		return 2
	}
	fmt.Fprintf(stderr, "%s: %v\n", programName, err)
	return 1
}

var errUsage = errors.New("usage error")

var errConfig = errors.New("config error")

func run(programName string, args []string, stdout io.Writer, stderr io.Writer, env []string, client Client) (int, error) {
	global, remaining, err := parseGlobal(programName, args, stderr)
	if err != nil {
		return 0, err
	}
	if len(remaining) == 0 {
		printUsage(stderr, global.ProgramName)
		return 2, errUsage
	}

	command := remaining[0]
	commandArgs := remaining[1:]
	switch command {
	case "version":
		payload := map[string]any{"program": global.ProgramName, "version": Version}
		printJSONOrText(stdout, global.JSON, payload, global.ProgramName+" version "+Version)
		return 0, nil
	case "whoami":
		config, client, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		result, err := client.GetAgent(config.AgentHandle)
		if err != nil {
			return 0, err
		}
		printJSONOrText(stdout, global.JSON, result, formatAgent(result))
		return 0, nil
	case "inbox":
		fs := commandFlagSet("inbox", stderr)
		limit := fs.Int("limit", 20, "maximum inbox deliveries")
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		if err := validateLimit(*limit); err != nil {
			return 0, err
		}
		config, client, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		result, err := client.GetInbox(config.AgentHandle, *limit)
		if err != nil {
			return 0, err
		}
		printJSONOrText(stdout, global.JSON, result, formatInbox(result))
		return 0, nil
	case "open":
		fs := commandFlagSet("open", stderr)
		limit := fs.Int("limit", 100, "maximum inbox deliveries to search")
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		if fs.NArg() != 1 {
			return 0, usage("open requires delivery_id")
		}
		if err := validateLimit(*limit); err != nil {
			return 0, err
		}
		config, client, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		item, err := requireInboxDelivery(client, config, fs.Arg(0), *limit)
		if err != nil {
			return 0, err
		}
		path, err := WriteDeliveryContext(item, config)
		if err != nil {
			return 0, err
		}
		payload := map[string]any{"context_path": path, "delivery": objectValue(item, "delivery")}
		printJSONOrText(stdout, global.JSON, payload, "Wrote "+path+"\n"+itemSummary(item, 96))
		return 0, nil
	case "thread":
		fs := commandFlagSet("thread", stderr)
		limit := fs.Int("limit", 50, "maximum thread messages")
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		if fs.NArg() != 1 {
			return 0, usage("thread requires thread_id")
		}
		if err := validateLimit(*limit); err != nil {
			return 0, err
		}
		_, client, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		result, err := client.GetThread(fs.Arg(0), *limit)
		if err != nil {
			return 0, err
		}
		printJSONOrText(stdout, global.JSON, result, formatThread(result))
		return 0, nil
	case "context":
		fs := commandFlagSet("context", stderr)
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		if fs.NArg() != 1 {
			return 0, usage("context requires thread_id")
		}
		config, client, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		result, err := client.GetThreadContext(fs.Arg(0), config.AgentHandle)
		if err != nil {
			return 0, err
		}
		printJSONOrText(stdout, global.JSON, result, mustJSON(result))
		return 0, nil
	case "draft-reply":
		fs := commandFlagSet("draft-reply", stderr)
		limit := fs.Int("limit", 100, "maximum inbox deliveries to search")
		approve := fs.Bool("approve", false, "send a generated draft through the delivery decision flow; ask-human/no-reply outcomes are never sent")
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		if fs.NArg() != 1 {
			return 0, usage("draft-reply requires delivery_id")
		}
		if err := validateLimit(*limit); err != nil {
			return 0, err
		}
		config, client, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		item, err := requireInboxDelivery(client, config, fs.Arg(0), *limit)
		if err != nil {
			return 0, err
		}
		var threadContext map[string]any
		if threadID := itemThreadID(item); threadID != "" {
			threadContext, err = client.GetThreadContext(threadID, config.AgentHandle)
			if err != nil {
				return 0, err
			}
		}
		agentProfile, err := client.GetAgent(config.AgentHandle)
		if err != nil {
			return 0, err
		}
		result := GenerateDraftReply(ResolveProfileResponseRules(agentProfile, config.ResponseRule), item, threadContext)
		payload := result.ToMap()
		payload["delivery_id"] = fs.Arg(0)
		payload["draft_sent"] = false
		payload["delivery_decision_submitted"] = false
		if *approve && result.Draft != "" {
			decision, err := client.DecideDelivery(fs.Arg(0), config.AgentHandle, "reply", result.Draft, generatedApprovedReplyNote)
			if err != nil {
				return 0, err
			}
			payload["draft_sent"] = true
			payload["delivery_decision_submitted"] = true
			payload["delivery_decision"] = decision
			printJSONOrText(stdout, global.JSON, payload, formatApprovedDraftResult(result, decision))
			return 0, nil
		}
		printJSONOrText(stdout, global.JSON, payload, formatDraftResult(result))
		return 0, nil
	case "reply":
		fs := commandFlagSet("reply", stderr)
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		if fs.NArg() < 2 {
			return 0, usage("reply requires delivery_id and content")
		}
		config, client, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		result, err := client.DecideDelivery(fs.Arg(0), config.AgentHandle, "reply", strings.Join(fs.Args()[1:], " "), "manual local agent connector reply")
		if err != nil {
			return 0, err
		}
		printJSONOrText(stdout, global.JSON, result, formatDecision(result, "Replied"))
		return 0, nil
	case "ack":
		fs := commandFlagSet("ack", stderr)
		limit := fs.Int("limit", 100, "maximum inbox deliveries to search")
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		if fs.NArg() != 1 {
			return 0, usage("ack requires delivery_id")
		}
		if err := validateLimit(*limit); err != nil {
			return 0, err
		}
		config, client, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		item, err := requireInboxDelivery(client, config, fs.Arg(0), *limit)
		if err != nil {
			return 0, err
		}
		messageID := itemMessageID(item)
		if messageID == "" {
			return 0, fmt.Errorf("delivery has no message_id: %s", fs.Arg(0))
		}
		result, err := client.AckMessage(messageID, config.AgentHandle)
		if err != nil {
			return 0, err
		}
		printJSONOrText(stdout, global.JSON, result, "Acknowledged "+messageID+".")
		return 0, nil
	case "ignore":
		fs := commandFlagSet("ignore", stderr)
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		if fs.NArg() != 1 {
			return 0, usage("ignore requires delivery_id")
		}
		config, client, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		result, err := client.DecideDelivery(fs.Arg(0), config.AgentHandle, "ignore", "", "manual local agent connector ignore")
		if err != nil {
			return 0, err
		}
		printJSONOrText(stdout, global.JSON, result, formatDecision(result, "Ignored"))
		return 0, nil
	case "post":
		fs := commandFlagSet("post", stderr)
		recipients := stringList{}
		fs.Var(&recipients, "to", "recipient handle")
		threadID := fs.String("thread-id", "", "thread id")
		intent := fs.String("intent", "message", "message intent")
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		if len(recipients) == 0 {
			return 0, usage("post requires --to")
		}
		if fs.NArg() < 1 {
			return 0, usage("post requires content")
		}
		config, client, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		result, err := client.SendMessage(config.AgentHandle, recipients, strings.Join(fs.Args(), " "), *threadID, *intent, "direct")
		if err != nil {
			return 0, err
		}
		printJSONOrText(stdout, global.JSON, result, fmt.Sprintf("Sent %v in %v.", result["message_id"], result["thread_id"]))
		return 0, nil
	case "route":
		if len(commandArgs) == 0 {
			return 0, usage("route requires subcommand: add")
		}
		switch commandArgs[0] {
		case "add":
			fs := commandFlagSet("route add", stderr)
			routeTo := stringList{}
			urlContains := stringList{}
			name := fs.String("name", "", "routing rule name")
			mode := fs.String("mode", "copy", "routing mode: direct, copy, handoff, review, or block")
			fs.Var(&routeTo, "to", "agent handle to route to")
			fs.Var(&urlContains, "url-contains", "case-insensitive URL substring to match")
			if err := parseCommand(fs, commandArgs[1:]); err != nil {
				return 0, err
			}
			if strings.TrimSpace(*name) == "" {
				return 0, usage("route add requires --name")
			}
			normalizedMode := strings.ToLower(strings.TrimSpace(*mode))
			if normalizedMode == "" {
				return 0, usage("route add requires --mode")
			}
			if len(urlContains) == 0 {
				return 0, usage("route add requires --url-contains")
			}
			if normalizedMode == "block" {
				if len(routeTo) != 0 {
					return 0, usage("route add with --mode block does not use --to")
				}
			} else if len(routeTo) == 0 {
				return 0, usage("route add requires --to unless --mode block")
			}
			_, client, err := loadRuntime(global, env, client, nil)
			if err != nil {
				return 0, err
			}
			result, err := client.CreateRoutingRule(strings.TrimSpace(*name), routeTo, normalizedMode, urlContains)
			if err != nil {
				return 0, err
			}
			printJSONOrText(stdout, global.JSON, result, formatRoutingRule(result))
			return 0, nil
		default:
			return 0, fmt.Errorf("unknown route subcommand: %s", commandArgs[0])
		}
	case "watch":
		fs := commandFlagSet("watch", stderr)
		limit := fs.Int("limit", 20, "maximum inbox deliveries")
		interval := fs.Float64("interval", 0, "poll interval seconds")
		notify := fs.Bool("notify", false, "show desktop notifications")
		once := fs.Bool("once", false, "run a single poll")
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		if err := validateLimit(*limit); err != nil {
			return 0, err
		}
		var intervalOverride *float64
		if *interval != 0 {
			intervalOverride = interval
		}
		config, client, err := loadRuntime(global, env, client, intervalOverride)
		if err != nil {
			return 0, err
		}
		if *once {
			result, err := PollOnce(client, config, *limit, *notify, nil)
			if err != nil {
				return 0, err
			}
			payload := map[string]any{"new_count": len(result.NewItems), "context_paths": result.ContextPaths}
			if global.JSON {
				printJSON(stdout, payload)
			} else if len(result.NewItems) > 0 {
				fmt.Fprintf(stdout, "%d new delivery item(s).\n", len(result.NewItems))
				for _, path := range result.ContextPaths {
					fmt.Fprintln(stdout, "Wrote "+path)
				}
			} else {
				fmt.Fprintln(stdout, "No new deliveries.")
			}
			return 0, nil
		}
		if config.StreamURL != "" {
			fmt.Fprintf(stdout, "Watching %s via stream %s (fallback poll every %gs).\n", config.AgentHandle, config.StreamURL, config.PollInterval.Seconds())
			ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			return 0, WatchLoopStreaming(ctx, client, config, *limit, *notify, nil, stdout)
		}
		fmt.Fprintf(stdout, "Watching %s every %gs.\n", config.AgentHandle, config.PollInterval.Seconds())
		return 0, WatchLoop(client, config, *limit, *notify, nil)
	case "stream":
		fs := commandFlagSet("stream", stderr)
		if err := parseCommand(fs, commandArgs); err != nil {
			return 0, err
		}
		config, _, err := loadRuntime(global, env, client, nil)
		if err != nil {
			return 0, err
		}
		if config.StreamURL == "" {
			return 0, fmt.Errorf("%w: missing required config: SEAGULL_STREAM_URL", errConfig)
		}
		return 0, runStreamCommand(config, global.JSON, stdout)
	default:
		return 0, fmt.Errorf("unknown command: %s", command)
	}
}

func parseGlobal(programName string, args []string, stderr io.Writer) (globalOptions, []string, error) {
	if programName == "" {
		programName = "gulls"
	}
	opts := globalOptions{ProgramName: programName}
	fs := flag.NewFlagSet(opts.ProgramName, flag.ContinueOnError)
	fs.SetOutput(stderr)
	fs.StringVar(&opts.APIURL, "api-url", "", "Seagull Message Hub URL. Defaults to SEAGULL_API_URL.")
	fs.StringVar(&opts.AgentHandle, "agent-handle", "", "Local agent handle. Defaults to SEAGULL_AGENT_HANDLE.")
	fs.StringVar(&opts.ContextDir, "context-dir", "", "Context handoff directory. Defaults to SEAGULL_AGENT_CONTEXT_DIR or .seagull/agent.")
	fs.StringVar(&opts.StreamURL, "stream-url", "", "WebSocket stream URL (ws:// or wss://). Defaults to SEAGULL_STREAM_URL.")
	fs.BoolVar(&opts.JSON, "json", false, "Print raw JSON where supported.")
	if err := fs.Parse(args); err != nil {
		return opts, nil, err
	}
	return opts, fs.Args(), nil
}

func loadRuntime(global globalOptions, env []string, client Client, interval *float64) (Config, Client, error) {
	config, err := LoadConfig(env, ConfigOverrides{
		APIURL:              global.APIURL,
		AgentHandle:         global.AgentHandle,
		ContextDir:          global.ContextDir,
		StreamURL:           global.StreamURL,
		PollIntervalSeconds: interval,
	})
	if err != nil {
		return Config{}, nil, fmt.Errorf("%w: %w", errConfig, err)
	}
	if client == nil {
		client = NewHTTPClient(config.APIURL, config.Token)
	}
	return config, client, nil
}

func commandFlagSet(name string, stderr io.Writer) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(stderr)
	return fs
}

func parseCommand(fs *flag.FlagSet, args []string) error {
	if err := fs.Parse(args); err != nil {
		return err
	}
	return nil
}

func requireInboxDelivery(client Client, config Config, deliveryID string, limit int) (map[string]any, error) {
	inbox, err := client.GetInbox(config.AgentHandle, limit)
	if err != nil {
		return nil, err
	}
	item := findInboxItem(inboxItems(inbox), deliveryID)
	if item == nil {
		return nil, fmt.Errorf("delivery not found in inbox: %s", deliveryID)
	}
	return item, nil
}

func formatAgent(result map[string]any) string {
	agent := result
	if nested := objectValue(result, "agent"); nested != nil {
		agent = nested
	}
	handle := firstClean(stringValue(agent, "handle"), "unknown")
	status := firstClean(stringValue(agent, "status"), "unknown")
	triggerMode := firstClean(stringValue(agent, "trigger_mode"), "manual")
	return fmt.Sprintf("%s [%s], trigger_mode=%s", handle, status, triggerMode)
}

func formatInbox(result map[string]any) string {
	items := inboxItems(result)
	if len(items) == 0 {
		return "Inbox is empty."
	}
	lines := []string{fmt.Sprintf("%d inbox item(s):", len(items))}
	for _, item := range items {
		lines = append(lines, "- "+itemSummary(item, 96))
	}
	return strings.Join(lines, "\n")
}

func formatThread(result map[string]any) string {
	rawMessages, ok := result["messages"].([]any)
	if !ok || len(rawMessages) == 0 {
		return "Thread has no messages."
	}
	lines := []string{fmt.Sprintf("%d message(s):", len(rawMessages))}
	for _, raw := range rawMessages {
		message, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		messageID := firstClean(stringValue(message, "message_id"), "unknown")
		sender := firstClean(stringValue(message, "sender_handle"), stringValue(message, "sender_agent_id"), "unknown")
		content := compactText(stringValue(message, "content_inline"))
		if content == "" {
			content = "(no inline content)"
		}
		lines = append(lines, fmt.Sprintf("- %s from %s: %s", messageID, sender, content))
	}
	return strings.Join(lines, "\n")
}

func formatDecision(result map[string]any, verb string) string {
	delivery := objectValue(result, "delivery")
	deliveryID := firstClean(stringValue(delivery, "delivery_id"), "unknown")
	status := firstClean(stringValue(delivery, "status"), "unknown")
	if reply := objectValue(result, "reply"); reply != nil {
		return fmt.Sprintf("%s %s; status=%s; reply=%s.", verb, deliveryID, status, stringValue(reply, "message_id"))
	}
	return fmt.Sprintf("%s %s; status=%s.", verb, deliveryID, status)
}

func formatRoutingRule(result map[string]any) string {
	rule := objectValue(result, "routing_rule")
	ruleID := firstClean(stringValue(rule, "rule_id"), "unknown")
	name := firstClean(stringValue(rule, "name"), "unnamed")
	mode := firstClean(stringValue(rule, "mode"), "copy")
	routeTo := strings.Join(stringSliceValue(rule, "route_to_handles"), ", ")
	matches := strings.Join(stringSliceValue(rule, "url_contains"), ", ")
	if routeTo == "" {
		routeTo = "(none)"
	}
	if matches == "" {
		matches = "(no URL filters)"
	}
	return fmt.Sprintf("Created routing rule %s: %s; mode=%s; to=%s; url_contains=%s.", ruleID, name, mode, routeTo, matches)
}

func formatDraftResult(result DraftResult) string {
	rules := result.AppliedRules
	lines := []string{
		"Outcome: " + result.Outcome,
		"Reason: " + result.Reason,
		fmt.Sprintf(
			"Rules: source=%v; schema_version=%v; reply_posture=%v; max_reply_chars=%v",
			rules["source"],
			rules["schema_version"],
			rules["reply_posture"],
			rules["max_reply_chars"],
		),
	}
	if len(result.TriggerLabels) > 0 {
		lines = append(lines, "Triggers: "+strings.Join(result.TriggerLabels, ", "))
	}
	if result.Draft == "" {
		lines = append(lines, "", "No draft generated. No reply sent.")
	} else {
		lines = append(lines, "", "Draft (not sent):", result.Draft)
	}
	lines = append(lines, "No delivery decision was submitted.")
	return strings.Join(lines, "\n")
}

func formatApprovedDraftResult(result DraftResult, decision map[string]any) string {
	lines := strings.Split(formatDraftResult(result), "\n")
	for index, line := range lines {
		if line == "Draft (not sent):" {
			lines[index] = "Draft (approved and sent):"
			break
		}
	}
	if len(lines) > 0 && lines[len(lines)-1] == "No delivery decision was submitted." {
		lines[len(lines)-1] = "Delivery decision submitted after explicit --approve."
	}
	lines = append(lines, "", formatDecision(decision, "Replied"))
	return strings.Join(lines, "\n")
}

// runStreamCommand runs the long-lived, state-free stream subscription:
// one NDJSON line per lifecycle change or received event (with --json), or
// human one-liners otherwise. It never writes the seen-delivery store or
// context files — consumers (like the Gulls macOS app) treat each event as a
// wake-up and fetch the inbox through their own pull path. Exits cleanly on
// SIGINT/SIGTERM; exits with a runtime error if the very first connect is
// rejected (bad URL or token missing the agent:inbox scope).
func runStreamCommand(config Config, asJSON bool, stdout io.Writer) error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	err := RunStream(ctx, config.StreamURL, config.Token, StreamCallbacks{
		OnConnect: func() {
			printStreamLine(stdout, asJSON, streamConnectedLine(config.StreamURL), "Stream connected: "+config.StreamURL)
		},
		OnEvent: func(raw []byte) {
			line := streamEventLine(raw)
			printStreamLine(stdout, asJSON, line, "Event: "+fmt.Sprintf("%v delivery=%v", line["event_type"], line["delivery_id"]))
		},
		OnDrop: func(dropErr error) {
			printStreamLine(stdout, asJSON, streamDisconnectedLine(dropErr), fmt.Sprintf("Stream disconnected: %v", dropErr))
		},
	})
	if err != nil && isStreamAuthError(err) {
		return fmt.Errorf("stream connect rejected (check that the connector token has the agent:inbox scope): %w", err)
	}
	return err
}

func streamConnectedLine(streamURL string) map[string]any {
	return map[string]any{"type": "stream.connected", "url": streamURL}
}

// streamEventLine builds the NDJSON line for a received event. The payload is
// only a wake-up signal, so parse failures degrade to event_type "unknown"
// rather than erroring.
func streamEventLine(raw []byte) map[string]any {
	line := map[string]any{"type": "stream.event", "event_type": "unknown"}
	var event map[string]any
	if err := json.Unmarshal(raw, &event); err != nil {
		return line
	}
	if eventType, ok := event["type"].(string); ok && eventType != "" {
		line["event_type"] = eventType
	}
	if data, ok := event["data"].(map[string]any); ok {
		for _, key := range []string{"delivery_id", "message_id", "thread_id"} {
			if value, ok := data[key].(string); ok && value != "" {
				line[key] = value
			}
		}
	}
	return line
}

func streamDisconnectedLine(err error) map[string]any {
	message := ""
	if err != nil {
		message = err.Error()
	}
	return map[string]any{"type": "stream.disconnected", "error": message}
}

// printStreamLine emits one compact NDJSON line (not indented like the other
// commands: consumers read line-by-line).
func printStreamLine(stdout io.Writer, asJSON bool, line map[string]any, text string) {
	if asJSON {
		payload, _ := json.Marshal(line)
		fmt.Fprintln(stdout, string(payload))
		return
	}
	fmt.Fprintln(stdout, text)
}

func printJSONOrText(stdout io.Writer, asJSON bool, result map[string]any, text string) {
	if asJSON {
		printJSON(stdout, result)
		return
	}
	fmt.Fprintln(stdout, text)
}

func printJSON(stdout io.Writer, result map[string]any) {
	payload, _ := json.MarshalIndent(result, "", "  ")
	fmt.Fprintln(stdout, string(payload))
}

func mustJSON(result map[string]any) string {
	payload, _ := json.MarshalIndent(result, "", "  ")
	return string(payload)
}

func validateLimit(limit int) error {
	if limit < 1 || limit > 100 {
		return usage("limit must be between 1 and 100")
	}
	return nil
}

func usage(message string) error {
	return fmt.Errorf("%w: %s", errUsage, message)
}

func printUsage(out io.Writer, programName string) {
	if programName == "" {
		programName = "gulls"
	}
	fmt.Fprintf(out, "usage: %s [--api-url URL] [--agent-handle HANDLE] [--context-dir DIR] [--json] <command> [args]\n", programName)
}

type stringList []string

func (s *stringList) String() string {
	return strings.Join(*s, ",")
}

func (s *stringList) Set(value string) error {
	value = strings.TrimSpace(value)
	if value == "" {
		return errors.New("value must be non-empty")
	}
	*s = append(*s, value)
	return nil
}
