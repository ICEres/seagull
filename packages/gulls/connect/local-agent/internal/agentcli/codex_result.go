package agentcli

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	codexTaskVersion     = 1
	codexTaskManifestMax = 256 * 1024
	codexTaskContentMax  = 128 * 1024
	codexTaskDirectory   = "codex-tasks"
	codexTaskRequestFile = "request.json"
	codexTaskResultFile  = "result.json"
	codexTaskReplyFile   = "reply.json"
)

type codexTaskRequest struct {
	Version              int    `json:"version"`
	TaskID               string `json:"task_id"`
	ProfileID            string `json:"profile_id"`
	GullHandle           string `json:"gull_handle"`
	ConnectionRevision   string `json:"connection_revision"`
	DeliveryID           string `json:"delivery_id,omitempty"`
	ThreadID             string `json:"thread_id,omitempty"`
	Goal                 string `json:"goal"`
	WorkingDirectory     string `json:"working_directory,omitempty"`
	ContextPath          string `json:"context_path,omitempty"`
	ReplyAuthorizationID string `json:"reply_authorization_id,omitempty"`
	CreatedAt            string `json:"created_at"`
}

type codexTaskResult struct {
	Version            int    `json:"version"`
	TaskID             string `json:"task_id"`
	ProfileID          string `json:"profile_id"`
	GullHandle         string `json:"gull_handle"`
	ConnectionRevision string `json:"connection_revision"`
	RequestSHA256      string `json:"request_sha256"`
	Content            string `json:"content"`
	CompletedAt        string `json:"completed_at"`
	CodexThreadID      string `json:"codex_thread_id,omitempty"`
}

// codexTaskReply is an explicit public-reply submission. It is kept separate
// from result.json because a result may contain private owner-facing notes or
// a proposed reply and must never be published implicitly.
type codexTaskReply struct {
	Version            int    `json:"version"`
	TaskID             string `json:"task_id"`
	ProfileID          string `json:"profile_id"`
	GullHandle         string `json:"gull_handle"`
	ConnectionRevision string `json:"connection_revision"`
	RequestSHA256      string `json:"request_sha256"`
	AuthorizationID    string `json:"authorization_id"`
	Content            string `json:"content"`
	SubmittedAt        string `json:"submitted_at"`
}

func runCodexCommand(args []string, global globalOptions, stdout, stderr io.Writer, env []string) (int, error) {
	if len(args) == 0 {
		return 0, usage("codex requires subcommand: result or reply")
	}
	switch args[0] {
	case "result":
		return runCodexResultCommand(args[1:], global, stdout, stderr, env)
	case "reply":
		return runCodexReplyCommand(args[1:], global, stdout, stderr, env)
	default:
		return 0, usage("codex requires subcommand: result or reply")
	}
}

func runCodexReplyCommand(args []string, global globalOptions, stdout, stderr io.Writer, env []string) (int, error) {
	fs := commandFlagSet("codex reply", stderr)
	content := fs.String("content", "", "exact public reply content")
	contentFile := fs.String("content-file", "", "read exact public reply content from a file, or - for stdin")
	profileID := fs.String("profile-id", "", "expected Gull profile ID")
	connectionRevision := fs.String("connection-revision", "", "expected Gull connection revision")
	if err := parseCommand(fs, args); err != nil {
		return 0, err
	}
	if fs.NArg() != 1 {
		return 0, usage("codex reply requires task_id")
	}
	taskID := fs.Arg(0)
	if !validLowerUUID(taskID) {
		return 0, usage("codex reply task_id must be a lowercase UUID")
	}
	if *content != "" && *contentFile != "" {
		return 0, usage("codex reply accepts only one of --content or --content-file")
	}
	if *content == "" && *contentFile == "" {
		return 0, usage("codex reply requires --content or --content-file")
	}
	expectedProfileID, expectedRevision, err := scopedCodexIdentity(global, *profileID, *connectionRevision, "codex reply")
	if err != nil {
		return 0, err
	}
	config, err := LoadConfig(env, ConfigOverrides{APIURL: global.APIURL, AgentHandle: global.AgentHandle, ContextDir: global.ContextDir})
	if err != nil {
		return 0, fmt.Errorf("%w: %w", errConfig, err)
	}
	replyContent, err := readCodexResultContent(*content, *contentFile, os.Stdin)
	if err != nil {
		return 0, err
	}
	reply, err := writeCodexTaskReply(config, taskID, replyContent, expectedProfileID, expectedRevision)
	if err != nil {
		return 0, err
	}
	if global.JSON {
		printJSON(stdout, codexTaskReplyMap(reply))
	} else {
		fmt.Fprintf(stdout, "Wrote explicit Codex reply for task %s.\n", taskID)
	}
	return 0, nil
}

func scopedCodexIdentity(global globalOptions, profileID, revision, command string) (string, string, error) {
	expectedProfileID := strings.TrimSpace(profileID)
	expectedRevision := strings.TrimSpace(revision)
	if global.ProfileID != "" || global.Revision != "" {
		if global.ProfileID == "" || global.Revision == "" {
			return "", "", usage("global explicit runtime routing requires both --profile-id and --connection-revision")
		}
		if expectedProfileID != "" && expectedProfileID != global.ProfileID {
			return "", "", usage(command + " profile-id does not match the scoped CLI profile")
		}
		if expectedRevision != "" && expectedRevision != global.Revision {
			return "", "", usage(command + " connection-revision does not match the scoped CLI revision")
		}
		expectedProfileID = global.ProfileID
		expectedRevision = global.Revision
	}
	return expectedProfileID, expectedRevision, nil
}

func runCodexResultCommand(args []string, global globalOptions, stdout, stderr io.Writer, env []string) (int, error) {
	fs := commandFlagSet("codex result", stderr)
	content := fs.String("content", "", "result content")
	contentFile := fs.String("content-file", "", "read result content from a file, or - for stdin")
	sessionID := fs.String("session-id", "", "Codex thread/session UUID")
	profileID := fs.String("profile-id", "", "expected Gull profile ID")
	connectionRevision := fs.String("connection-revision", "", "expected Gull connection revision")
	if err := parseCommand(fs, args); err != nil {
		return 0, err
	}
	if fs.NArg() != 1 {
		return 0, usage("codex result requires task_id")
	}
	taskID := fs.Arg(0)
	if !validLowerUUID(taskID) {
		return 0, usage("codex result task_id must be a lowercase UUID")
	}
	if *contentFile != "" && *content != "" {
		return 0, usage("codex result accepts only one of --content or --content-file")
	}
	if *sessionID != "" && !validLocalActionID(*sessionID) {
		return 0, usage("codex result session-id must be a UUID")
	}
	expectedProfileID := strings.TrimSpace(*profileID)
	expectedRevision := strings.TrimSpace(*connectionRevision)
	if global.ProfileID != "" || global.Revision != "" {
		if global.ProfileID == "" || global.Revision == "" {
			return 0, usage("global explicit runtime routing requires both --profile-id and --connection-revision")
		}
		if expectedProfileID != "" && expectedProfileID != global.ProfileID {
			return 0, usage("codex result profile-id does not match the scoped CLI profile")
		}
		if expectedRevision != "" && expectedRevision != global.Revision {
			return 0, usage("codex result connection-revision does not match the scoped CLI revision")
		}
		expectedProfileID = global.ProfileID
		expectedRevision = global.Revision
	}

	config, err := LoadConfig(env, ConfigOverrides{
		APIURL: global.APIURL, AgentHandle: global.AgentHandle, ContextDir: global.ContextDir,
	})
	if err != nil {
		return 0, fmt.Errorf("%w: %w", errConfig, err)
	}
	resultContent, err := readCodexResultContent(*content, *contentFile, os.Stdin)
	if err != nil {
		return 0, err
	}
	result, err := writeCodexTaskResult(config, taskID, resultContent, *sessionID, expectedProfileID, expectedRevision)
	if err != nil {
		return 0, err
	}
	if global.JSON {
		printJSON(stdout, codexTaskResultMap(result))
	} else {
		fmt.Fprintf(stdout, "Wrote Codex result for task %s.\n", taskID)
	}
	return 0, nil
}

func codexTaskResultMap(result codexTaskResult) map[string]any {
	data, _ := json.Marshal(result)
	var payload map[string]any
	_ = json.Unmarshal(data, &payload)
	return payload
}

func codexTaskReplyMap(reply codexTaskReply) map[string]any {
	data, _ := json.Marshal(reply)
	var payload map[string]any
	_ = json.Unmarshal(data, &payload)
	return payload
}

func readCodexResultContent(value, path string, stdin io.Reader) (string, error) {
	if path == "" {
		if strings.TrimSpace(value) == "" {
			return "", errors.New("Codex result content must not be empty")
		}
		if !utf8.ValidString(value) || len([]byte(value)) > codexTaskContentMax {
			return "", fmt.Errorf("codex result content exceeds %d bytes or is not valid UTF-8", codexTaskContentMax)
		}
		return value, nil
	}
	var reader io.Reader
	if path == "-" {
		reader = stdin
	} else {
		file, err := os.Open(path)
		if err != nil {
			return "", err
		}
		defer file.Close()
		reader = file
	}
	data, err := io.ReadAll(io.LimitReader(reader, codexTaskContentMax+1))
	if err != nil {
		return "", err
	}
	if len(data) > codexTaskContentMax {
		return "", fmt.Errorf("codex result content exceeds %d bytes", codexTaskContentMax)
	}
	if len(data) == 0 {
		return "", errors.New("Codex result content must not be empty")
	}
	return string(data), nil
}

func writeCodexTaskResult(config Config, taskID, content, sessionID, expectedProfileID, expectedRevision string) (codexTaskResult, error) {
	if !validLowerUUID(taskID) {
		return codexTaskResult{}, errors.New("Codex task_id must be a lowercase UUID")
	}
	if strings.TrimSpace(content) == "" {
		return codexTaskResult{}, errors.New("Codex result content must not be empty")
	}
	if !utf8.ValidString(content) || len([]byte(content)) > codexTaskContentMax {
		return codexTaskResult{}, fmt.Errorf("Codex result content exceeds %d bytes or is not valid UTF-8", codexTaskContentMax)
	}
	if sessionID != "" && !validLocalActionID(sessionID) {
		return codexTaskResult{}, errors.New("Codex session ID must be a UUID")
	}
	root := filepath.Join(config.ContextDir, codexTaskDirectory)
	if err := ensurePrivateDirectory(config.ContextDir); err != nil {
		return codexTaskResult{}, fmt.Errorf("context directory: %w", err)
	}
	if err := ensurePrivateDirectory(root); err != nil {
		return codexTaskResult{}, fmt.Errorf("codex task directory: %w", err)
	}
	taskDir := filepath.Join(root, taskID)
	if err := ensurePrivateExistingDirectory(taskDir); err != nil {
		return codexTaskResult{}, fmt.Errorf("task directory: %w", err)
	}
	requestPath := filepath.Join(taskDir, codexTaskRequestFile)
	requestData, err := readPrivateCodexManifest(requestPath)
	if err != nil {
		return codexTaskResult{}, err
	}
	if !utf8.Valid(requestData) {
		return codexTaskResult{}, errors.New("Codex task request is not valid UTF-8")
	}
	var request codexTaskRequest
	if err := json.Unmarshal(requestData, &request); err != nil {
		return codexTaskResult{}, fmt.Errorf("invalid Codex task request: %w", err)
	}
	if err := validateCodexTaskRequest(request, taskID, config, expectedProfileID, expectedRevision); err != nil {
		return codexTaskResult{}, err
	}

	digest := sha256.Sum256(requestData)
	result := codexTaskResult{
		Version: codexTaskVersion, TaskID: request.TaskID, ProfileID: request.ProfileID,
		GullHandle: request.GullHandle, ConnectionRevision: request.ConnectionRevision,
		RequestSHA256: hex.EncodeToString(digest[:]), Content: content,
		CompletedAt: time.Now().UTC().Format(time.RFC3339Nano), CodexThreadID: sessionID,
	}
	resultData, err := json.Marshal(result)
	if err != nil {
		return codexTaskResult{}, err
	}
	resultData = append(resultData, '\n')
	resultPath := filepath.Join(taskDir, codexTaskResultFile)
	if info, statErr := os.Lstat(resultPath); statErr == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
			return codexTaskResult{}, errors.New("Codex task result must be a private regular file")
		}
		return codexTaskResult{}, errors.New("Codex task result already exists")
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return codexTaskResult{}, statErr
	}
	if err := writePrivateNewFile(resultPath, resultData); err != nil {
		return codexTaskResult{}, err
	}
	return result, nil
}

func writeCodexTaskReply(config Config, taskID, content, expectedProfileID, expectedRevision string) (codexTaskReply, error) {
	if !validLowerUUID(taskID) {
		return codexTaskReply{}, errors.New("Codex task_id must be a lowercase UUID")
	}
	if strings.TrimSpace(content) == "" {
		return codexTaskReply{}, errors.New("Codex reply content must not be empty")
	}
	if !utf8.ValidString(content) || len([]byte(content)) > codexTaskContentMax {
		return codexTaskReply{}, fmt.Errorf("Codex reply content exceeds %d bytes or is not valid UTF-8", codexTaskContentMax)
	}
	root := filepath.Join(config.ContextDir, codexTaskDirectory)
	if err := ensurePrivateDirectory(config.ContextDir); err != nil {
		return codexTaskReply{}, fmt.Errorf("context directory: %w", err)
	}
	if err := ensurePrivateDirectory(root); err != nil {
		return codexTaskReply{}, fmt.Errorf("codex task directory: %w", err)
	}
	taskDir := filepath.Join(root, taskID)
	if err := ensurePrivateExistingDirectory(taskDir); err != nil {
		return codexTaskReply{}, fmt.Errorf("task directory: %w", err)
	}
	requestPath := filepath.Join(taskDir, codexTaskRequestFile)
	requestData, err := readPrivateCodexManifest(requestPath)
	if err != nil {
		return codexTaskReply{}, err
	}
	if !utf8.Valid(requestData) {
		return codexTaskReply{}, errors.New("Codex task request is not valid UTF-8")
	}
	var request codexTaskRequest
	if err := json.Unmarshal(requestData, &request); err != nil {
		return codexTaskReply{}, fmt.Errorf("invalid Codex task request: %w", err)
	}
	if err := validateCodexTaskRequest(request, taskID, config, expectedProfileID, expectedRevision); err != nil {
		return codexTaskReply{}, err
	}
	if request.ReplyAuthorizationID == "" {
		return codexTaskReply{}, errors.New("Codex task is not authorized for public reply submission")
	}
	if !validLowerUUID(request.ReplyAuthorizationID) {
		return codexTaskReply{}, errors.New("Codex task reply authorization is invalid")
	}
	digest := sha256.Sum256(requestData)
	reply := codexTaskReply{
		Version: 1, TaskID: request.TaskID, ProfileID: request.ProfileID,
		GullHandle: request.GullHandle, ConnectionRevision: request.ConnectionRevision,
		RequestSHA256: hex.EncodeToString(digest[:]), AuthorizationID: request.ReplyAuthorizationID,
		Content: content, SubmittedAt: time.Now().UTC().Format(time.RFC3339Nano),
	}
	replyData, err := json.Marshal(reply)
	if err != nil {
		return codexTaskReply{}, err
	}
	replyData = append(replyData, '\n')
	replyPath := filepath.Join(taskDir, codexTaskReplyFile)
	if info, statErr := os.Lstat(replyPath); statErr == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
			return codexTaskReply{}, errors.New("Codex task reply must be a private regular file")
		}
		return codexTaskReply{}, errors.New("Codex task reply already exists")
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return codexTaskReply{}, statErr
	}
	if err := writePrivateNewFile(replyPath, replyData); err != nil {
		return codexTaskReply{}, err
	}
	return reply, nil
}

func readPrivateCodexManifest(path string) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, errors.New("Codex task request was not found")
		}
		return nil, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("Codex task request must be a private regular file")
	}
	if info.Size() > codexTaskManifestMax {
		return nil, fmt.Errorf("Codex task request exceeds %d bytes", codexTaskManifestMax)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(data) > codexTaskManifestMax {
		return nil, fmt.Errorf("Codex task request exceeds %d bytes", codexTaskManifestMax)
	}
	return data, nil
}

func validateCodexTaskRequest(request codexTaskRequest, taskID string, config Config, expectedProfileID, expectedRevision string) error {
	for name, value := range map[string]string{
		"profile_id": request.ProfileID, "gull_handle": request.GullHandle,
		"connection_revision": request.ConnectionRevision, "delivery_id": request.DeliveryID,
		"thread_id": request.ThreadID, "goal": request.Goal,
		"working_directory": request.WorkingDirectory, "context_path": request.ContextPath,
	} {
		if !utf8.ValidString(value) {
			return fmt.Errorf("Codex task request %s is not valid UTF-8", name)
		}
	}
	if request.Version != codexTaskVersion || request.TaskID != taskID || !validLowerUUID(request.TaskID) {
		return errors.New("Codex task request has an invalid task_id")
	}
	if strings.TrimSpace(request.ProfileID) == "" || strings.TrimSpace(request.GullHandle) == "" || strings.TrimSpace(request.ConnectionRevision) == "" {
		return errors.New("Codex task request is missing profile identity")
	}
	if len(request.ProfileID) > 4096 || len(request.ConnectionRevision) > 4096 || len(request.GullHandle) > 4096 {
		return errors.New("Codex task request profile identity is too long")
	}
	if expectedProfileID != "" && request.ProfileID != expectedProfileID {
		return errors.New("Codex task request belongs to a different profile")
	}
	if expectedRevision != "" && request.ConnectionRevision != expectedRevision {
		return errors.New("Codex task request belongs to an older connection")
	}
	if request.GullHandle != config.AgentHandle {
		return errors.New("Codex task request belongs to a different Gull")
	}
	if request.ProfileID == "" || request.ConnectionRevision == "" {
		return errors.New("Codex task request has an invalid profile identity")
	}
	if strings.TrimSpace(request.Goal) == "" || !utf8.ValidString(request.Goal) || len([]byte(request.Goal)) > 16*1024 {
		return errors.New("Codex task request has invalid goal or created_at")
	}
	if len(request.WorkingDirectory) > 16*1024 || len(request.ContextPath) > 16*1024 {
		return errors.New("Codex task request path is too long")
	}
	if len(request.DeliveryID) > 256 || len(request.ThreadID) > 256 {
		return errors.New("Codex task request delivery or thread ID is too long")
	}
	if (request.DeliveryID == "") != (request.ContextPath == "") {
		return errors.New("Codex task request must pair delivery_id with context_path")
	}
	if request.WorkingDirectory != "" && !filepath.IsAbs(request.WorkingDirectory) {
		return errors.New("Codex task request working_directory must be absolute")
	}
	if request.ContextPath != "" && !filepath.IsAbs(request.ContextPath) {
		return errors.New("Codex task request context_path must be absolute")
	}
	if _, err := time.Parse(time.RFC3339Nano, request.CreatedAt); err != nil {
		return errors.New("Codex task request has invalid goal or created_at")
	}
	return nil
}

func validLowerUUID(value string) bool {
	return validLocalActionID(value) && value == strings.ToLower(value)
}

func ensurePrivateDirectory(path string) error {
	clean := filepath.Clean(path)
	if clean == "." || clean == string(filepath.Separator) {
		return errors.New("directory path is too broad")
	}
	info, err := os.Lstat(clean)
	if err == nil {
		if !info.IsDir() || info.Mode().Type()&os.ModeSymlink != 0 {
			return errors.New("directory must be private and must not be a symlink")
		}
		if info.Mode().Perm()&0077 != 0 {
			if err := os.Chmod(clean, 0700); err != nil {
				return err
			}
		}
		return nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	parent := filepath.Dir(clean)
	parentInfo, parentErr := os.Lstat(parent)
	if parentErr == nil {
		if !parentInfo.IsDir() || parentInfo.Mode().Type()&os.ModeSymlink != 0 {
			return errors.New("directory parent must not be a symlink")
		}
	} else if errors.Is(parentErr, os.ErrNotExist) {
		if err := ensurePrivateDirectory(parent); err != nil {
			return err
		}
	} else {
		return parentErr
	}
	if err := os.Mkdir(clean, 0700); err != nil && !errors.Is(err, os.ErrExist) {
		return err
	}
	info, err = os.Lstat(clean)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode().Type()&os.ModeSymlink != 0 {
		return errors.New("directory must be private and must not be a symlink")
	}
	return nil
}

func ensurePrivateExistingDirectory(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return errors.New("directory was not found")
		}
		return err
	}
	if !info.IsDir() || info.Mode().Type()&os.ModeSymlink != 0 {
		return errors.New("directory must be private and must not be a symlink")
	}
	if info.Mode().Perm()&0077 != 0 {
		return errors.New("directory must be private")
	}
	return nil
}

func writePrivateNewFile(path string, data []byte) error {
	dir := filepath.Dir(path)
	temp, err := os.CreateTemp(dir, ".codex-result-*")
	if err != nil {
		return err
	}
	tempPath := temp.Name()
	defer os.Remove(tempPath)
	if _, err := temp.Write(data); err != nil {
		_ = temp.Close()
		return err
	}
	if err := temp.Sync(); err != nil {
		_ = temp.Close()
		return err
	}
	if err := temp.Close(); err != nil {
		return err
	}
	if err := os.Link(tempPath, path); err != nil {
		return err
	}
	return nil
}
