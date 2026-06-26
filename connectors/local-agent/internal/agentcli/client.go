package agentcli

import (
	"bytes"
	"context"
	"encoding/json"
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
	GetThreadContext(threadID string) (map[string]any, error)
	SendMessage(senderHandle string, recipientHandles []string, content string, threadID string, intent string, visibility string) (map[string]any, error)
	AckMessage(messageID string, recipientHandle string) (map[string]any, error)
	DecideDelivery(deliveryID string, agentHandle string, decision string, content string, note string) (map[string]any, error)
}

type HTTPClient struct {
	APIURL  string
	Token   string
	Timeout time.Duration
	Client  *http.Client
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
	return c.request(http.MethodGet, "/agents/"+escapePathValue(handle), nil)
}

func (c *HTTPClient) GetInbox(handle string, limit int) (map[string]any, error) {
	query := url.Values{"limit": []string{fmt.Sprintf("%d", limit)}}
	return c.request(http.MethodGet, "/agents/"+escapePathValue(handle)+"/inbox?"+query.Encode(), nil)
}

func (c *HTTPClient) GetThread(threadID string, limit int) (map[string]any, error) {
	query := url.Values{"limit": []string{fmt.Sprintf("%d", limit)}}
	return c.request(http.MethodGet, "/threads/"+escapePathValue(threadID)+"?"+query.Encode(), nil)
}

func (c *HTTPClient) GetThreadContext(threadID string) (map[string]any, error) {
	return c.request(http.MethodGet, "/threads/"+escapePathValue(threadID)+"/context", nil)
}

func (c *HTTPClient) SendMessage(senderHandle string, recipientHandles []string, content string, threadID string, intent string, visibility string) (map[string]any, error) {
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
	return c.request(http.MethodPost, "/messages", body)
}

func (c *HTTPClient) AckMessage(messageID string, recipientHandle string) (map[string]any, error) {
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
	return c.request(http.MethodPost, "/deliveries/"+escapePathValue(deliveryID)+"/decision", body)
}

func escapePathValue(value string) string {
	return strings.ReplaceAll(url.QueryEscape(value), "+", "%20")
}

func (c *HTTPClient) request(method string, path string, body map[string]any) (map[string]any, error) {
	var reader io.Reader
	if body != nil {
		payload, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		reader = bytes.NewReader(payload)
	}

	req, err := http.NewRequest(method, c.APIURL+path, reader)
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
		return nil, fmt.Errorf("%d: %s", resp.StatusCode, string(payload))
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
