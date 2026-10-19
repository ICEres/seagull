package agentcli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func localActionTestConfig(contextDir string) Config {
	return Config{
		APIURL:      "https://message-api.example",
		AgentHandle: "@test:gulls.ai",
		ContextDir:  contextDir,
	}
}

func localActionTestRequest(t *testing.T, config Config, kind string) localActionRequest {
	t.Helper()
	var executable string
	var args []string
	var workingDirectory string
	var path string
	var content *string
	switch kind {
	case "command":
		executable = "/usr/bin/printf"
		args = []string{"%s", "literal $HOME"}
		workingDirectory = "/tmp"
	case "read_file":
		path = "/absolute/file"
	case "write_file":
		path = "/absolute/file"
		value := "content"
		content = &value
	}
	request, err := newLocalActionRequest(config, kind, executable, args, workingDirectory, path, content)
	if err != nil {
		t.Fatal(err)
	}
	if err := validateLocalActionRequest(request); err != nil {
		t.Fatal(err)
	}
	return request
}

func TestLocalActionRequestIsQueuedWithoutExecuting(t *testing.T) {
	dir := t.TempDir()
	config := localActionTestConfig(dir)
	request := localActionTestRequest(t, config, "command")
	if err := writeLocalActionRequest(dir, request); err != nil {
		t.Fatal(err)
	}

	path := filepath.Join(dir, "local-actions", "requests", request.RequestID+".json")
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("request mode = %o, want 600", info.Mode().Perm())
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var decoded localActionRequest
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded.Executable != "/usr/bin/printf" || strings.Join(decoded.Arguments, "|") != "%s|literal $HOME" {
		t.Fatalf("request lost literal command fields: %#v", decoded)
	}
	if _, err := os.Stat(filepath.Join(dir, "local-actions", "results", request.RequestID+".json")); !os.IsNotExist(err) {
		t.Fatalf("request unexpectedly produced a result: %v", err)
	}
}

func TestLocalActionStatusReadsRequestThenResultAndChecksHandle(t *testing.T) {
	dir := t.TempDir()
	config := localActionTestConfig(dir)
	request := localActionTestRequest(t, config, "read_file")
	if err := writeLocalActionRequest(dir, request); err != nil {
		t.Fatal(err)
	}
	payload, state, err := readLocalActionStatus(dir, config.AgentHandle, request.RequestID)
	if err != nil || state != "needs_approval" || payload["request_id"] != request.RequestID {
		t.Fatalf("request status = %#v, %s, %v", payload, state, err)
	}
	_, _, err = readLocalActionStatus(dir, "@other:gulls.ai", request.RequestID)
	if !os.IsNotExist(err) {
		t.Fatalf("mismatched handle error = %v, want not found", err)
	}

	_, results, err := localActionDirectories(dir)
	if err != nil {
		t.Fatal(err)
	}
	result := localActionResult{
		Version: localActionVersion, RequestID: request.RequestID, GullHandle: config.AgentHandle,
		Status: "succeeded", CompletedAt: "2026-10-18T00:00:00Z", Content: "file contents",
	}
	data, _ := json.Marshal(result)
	if err := os.WriteFile(filepath.Join(results, request.RequestID+".json"), append(data, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}
	payload, state, err = readLocalActionStatus(dir, config.AgentHandle, request.RequestID)
	if err != nil || state != "succeeded" || payload["content"] != "file contents" {
		t.Fatalf("result status = %#v, %s, %v", payload, state, err)
	}
}

func TestLocalActionValidationAndBounds(t *testing.T) {
	config := localActionTestConfig(t.TempDir())
	request := localActionTestRequest(t, config, "command")
	request.Executable = "printf"
	if err := validateLocalActionRequest(request); err == nil {
		t.Fatal("relative executable was accepted")
	}
	request = localActionTestRequest(t, config, "command")
	request.WorkingDirectory = ""
	if err := validateLocalActionRequest(request); err == nil {
		t.Fatal("command without working directory was accepted")
	}
	request = localActionTestRequest(t, config, "read_file")
	request.WorkingDirectory = "/tmp"
	if err := validateLocalActionRequest(request); err == nil {
		t.Fatal("file action with working directory was accepted")
	}
	empty := ""
	request, err := newLocalActionRequest(config, "write_file", "", nil, "", "/absolute/file", &empty)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := json.Marshal(request)
	if err != nil || !strings.Contains(string(payload), `"content":""`) {
		t.Fatalf("empty write content was not preserved: %s (%v)", payload, err)
	}
	if _, err := readLocalActionContentFile(filepath.Join(t.TempDir(), "missing")); err == nil {
		t.Fatal("missing content file was accepted")
	}

	large := strings.Repeat("x", maxLocalActionFileInput+1)
	path := filepath.Join(t.TempDir(), "large.txt")
	if err := os.WriteFile(path, []byte(large), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := readLocalActionContentFile(path); err == nil {
		t.Fatal("oversized content file was accepted")
	}
	missingContext := filepath.Join(t.TempDir(), "missing-context")
	if _, _, err := readLocalActionStatus(missingContext, config.AgentHandle, request.RequestID); !os.IsNotExist(err) {
		t.Fatalf("missing status error = %v, want not found", err)
	}
	if _, err := os.Stat(missingContext); !os.IsNotExist(err) {
		t.Fatalf("status query created context directory: %v", err)
	}
}
