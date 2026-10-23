package agentcli

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func codexResultTestConfig(contextDir string) Config {
	return Config{
		APIURL:      "https://message-api.example",
		AgentHandle: "@test:gulls.ai",
		ContextDir:  contextDir,
	}
}

func writeCodexTestRequest(t *testing.T, config Config, taskID string, handle string) []byte {
	t.Helper()
	root := filepath.Join(config.ContextDir, codexTaskDirectory, taskID)
	if err := ensurePrivateDirectory(root); err != nil {
		t.Fatal(err)
	}
	request := codexTaskRequest{
		Version: codexTaskVersion, TaskID: taskID, ProfileID: "profile-1",
		GullHandle: handle, ConnectionRevision: "revision-1", Goal: "Review this task",
		CreatedAt: "2026-10-21T00:00:00Z",
	}
	data, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	data = append(data, '\n')
	if err := os.WriteFile(filepath.Join(root, codexTaskRequestFile), data, 0600); err != nil {
		t.Fatal(err)
	}
	return data
}

func TestCodexTaskResultRoundTripIsLocalAndProfileScoped(t *testing.T) {
	config := codexResultTestConfig(t.TempDir())
	taskID := "123e4567-e89b-12d3-a456-426614174000"
	requestData := writeCodexTestRequest(t, config, taskID, config.AgentHandle)

	result, err := writeCodexTaskResult(config, taskID, "draft result", "123e4567-e89b-12d3-a456-426614174001", "", "")
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(requestData)
	if result.RequestSHA256 != hex.EncodeToString(digest[:]) || result.Content != "draft result" {
		t.Fatalf("unexpected result: %#v", result)
	}
	path := filepath.Join(config.ContextDir, codexTaskDirectory, taskID, codexTaskResultFile)
	info, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm() != 0600 {
		t.Fatalf("result file mode = %o, want private regular file", info.Mode().Perm())
	}
	if _, err := os.Stat(filepath.Join(config.ContextDir, "network-send-marker")); !os.IsNotExist(err) {
		t.Fatalf("unexpected network marker: %v", err)
	}
}

func TestCodexTaskResultRejectsMismatchedGullAndStaleIdentity(t *testing.T) {
	config := codexResultTestConfig(t.TempDir())
	taskID := "123e4567-e89b-12d3-a456-426614174000"
	writeCodexTestRequest(t, config, taskID, "@other:gulls.ai")
	if _, err := writeCodexTaskResult(config, taskID, "draft", "", "", ""); err == nil || !strings.Contains(err.Error(), "different Gull") {
		t.Fatalf("mismatched Gull error = %v", err)
	}

	config = codexResultTestConfig(t.TempDir())
	writeCodexTestRequest(t, config, taskID, config.AgentHandle)
	path := filepath.Join(config.ContextDir, codexTaskDirectory, taskID, codexTaskRequestFile)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var request codexTaskRequest
	if err := json.Unmarshal(data, &request); err != nil {
		t.Fatal(err)
	}
	request.ConnectionRevision = ""
	data, _ = json.Marshal(request)
	if err := os.WriteFile(path, append(data, '\n'), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "draft", "", "", ""); err == nil || !strings.Contains(err.Error(), "profile identity") {
		t.Fatalf("stale identity error = %v", err)
	}
}

func TestCodexTaskResultRejectsInvalidPathsSymlinksAndOverwrite(t *testing.T) {
	config := codexResultTestConfig(t.TempDir())
	if _, err := writeCodexTaskResult(config, "../escape", "draft", "", "", ""); err == nil {
		t.Fatal("path traversal task ID was accepted")
	}

	taskID := "123e4567-e89b-12d3-a456-426614174000"
	root := filepath.Join(config.ContextDir, codexTaskDirectory)
	if err := os.MkdirAll(config.ContextDir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(t.TempDir(), root); err != nil {
		t.Fatal(err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "draft", "", "", ""); err == nil || !strings.Contains(err.Error(), "symlink") {
		t.Fatalf("symlink task root error = %v", err)
	}

	config = codexResultTestConfig(t.TempDir())
	writeCodexTestRequest(t, config, taskID, config.AgentHandle)
	if _, err := writeCodexTaskResult(config, taskID, "first", "", "", ""); err != nil {
		t.Fatal(err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "second", "", "", ""); err == nil || !strings.Contains(err.Error(), "already exists") {
		t.Fatalf("overwrite error = %v", err)
	}
}

func TestCodexTaskResultChecksOptionalIdentityAndSession(t *testing.T) {
	config := codexResultTestConfig(t.TempDir())
	taskID := "123e4567-e89b-12d3-a456-426614174000"
	writeCodexTestRequest(t, config, taskID, config.AgentHandle)
	if _, err := writeCodexTaskResult(config, taskID, "draft", "not-a-uuid", "", ""); err == nil {
		t.Fatal("invalid session ID was accepted")
	}
	if _, err := writeCodexTaskResult(config, taskID, "draft", "", "different-profile", "revision-1"); err == nil || !strings.Contains(err.Error(), "different profile") {
		t.Fatalf("profile mismatch error = %v", err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "draft", "", "profile-1", "different-revision"); err == nil || !strings.Contains(err.Error(), "older connection") {
		t.Fatalf("revision mismatch error = %v", err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "  \n\t", "", "", ""); err == nil {
		t.Fatal("whitespace-only result was accepted")
	}
	if _, err := writeCodexTaskResult(config, taskID, strings.Repeat("x", codexTaskContentMax+1), "", "", ""); err == nil {
		t.Fatal("oversized result was accepted")
	}
}

func TestCodexTaskResultRejectsMalformedManifestAndUnsafeShape(t *testing.T) {
	config := codexResultTestConfig(t.TempDir())
	taskID := "123e4567-e89b-12d3-a456-426614174000"
	writeCodexTestRequest(t, config, taskID, config.AgentHandle)
	requestPath := filepath.Join(config.ContextDir, codexTaskDirectory, taskID, codexTaskRequestFile)
	data, err := os.ReadFile(requestPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(requestPath, append([]byte{'{'}, 0xff), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "draft", "", "", ""); err == nil || !strings.Contains(err.Error(), "not valid UTF-8") {
		t.Fatalf("invalid UTF-8 manifest error = %v", err)
	}
	if err := os.WriteFile(requestPath, data, 0600); err != nil {
		t.Fatal(err)
	}
	var request codexTaskRequest
	if err := json.Unmarshal(data, &request); err != nil {
		t.Fatal(err)
	}
	request.DeliveryID = "delivery-1"
	data, _ = json.Marshal(request)
	if err := os.WriteFile(requestPath, append(data, '\n'), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "draft", "", "", ""); err == nil || !strings.Contains(err.Error(), "pair") {
		t.Fatalf("unpaired delivery/context error = %v", err)
	}
	request.DeliveryID = "delivery-1"
	request.ContextPath = "relative/context.md"
	data, _ = json.Marshal(request)
	if err := os.WriteFile(requestPath, append(data, '\n'), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "draft", "", "", ""); err == nil || !strings.Contains(err.Error(), "absolute") {
		t.Fatalf("relative context path error = %v", err)
	}
	request.ContextPath = "/private/context.md"
	request.DeliveryID = strings.Repeat("d", 257)
	data, _ = json.Marshal(request)
	if err := os.WriteFile(requestPath, append(data, '\n'), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "draft", "", "", ""); err == nil || !strings.Contains(err.Error(), "too long") {
		t.Fatalf("oversized delivery ID error = %v", err)
	}
}

func TestCodexTaskResultRejectsResultSymlinkAndKeepsExistingResult(t *testing.T) {
	config := codexResultTestConfig(t.TempDir())
	taskID := "123e4567-e89b-12d3-a456-426614174000"
	writeCodexTestRequest(t, config, taskID, config.AgentHandle)
	resultPath := filepath.Join(config.ContextDir, codexTaskDirectory, taskID, codexTaskResultFile)
	if err := os.Symlink(filepath.Join(config.ContextDir, "elsewhere"), resultPath); err != nil {
		t.Fatal(err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "draft", "", "", ""); err == nil || !strings.Contains(err.Error(), "private regular file") {
		t.Fatalf("result symlink error = %v", err)
	}
	if err := os.Remove(resultPath); err != nil {
		t.Fatal(err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "first", "", "", ""); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(resultPath)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := writeCodexTaskResult(config, taskID, "second", "", "", ""); err == nil {
		t.Fatal("existing result was overwritten")
	}
	after, err := os.ReadFile(resultPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(before) != string(after) {
		t.Fatal("existing result changed after rejected overwrite")
	}
}

func TestCodexResultContentLimitAndLocalCommand(t *testing.T) {
	if _, err := readCodexResultContent("draft", "", strings.NewReader("")); err != nil {
		t.Fatal(err)
	}
	if _, err := readCodexResultContent("", "-", strings.NewReader(strings.Repeat("x", codexTaskContentMax+1))); err == nil {
		t.Fatal("oversized stdin content was accepted")
	}

	contextDir := t.TempDir()
	taskID := "123e4567-e89b-12d3-a456-426614174000"
	config := codexResultTestConfig(contextDir)
	requestData := writeCodexTestRequest(t, config, taskID, config.AgentHandle)
	stdout := new(strings.Builder)
	stderr := new(strings.Builder)
	code := Main([]string{
		"--api-url", config.APIURL, "--agent-handle", config.AgentHandle, "--context-dir", contextDir,
		"codex", "result", "--content", "from codex", taskID,
	}, stdout, stderr, nil, nil)
	if code != 0 {
		t.Fatalf("codex result exit=%d stderr=%s", code, stderr.String())
	}
	if !strings.Contains(stdout.String(), taskID) {
		t.Fatalf("unexpected output: %s", stdout.String())
	}
	resultBytes, err := os.ReadFile(filepath.Join(contextDir, codexTaskDirectory, taskID, codexTaskResultFile))
	if err != nil {
		t.Fatal(err)
	}
	var result codexTaskResult
	if err := json.Unmarshal(resultBytes, &result); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(requestData)
	if result.RequestSHA256 != hex.EncodeToString(digest[:]) || result.Content != "from codex" {
		t.Fatalf("unexpected command result: %#v", result)
	}
}
