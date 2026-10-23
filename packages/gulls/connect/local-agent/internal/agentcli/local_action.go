package agentcli

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	localActionVersion      = 1
	localActionCodexVersion = 2
	maxLocalActionRequest   = 256 * 1024
	maxLocalActionFileInput = 1 * 1024 * 1024
	maxLocalActionResult    = 8 * 1024 * 1024
)

type localActionRequest struct {
	Version            int      `json:"version"`
	RequestID          string   `json:"request_id"`
	GullHandle         string   `json:"gull_handle"`
	Kind               string   `json:"kind"`
	CreatedAt          string   `json:"created_at"`
	ProfileID          string   `json:"profile_id,omitempty"`
	CodexTaskID        string   `json:"codex_task_id,omitempty"`
	CodexTaskFolder    string   `json:"codex_task_folder,omitempty"`
	CodexTaskDigest    string   `json:"codex_task_digest,omitempty"`
	ConnectionRevision string   `json:"connection_revision,omitempty"`
	Executable         string   `json:"executable,omitempty"`
	Arguments          []string `json:"arguments,omitempty"`
	WorkingDirectory   string   `json:"working_directory,omitempty"`
	Path               string   `json:"path,omitempty"`
	Content            *string  `json:"content,omitempty"`
}

type localActionResult struct {
	Version     int    `json:"version"`
	RequestID   string `json:"request_id"`
	GullHandle  string `json:"gull_handle"`
	Status      string `json:"status"`
	CompletedAt string `json:"completed_at"`
	Stdout      string `json:"stdout,omitempty"`
	Stderr      string `json:"stderr,omitempty"`
	ExitCode    *int   `json:"exit_code,omitempty"`
	Content     string `json:"content,omitempty"`
	Error       string `json:"error,omitempty"`
}

func runLocalActionCommand(args []string, global globalOptions, stdout, stderr io.Writer, env []string, client Client) (int, error) {
	if len(args) == 0 {
		return 0, usage("local-action requires subcommand: request or status")
	}
	config, _, err := loadRuntime(global, env, client, nil)
	if err != nil {
		return 0, err
	}
	switch args[0] {
	case "request":
		fs := commandFlagSet("local-action request", stderr)
		kind := fs.String("kind", "", "command, read_file, or write_file")
		executable := fs.String("executable", "", "absolute executable path for command actions")
		workingDirectory := fs.String("working-directory", "", "absolute working directory for command actions")
		path := fs.String("path", "", "absolute file path for read_file or write_file")
		content := fs.String("content", "", "file content for write_file")
		contentFile := fs.String("content-file", "", "read write_file content from a local file (maximum 1 MiB)")
		arguments := stringList{}
		fs.Var(&arguments, "arg", "literal command argument; may be repeated")
		if err := parseCommand(fs, args[1:]); err != nil {
			return 0, err
		}
		if fs.NArg() != 0 {
			return 0, usage("local-action request does not accept positional arguments")
		}
		if *contentFile != "" && *content != "" {
			return 0, usage("local-action request accepts only one of --content or --content-file")
		}
		contentSet := false
		fs.Visit(func(flag *flag.Flag) {
			if flag.Name == "content" {
				contentSet = true
			}
		})
		var requestContent *string
		if contentSet {
			value := *content
			requestContent = &value
		}
		if *contentFile != "" {
			value, readErr := readLocalActionContentFile(*contentFile)
			err = readErr
			if err != nil {
				return 0, err
			}
			requestContent = &value
		}
		if *kind == "write_file" && requestContent == nil {
			return 0, usage("write_file requires --content or --content-file")
		}
		request, err := newLocalActionRequest(config, *kind, *executable, []string(arguments), *workingDirectory, *path, requestContent)
		if err != nil {
			return 0, usage(err.Error())
		}
		if err := writeLocalActionRequest(config.ContextDir, request); err != nil {
			return 0, err
		}
		payload := localActionRequestMap(request)
		payload["state"] = "needs_approval"
		printJSONOrText(stdout, global.JSON, payload, fmt.Sprintf("Queued local action %s for Mac approval.", request.RequestID))
		return 0, nil
	case "status":
		fs := commandFlagSet("local-action status", stderr)
		if err := parseCommand(fs, args[1:]); err != nil {
			return 0, err
		}
		if fs.NArg() != 1 {
			return 0, usage("local-action status requires request_id")
		}
		payload, state, err := readLocalActionStatus(config.ContextDir, config.AgentHandle, fs.Arg(0))
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				return 0, fmt.Errorf("local action not found: %s", fs.Arg(0))
			}
			return 0, err
		}
		printJSONOrText(stdout, global.JSON, payload, fmt.Sprintf("Local action %s: %s.", fs.Arg(0), state))
		return 0, nil
	default:
		return 0, fmt.Errorf("unknown local-action subcommand: %s", args[0])
	}
}

func newLocalActionRequest(config Config, kind, executable string, args []string, workingDirectory, path string, content *string) (localActionRequest, error) {
	requestID, err := newLocalActionID()
	if err != nil {
		return localActionRequest{}, err
	}
	request := localActionRequest{
		Version:          localActionVersion,
		RequestID:        requestID,
		GullHandle:       config.AgentHandle,
		Kind:             kind,
		CreatedAt:        time.Now().UTC().Format(time.RFC3339Nano),
		Executable:       executable,
		Arguments:        args,
		WorkingDirectory: workingDirectory,
		Path:             path,
		Content:          content,
	}
	if err := validateLocalActionRequest(request); err != nil {
		return localActionRequest{}, err
	}
	return request, nil
}

func validateLocalActionRequest(request localActionRequest) error {
	if (request.Version != localActionVersion && request.Version != localActionCodexVersion) || !validLocalActionID(request.RequestID) {
		return errors.New("invalid local action request metadata")
	}
	if strings.TrimSpace(request.GullHandle) == "" {
		return errors.New("local action requires a configured Gull handle")
	}
	if request.CreatedAt == "" {
		return errors.New("local action requires created_at")
	}
	if request.Version == localActionCodexVersion {
		if strings.TrimSpace(request.ProfileID) == "" || !validLocalActionID(request.CodexTaskID) ||
			!filepath.IsAbs(request.CodexTaskFolder) || len(request.CodexTaskDigest) != 64 ||
			!isHexDigest(request.CodexTaskDigest) || strings.TrimSpace(request.ConnectionRevision) == "" {
			return errors.New("Codex local action requires task provenance")
		}
	}
	if _, err := time.Parse(time.RFC3339Nano, request.CreatedAt); err != nil {
		return errors.New("local action created_at must be RFC3339")
	}
	switch request.Kind {
	case "command":
		if !filepath.IsAbs(request.Executable) {
			return errors.New("command executable must be an absolute path")
		}
		if request.WorkingDirectory == "" {
			return errors.New("command requires an absolute working directory")
		}
		if request.Path != "" || request.Content != nil {
			return errors.New("command does not accept path or content")
		}
	case "read_file":
		if !filepath.IsAbs(request.Path) {
			return errors.New("read_file path must be an absolute path")
		}
		if request.Executable != "" || len(request.Arguments) != 0 || request.WorkingDirectory != "" || request.Content != nil {
			return errors.New("read_file accepts only path")
		}
	case "write_file":
		if !filepath.IsAbs(request.Path) {
			return errors.New("write_file path must be an absolute path")
		}
		if request.Executable != "" || len(request.Arguments) != 0 || request.WorkingDirectory != "" || request.Content == nil {
			return errors.New("write_file accepts only path and content")
		}
	default:
		return fmt.Errorf("unsupported local action kind: %s", request.Kind)
	}
	if request.WorkingDirectory != "" && !filepath.IsAbs(request.WorkingDirectory) {
		return errors.New("working directory must be an absolute path")
	}
	return nil
}

func isHexDigest(value string) bool {
	for _, char := range value {
		if !((char >= '0' && char <= '9') || (char >= 'a' && char <= 'f') || (char >= 'A' && char <= 'F')) {
			return false
		}
	}
	return true
}

func validateLocalActionResult(result localActionResult) error {
	if result.Version != localActionVersion || !validLocalActionID(result.RequestID) {
		return errors.New("invalid local action result metadata")
	}
	if strings.TrimSpace(result.GullHandle) == "" {
		return errors.New("local action result requires a Gull handle")
	}
	switch result.Status {
	case "succeeded", "failed", "rejected", "cancelled":
	default:
		return fmt.Errorf("unsupported local action result status: %s", result.Status)
	}
	if result.CompletedAt == "" {
		return errors.New("local action result requires completed_at")
	}
	if _, err := time.Parse(time.RFC3339Nano, result.CompletedAt); err != nil {
		return errors.New("local action completed_at must be RFC3339")
	}
	return nil
}

func localActionRequestMap(request localActionRequest) map[string]any {
	return marshalMap(request)
}

func localActionResultMap(result localActionResult) map[string]any {
	return marshalMap(result)
}

func marshalMap(value any) map[string]any {
	data, _ := json.Marshal(value)
	var result map[string]any
	_ = json.Unmarshal(data, &result)
	return result
}

func localActionDirectories(contextDir string) (string, string, error) {
	requests, results := localActionPaths(contextDir)
	base := filepath.Dir(requests)
	for _, path := range []string{base, requests, results} {
		if err := os.MkdirAll(path, 0o700); err != nil {
			return "", "", err
		}
		if err := os.Chmod(path, 0o700); err != nil {
			return "", "", err
		}
	}
	return requests, results, nil
}

func localActionPaths(contextDir string) (string, string) {
	base := filepath.Join(contextDir, "local-actions")
	return filepath.Join(base, "requests"), filepath.Join(base, "results")
}

func writeLocalActionRequest(contextDir string, request localActionRequest) error {
	if err := validateLocalActionRequest(request); err != nil {
		return err
	}
	payload, err := json.Marshal(request)
	if err != nil {
		return err
	}
	if len(payload)+1 > maxLocalActionRequest {
		return fmt.Errorf("local action request exceeds %d bytes", maxLocalActionRequest)
	}
	requests, _, err := localActionDirectories(contextDir)
	if err != nil {
		return err
	}
	path := filepath.Join(requests, request.RequestID+".json")
	tempPath := filepath.Join(requests, "."+request.RequestID+".tmp")
	file, err := os.OpenFile(tempPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	defer os.Remove(tempPath)
	if _, err := file.Write(append(payload, '\n')); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	// A hard link publishes the fully written file atomically and refuses to
	// replace an existing request with the same ID.
	return os.Link(tempPath, path)
}

func readLocalActionStatus(contextDir, configuredHandle, requestID string) (map[string]any, string, error) {
	if !validLocalActionID(requestID) {
		return nil, "", errors.New("request_id must be a UUID")
	}
	requests, results := localActionPaths(contextDir)
	resultPath := filepath.Join(results, requestID+".json")
	requestPath := filepath.Join(requests, requestID+".json")
	if data, readErr := readLocalActionFile(resultPath, maxLocalActionResult); readErr == nil {
		var result localActionResult
		if err := json.Unmarshal(data, &result); err != nil {
			return nil, "", fmt.Errorf("invalid local action result: %w", err)
		}
		if err := validateLocalActionResult(result); err != nil {
			return nil, "", fmt.Errorf("invalid local action result: %w", err)
		}
		if result.RequestID != requestID || result.GullHandle != configuredHandle {
			return nil, "", os.ErrNotExist
		}
		payload := localActionResultMap(result)
		payload["state"] = result.Status
		return payload, result.Status, nil
	} else if !os.IsNotExist(readErr) {
		return nil, "", readErr
	}
	data, err := readLocalActionFile(requestPath, maxLocalActionRequest)
	if err != nil {
		return nil, "", os.ErrNotExist
	}
	var request localActionRequest
	if err := json.Unmarshal(data, &request); err != nil {
		return nil, "", fmt.Errorf("invalid local action request: %w", err)
	}
	if err := validateLocalActionRequest(request); err != nil {
		return nil, "", fmt.Errorf("invalid local action request: %w", err)
	}
	if request.RequestID != requestID || request.GullHandle != configuredHandle {
		return nil, "", os.ErrNotExist
	}
	payload := localActionRequestMap(request)
	payload["state"] = "needs_approval"
	return payload, "needs_approval", nil
}

func readLocalActionFile(path string, limit int64) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) > limit {
		return nil, fmt.Errorf("local action file exceeds %d bytes", limit)
	}
	return data, nil
}

func readLocalActionContentFile(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, maxLocalActionFileInput+1))
	if err != nil {
		return "", err
	}
	if len(data) > maxLocalActionFileInput {
		return "", fmt.Errorf("content file exceeds %d bytes", maxLocalActionFileInput)
	}
	return string(data), nil
}

func newLocalActionID() (string, error) {
	var data [16]byte
	if _, err := rand.Read(data[:]); err != nil {
		return "", err
	}
	data[6] = (data[6] & 0x0f) | 0x40
	data[8] = (data[8] & 0x3f) | 0x80
	encoded := hex.EncodeToString(data[:])
	return encoded[0:8] + "-" + encoded[8:12] + "-" + encoded[12:16] + "-" + encoded[16:20] + "-" + encoded[20:32], nil
}

func validLocalActionID(value string) bool {
	if len(value) != 36 || value[8] != '-' || value[13] != '-' || value[18] != '-' || value[23] != '-' {
		return false
	}
	for index, char := range value {
		if index == 8 || index == 13 || index == 18 || index == 23 {
			continue
		}
		if !((char >= '0' && char <= '9') || (char >= 'a' && char <= 'f') || (char >= 'A' && char <= 'F')) {
			return false
		}
	}
	return true
}
