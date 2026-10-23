package agentcli

import (
	"errors"
	"io"
)

func runHistoryCommand(args []string, global globalOptions, stdout, stderr io.Writer, env []string, client Client) (int, error) {
	summary := len(args) > 0 && args[0] == "summary"
	if summary {
		args = args[1:]
	}
	fs := commandFlagSet("history", stderr)
	limit := fs.Int("limit", 50, "maximum saved messages in this page")
	cursor := fs.String("cursor", "", "continue a saved message search")
	query := fs.String("query", "", "search saved sender names and message text")
	status := fs.String("status", "", "filter by delivery status")
	threadID := fs.String("thread-id", "", "filter by thread")
	days := fs.Int("days", 7, "number of UTC days in the activity summary")
	if err := parseCommand(fs, args); err != nil {
		return 0, err
	}
	if fs.NArg() != 0 {
		return 0, usage("history accepts flags only, or the summary subcommand")
	}
	if err := validateLimit(*limit); err != nil {
		return 0, err
	}
	if *days < 1 || *days > 366 {
		return 0, usage("days must be between 1 and 366")
	}
	_, loaded, err := loadRuntime(global, env, client, nil)
	if err != nil {
		return 0, err
	}
	history, ok := loaded.(historyQueryClient)
	if !ok {
		return 0, errors.New("local message history requires Gulls or gulls runtime serve to be running")
	}
	var result map[string]any
	if summary {
		result, err = history.HistorySummary(*days)
	} else {
		result, err = history.QueryHistory(HistoryQuery{Limit: *limit, Cursor: *cursor, Query: *query, Status: *status, ThreadID: *threadID})
	}
	if err != nil {
		return 0, err
	}
	text := formatInbox(result)
	if summary {
		text = mustJSON(result)
	}
	printJSONOrText(stdout, global.JSON, result, text)
	return 0, nil
}
