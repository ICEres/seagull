package agentcli

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Client interface {
	GetAgent(handle string) (map[string]any, error)
	GetInbox(handle string, limit int) (map[string]any, error)
	GetThread(threadID string, limit int) (map[string]any, error)
	GetThreadContext(threadID string, requesterHandle string) (map[string]any, error)
	SendMessage(senderHandle string, recipientHandles []string, content string, threadID string, intent string, visibility string) (map[string]any, error)
	CreateRoutingRule(name string, routeToHandles []string, mode string, urlContains []string) (map[string]any, error)
	AckMessage(messageID string, recipientHandle string) (map[string]any, error)
	DecideDelivery(deliveryID string, agentHandle string, decision string, content string, note string) (map[string]any, error)
}

// idempotentMessageClient is optional so older test and embedded clients keep
// implementing Client while the bundled HTTP client can safely retry a
// persisted outbox entry.
type idempotentMessageClient interface {
	SendMessageWithIdempotency(senderHandle string, recipientHandles []string, content string, threadID string, intent string, visibility string, idempotencyKey string) (map[string]any, error)
}

type contextInboxClient interface {
	GetInboxForContext(handle string, limit int) (map[string]any, error)
}

type pagedThreadClient interface {
	GetThreadPage(threadID string, limit int, cursor string) (map[string]any, error)
}

type historyQueryClient interface {
	QueryHistory(query HistoryQuery) (map[string]any, error)
	HistorySummary(days int) (map[string]any, error)
}

type historyDeliveryClient interface {
	HistoryDelivery(deliveryID string) (map[string]any, error)
}

// delegatedReplyClient is implemented by clients that support the versioned,
// idempotent public-reply publication endpoint. It is intentionally optional
// so test doubles and older embedded clients can continue to satisfy Client;
// callers must fail closed when delegated publication is requested without it.
type delegatedReplyClient interface {
	PublishDelegatedReply(deliveryID, publicationKey, taskID, content string) (map[string]any, error)
	DelegatedReplyStatus(deliveryID, publicationKey string) (map[string]any, error)
}

func getInboxForContext(client Client, handle string, limit int) (map[string]any, error) {
	if contextClient, ok := client.(contextInboxClient); ok {
		return contextClient.GetInboxForContext(handle, limit)
	}
	return client.GetInbox(handle, limit)
}

// statusError carries the HTTP status of a rejected request so callers can
// classify failures (e.g. auth) without matching message text.
type statusError struct {
	code    int
	message string
}

func (e *statusError) Error() string { return fmt.Sprintf("%d: %s", e.code, e.message) }

type HTTPClient struct {
	APIURL       string
	SocialAPIURL string
	NodeID       string
	Token        string
	Timeout      time.Duration
	Client       *http.Client
	Context      context.Context
}

func (c *HTTPClient) withContext(ctx context.Context) *HTTPClient {
	clone := *c
	clone.Context = ctx
	return &clone
}

func NewHTTPClient(apiURL string, token string) *HTTPClient {
	return &HTTPClient{
		APIURL:  strings.TrimRight(apiURL, "/"),
		Token:   token,
		Timeout: 10 * time.Second,
		Client:  http.DefaultClient,
	}
}

func (c *HTTPClient) GetAgent(handle string) (map[string]any, error) {
	if c.Token != "" {
		localRuntime, err := c.heartbeat()
		if err != nil {
			return nil, err
		}
		if c.hasPairedRuntime() && localRuntime == nil {
			return nil, fmt.Errorf("authenticated local runtime instructions are unavailable")
		}
		result, err := c.request(http.MethodGet, "/agent/me", nil)
		if err != nil {
			return nil, err
		}
		attachLocalRuntime(result, localRuntime)
		return result, nil
	}
	return c.request(http.MethodGet, "/agents/"+escapePathValue(handle), nil)
}

func (c *HTTPClient) GetInbox(handle string, limit int) (map[string]any, error) {
	return c.GetInboxPage(handle, limit, "")
}

func (c *HTTPClient) GetInboxPage(handle string, limit int, cursor string) (map[string]any, error) {
	query := url.Values{"limit": []string{fmt.Sprintf("%d", limit)}}
	if cursor != "" {
		query.Set("cursor", cursor)
	}
	if c.Token != "" {
		var localRuntime map[string]any
		if cursor == "" {
			localRuntime, _ = c.heartbeat()
		}
		result, err := c.request(http.MethodGet, "/agent/inbox?"+query.Encode(), nil)
		if err != nil {
			return nil, err
		}
		attachLocalRuntime(result, localRuntime)
		return result, nil
	}
	return c.request(http.MethodGet, "/agents/"+escapePathValue(handle)+"/inbox?"+query.Encode(), nil)
}

// GetInboxForContext is used when writing a local handoff file. A paired
// runtime must have a current, authenticated owner instruction set before the
// file is created; callers that only need inbox polling may use GetInbox.
func (c *HTTPClient) GetInboxForContext(handle string, limit int) (map[string]any, error) {
	if c.Token == "" {
		return c.GetInbox(handle, limit)
	}
	localRuntime, err := c.heartbeat()
	if err != nil {
		return nil, err
	}
	if c.hasPairedRuntime() && localRuntime == nil {
		return nil, fmt.Errorf("authenticated local runtime instructions are unavailable")
	}
	return c.getInbox(handle, limit, localRuntime)
}

func (c *HTTPClient) getInbox(handle string, limit int, localRuntime map[string]any) (map[string]any, error) {
	query := url.Values{"limit": []string{fmt.Sprintf("%d", limit)}}
	result, err := c.request(http.MethodGet, "/agent/inbox?"+query.Encode(), nil)
	if err != nil {
		return nil, err
	}
	attachLocalRuntime(result, localRuntime)
	return result, nil
}

func (c *HTTPClient) GetThread(threadID string, limit int) (map[string]any, error) {
	return c.GetThreadPage(threadID, limit, "")
}

func (c *HTTPClient) GetThreadPage(threadID string, limit int, cursor string) (map[string]any, error) {
	query := url.Values{"limit": []string{fmt.Sprintf("%d", limit)}}
	if cursor != "" {
		query.Set("cursor", cursor)
	}
	if c.Token != "" {
		return c.request(http.MethodGet, "/agent/threads/"+escapePathValue(threadID)+"?"+query.Encode(), nil)
	}
	return c.request(http.MethodGet, "/threads/"+escapePathValue(threadID)+"?"+query.Encode(), nil)
}

func (c *HTTPClient) GetThreadContext(threadID string, requesterHandle string) (map[string]any, error) {
	if c.Token != "" {
		return c.request(http.MethodGet, "/agent/threads/"+escapePathValue(threadID)+"/context", nil)
	}
	query := url.Values{"requester_handle": []string{requesterHandle}}
	return c.request(http.MethodGet, "/threads/"+escapePathValue(threadID)+"/context?"+query.Encode(), nil)
}

func (c *HTTPClient) SendMessage(senderHandle string, recipientHandles []string, content string, threadID string, intent string, visibility string) (map[string]any, error) {
	return c.SendMessageWithIdempotency(senderHandle, recipientHandles, content, threadID, intent, visibility, "")
}

func (c *HTTPClient) SendMessageWithIdempotency(senderHandle string, recipientHandles []string, content string, threadID string, intent string, visibility string, idempotencyKey string) (map[string]any, error) {
	body := map[string]any{
		"sender_handle":     senderHandle,
		"recipient_handles": recipientHandles,
		"content":           content,
		"intent":            intent,
		"visibility":        visibility,
	}
	if threadID != "" {
		body["thread_id"] = threadID
	}
	if strings.TrimSpace(idempotencyKey) != "" {
		body["idempotency_key"] = idempotencyKey
	}
	if c.Token != "" {
		delete(body, "sender_handle")
		return c.request(http.MethodPost, "/agent/posts", body)
	}
	return c.request(http.MethodPost, "/messages", body)
}

func (c *HTTPClient) CreateRoutingRule(name string, routeToHandles []string, mode string, urlContains []string) (map[string]any, error) {
	return c.request(http.MethodPost, "/routing-rules", map[string]any{
		"name":             name,
		"route_to_handles": routeToHandles,
		"mode":             mode,
		"url_contains":     urlContains,
	})
}

func (c *HTTPClient) AckMessage(messageID string, recipientHandle string) (map[string]any, error) {
	if c.Token != "" {
		return c.request(http.MethodPost, "/agent/messages/"+escapePathValue(messageID)+"/ack", nil)
	}
	return c.request(http.MethodPost, "/messages/"+escapePathValue(messageID)+"/ack", map[string]any{
		"recipient_handle": recipientHandle,
	})
}

func (c *HTTPClient) DecideDelivery(deliveryID string, agentHandle string, decision string, content string, note string) (map[string]any, error) {
	body := map[string]any{
		"agent_handle": agentHandle,
		"decision":     decision,
	}
	if content != "" {
		body["content"] = content
	}
	if note != "" {
		body["note"] = note
	}
	if c.Token != "" {
		delete(body, "agent_handle")
	}
	path := "/deliveries/" + escapePathValue(deliveryID) + "/decision"
	if c.Token != "" {
		path = "/agent/deliveries/" + escapePathValue(deliveryID) + "/decision"
	}
	return c.request(http.MethodPost, path, body)
}

// PublishDelegatedReply submits the exact content produced by a delegated
// agent. The publication key is the durable idempotency key bound to the
// source delivery and task. This never falls back to the legacy decision
// endpoint because that endpoint is not safe for automatic retries.
func (c *HTTPClient) PublishDelegatedReply(deliveryID, publicationKey, taskID, content string) (map[string]any, error) {
	if c.Token == "" {
		return nil, errors.New("delegated reply publication requires an authenticated local connection")
	}
	if strings.TrimSpace(publicationKey) == "" {
		return nil, errors.New("delegated reply publication requires publication_key")
	}
	if strings.TrimSpace(content) == "" {
		return nil, errors.New("delegated reply content must not be empty")
	}
	body := map[string]any{
		"publication_key": publicationKey,
		"content":         content,
	}
	if strings.TrimSpace(taskID) != "" {
		body["task_id"] = taskID
	}
	return c.request(http.MethodPost, "/agent/deliveries/"+escapePathValue(deliveryID)+"/reply-publications", body)
}

// DelegatedReplyStatus reconciles an uncertain send after a network timeout.
// A missing receipt is returned by the server as a normal 404 statusError;
// callers should surface that distinction instead of retrying blindly.
func (c *HTTPClient) DelegatedReplyStatus(deliveryID, publicationKey string) (map[string]any, error) {
	if c.Token == "" {
		return nil, errors.New("delegated reply status requires an authenticated local connection")
	}
	if strings.TrimSpace(publicationKey) == "" {
		return nil, errors.New("delegated reply status requires publication_key")
	}
	return c.request(http.MethodGet, "/agent/deliveries/"+escapePathValue(deliveryID)+"/reply-publications/"+escapePathValue(publicationKey), nil)
}

func escapePathValue(value string) string {
	return strings.ReplaceAll(url.QueryEscape(value), "+", "%20")
}

func (c *HTTPClient) request(method string, path string, body map[string]any) (map[string]any, error) {
	return c.requestBase(c.APIURL, method, path, body)
}

func (c *HTTPClient) requestBase(baseURL string, method string, path string, body map[string]any) (map[string]any, error) {
	var reader io.Reader
	if body != nil {
		payload, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		reader = bytes.NewReader(payload)
	}

	requestContext := c.Context
	if requestContext == nil {
		requestContext = context.Background()
	}
	req, err := http.NewRequestWithContext(requestContext, method, strings.TrimRight(baseURL, "/")+path, reader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("accept", "application/json")
	req.Header.Set("user-agent", "seagull/0.1")
	if body != nil {
		req.Header.Set("content-type", "application/json")
	}
	if c.Token != "" {
		req.Header.Set("authorization", "Bearer "+c.Token)
	}

	client := c.Client
	if client == nil {
		client = http.DefaultClient
	}
	if c.Timeout > 0 {
		ctx, cancel := context.WithTimeout(req.Context(), c.Timeout)
		req = req.WithContext(ctx)
		defer cancel()
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("502: %w", err)
	}
	defer resp.Body.Close()
	payload, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, &statusError{code: resp.StatusCode, message: string(payload)}
	}
	if len(bytes.TrimSpace(payload)) == 0 {
		return map[string]any{}, nil
	}

	var result map[string]any
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.UseNumber()
	if err := decoder.Decode(&result); err != nil {
		return nil, err
	}
	return result, nil
}

func (c *HTTPClient) heartbeat() (map[string]any, error) {
	if c.SocialAPIURL == "" || c.NodeID == "" || c.Token == "" {
		return nil, nil
	}
	body := map[string]any{}
	body["node_id"] = c.NodeID
	result, err := c.requestBase(c.SocialAPIURL, http.MethodPost, "/local-connections/heartbeat", body)
	if err != nil {
		return nil, err
	}
	return objectValue(result, "local_runtime"), nil
}

func (c *HTTPClient) hasPairedRuntime() bool {
	return c.Token != "" && c.SocialAPIURL != "" && c.NodeID != ""
}

func attachLocalRuntime(result map[string]any, localRuntime map[string]any) {
	if result == nil || localRuntime == nil {
		return
	}
	result["local_runtime"] = localRuntime
	items, ok := result["items"].([]any)
	if !ok {
		return
	}
	for _, raw := range items {
		if item, ok := raw.(map[string]any); ok {
			item["local_runtime"] = localRuntime
		}
	}
}
