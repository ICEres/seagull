package agentcli

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
)

// Credential revisions validate IPC requests; stable connection identities
// partition history so a credential refresh does not erase the local cache.
func historyProfileScope(config Config) string {
	connection := RuntimeProfile{Environment: map[string]string{
		"SEAGULL_API_URL":           config.APIURL,
		"SEAGULL_AGENT_HANDLE":      config.AgentHandle,
		"SEAGULL_AGENT_CONTEXT_DIR": config.ContextDir,
	}}
	identity := strings.Join([]string{profileIdentity(connection), strings.TrimRight(config.SocialAPIURL, "/"), config.NodeID}, "\x00")
	digest := sha256.Sum256([]byte(identity))
	return hex.EncodeToString(digest[:])
}

func isHistoryCommand(args []string) bool {
	for _, arg := range args {
		if arg == "--json" {
			continue
		}
		return arg == "history"
	}
	return false
}

func historyItems(items []map[string]any) []any {
	result := make([]any, len(items))
	for i, item := range items {
		result[i] = item
	}
	return result
}

func (p *runtimeProfile) restoreHistory() error {
	if p.inbox != nil {
		if err := p.history.ImportInboxPageNamed("recent", inboxItems(p.inbox), "", false); err != nil {
			return fmt.Errorf("import inbox snapshot: %w", err)
		}
	}
	page, err := p.history.Query(HistoryQuery{Limit: 100})
	if err != nil {
		return err
	}
	if len(page.Items) > 0 || p.inbox == nil {
		p.inbox = map[string]any{"items": historyItems(page.Items)}
	}
	return nil
}

func (p *runtimeProfile) historyComplete() bool {
	if p.history == nil {
		return false
	}
	state, err := p.history.SyncStateNamed("inbox")
	return err == nil && state.Complete
}

// The live inbox remains bounded and is the only source of notifications.
// History metadata lets the UI refresh its independent paged queries.
func (p *runtimeProfile) historyEnvelope(inbox map[string]any) map[string]any {
	if p.history == nil || inbox == nil {
		return inbox
	}
	copy := make(map[string]any, len(inbox)+3)
	for key, value := range inbox {
		copy[key] = value
	}
	if page, err := p.history.Query(HistoryQuery{Limit: 1}); err == nil {
		copy["history_total"] = page.Total
	}
	copy["history_sync_complete"] = p.historyComplete()
	copy["history_generation"] = p.historyGeneration
	return copy
}

func (p *runtimeProfile) wakeHistorySync() {
	if p.historyWake != nil {
		select {
		case p.historyWake <- struct{}{}:
		default:
		}
	}
}

type inboxHistoryResume struct {
	PageCursor string `json:"page_cursor"`
	AnchorID   string `json:"anchor_id"`
	TargetID   string `json:"target_id"`
}

func (p *runtimeProfile) syncHistoryLoop() {
	for {
		select {
		case <-p.ctx.Done():
			return
		case <-p.historyWake:
		}
		for p.ctx.Err() == nil {
			more, err := p.syncNextHistoryPage(p.ctx)
			if err != nil || !more {
				break
			}
			timer := time.NewTimer(150 * time.Millisecond)
			select {
			case <-p.ctx.Done():
				timer.Stop()
				return
			case <-timer.C:
			}
		}
		// A bounded rotating reconciliation also observes decisions made on
		// another device for deliveries older than the newest inbox page.
		if p.ctx.Err() == nil {
			_ = p.reconcileHistoryPage(p.ctx)
		}
	}
}

func (p *runtimeProfile) syncNextHistoryPage(ctx context.Context) (bool, error) {
	state, err := p.history.SyncStateNamed("inbox")
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return false, err
	}
	err = nil
	var resume inboxHistoryResume
	if state.Cursor != "" {
		if err := json.Unmarshal([]byte(state.Cursor), &resume); err != nil {
			return false, fmt.Errorf("invalid saved inbox sync position: %w", err)
		}
	}
	var page map[string]any
	if resume.PageCursor != "" {
		page, err = p.client.withContext(ctx).GetInboxPage(p.config.AgentHandle, 100, resume.PageCursor)
	} else {
		p.mu.RLock()
		page = p.inbox
		status := p.status
		p.mu.RUnlock()
		if status != "connected" && status != "paused" {
			return false, nil
		}
		anchor, anchorErr := p.history.SyncStateNamed("anchor")
		if anchorErr != nil && !errors.Is(anchorErr, sql.ErrNoRows) {
			return false, anchorErr
		}
		resume.AnchorID = anchor.Cursor
		if items := inboxItems(page); len(items) > 0 {
			resume.TargetID = itemDeliveryID(items[0])
		}
	}
	if err != nil {
		return false, err
	}
	items := inboxItems(page)
	next := stringValue(page, "next_cursor")
	_, paged := page["next_cursor"]
	if _, supported := page["has_more"]; supported {
		paged = true
	}
	reachedAnchor := false
	for _, item := range items {
		if resume.AnchorID != "" && itemDeliveryID(item) == resume.AnchorID {
			reachedAnchor = true
			break
		}
	}
	complete := reachedAnchor || (paged && next == "")
	more := !complete && next != "" && next != resume.PageCursor
	resume.PageCursor = next
	position := ""
	if more {
		payload, _ := json.Marshal(resume)
		position = string(payload)
	}
	if err := p.history.ImportInboxPageNamed("inbox", items, position, complete); err != nil {
		return false, err
	}
	if complete {
		if err := p.history.ImportInboxPageNamed("anchor", nil, resume.TargetID, true); err != nil {
			return false, err
		}
	}
	p.historyChanged()
	return more, nil
}

func (p *runtimeProfile) reconcileHistoryPage(ctx context.Context) error {
	state, err := p.history.SyncStateNamed("reconcile")
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	if state.Complete {
		if checked, err := time.Parse(time.RFC3339Nano, state.UpdatedAt); err == nil && time.Since(checked) < 5*time.Minute {
			return nil
		}
	}
	page, err := p.client.withContext(ctx).GetInboxPage(p.config.AgentHandle, 100, state.Cursor)
	if err != nil {
		return err
	}
	next := stringValue(page, "next_cursor")
	if err := p.history.ImportInboxPageNamed("reconcile", inboxItems(page), next, next == ""); err != nil {
		return err
	}
	p.historyChanged()
	return nil
}

func (p *runtimeProfile) historyChanged() {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.historyGeneration++
	p.emitLocked()
}

func (c *runtimeProfileClient) QueryHistory(query HistoryQuery) (map[string]any, error) {
	if c.profile.history == nil {
		return nil, errors.New("local message history is unavailable")
	}
	page, err := c.profile.history.Query(query)
	if err != nil {
		return nil, err
	}
	return map[string]any{"items": historyItems(page.Items), "next_cursor": page.NextCursor, "total": page.Total, "sync_complete": c.profile.historyComplete()}, nil
}

func (c *runtimeProfileClient) HistorySummary(days int) (map[string]any, error) {
	if c.profile.history == nil {
		return nil, errors.New("local message history is unavailable")
	}
	summary, err := c.profile.history.Summary(days)
	if err != nil {
		return nil, err
	}
	payload, err := json.Marshal(summary)
	if err != nil {
		return nil, err
	}
	var result map[string]any
	if err := json.Unmarshal(payload, &result); err != nil {
		return nil, err
	}
	result["sync_complete"] = c.profile.historyComplete()
	return result, nil
}

func (c *runtimeProfileClient) HistoryDelivery(deliveryID string) (map[string]any, error) {
	if c.profile.history == nil {
		return nil, nil
	}
	item, err := c.profile.history.GetDelivery(deliveryID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	return item, err
}

func (c *runtimeProfileClient) GetThread(threadID string, limit int) (map[string]any, error) {
	return c.GetThreadPage(threadID, limit, "")
}

func (c *runtimeProfileClient) GetThreadPage(threadID string, limit int, cursor string) (map[string]any, error) {
	store := c.profile.history
	if store == nil {
		return c.profile.client.withContext(c.profile.ctx).GetThreadPage(threadID, limit, cursor)
	}
	// Validate the local cursor before reading the network or changing cache.
	cached, err := store.QueryThread(threadID, limit, cursor)
	if err != nil {
		return nil, err
	}
	stateName := "thread:" + threadID
	state, err := store.SyncStateNamed(stateName)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return nil, err
	}
	remoteCursor := ""
	if cursor != "" {
		remoteCursor = state.Cursor
		if remoteCursor == "" {
			delete(cached, "end_cursor")
			return cached, nil
		}
	}
	page, err := c.profile.client.withContext(c.profile.ctx).GetThreadPage(threadID, 100, remoteCursor)
	if err != nil {
		if isRuntimeAuthorizationError(err) || len(threadMessages(cached)) == 0 {
			return nil, err
		}
		cached["offline"] = true
		delete(cached, "end_cursor")
		return cached, nil
	}
	next := stringValue(page, "next_cursor")
	if err := store.SaveThread(threadID, page, next); err != nil {
		return nil, err
	}
	if err := store.ImportInboxPageNamed(stateName, nil, next, next == ""); err != nil {
		return nil, err
	}
	result, err := store.QueryThread(threadID, limit, cursor)
	if err != nil {
		return nil, err
	}
	if stringValue(result, "next_cursor") == "" && next != "" {
		result["next_cursor"] = stringValue(result, "end_cursor")
	}
	delete(result, "end_cursor")
	return result, nil
}

func threadMessages(payload map[string]any) []any {
	messages, _ := payload["messages"].([]any)
	return messages
}

func (c *runtimeProfileClient) DecideDelivery(deliveryID, handle, decision, content, note string) (map[string]any, error) {
	result, err := c.Client.DecideDelivery(deliveryID, handle, decision, content, note)
	if err == nil {
		c.updateHistoryDelivery(deliveryID, objectValue(result, "delivery"))
	}
	return result, err
}

// These explicit passthroughs are required because runtimeProfileClient embeds
// the narrow Client interface. Without them a resident runtime hides the
// HTTP client's delegated publication capability from the command dispatcher.
func (c *runtimeProfileClient) PublishDelegatedReply(deliveryID, publicationKey, taskID, content string) (map[string]any, error) {
	delegated, ok := c.Client.(delegatedReplyClient)
	if !ok {
		return nil, errors.New("delegated reply publication is unavailable for this connection; refusing legacy fallback")
	}
	result, err := delegated.PublishDelegatedReply(deliveryID, publicationKey, taskID, content)
	if err == nil {
		c.updateHistoryDelivery(deliveryID, objectValue(result, "delivery"))
	}
	return result, err
}

func (c *runtimeProfileClient) DelegatedReplyStatus(deliveryID, publicationKey string) (map[string]any, error) {
	delegated, ok := c.Client.(delegatedReplyClient)
	if !ok {
		return nil, errors.New("delegated reply status is unavailable for this connection")
	}
	return delegated.DelegatedReplyStatus(deliveryID, publicationKey)
}

func (c *runtimeProfileClient) AckMessage(messageID, handle string) (map[string]any, error) {
	result, err := c.Client.AckMessage(messageID, handle)
	if err == nil {
		if deliveries, ok := result["deliveries"].([]any); ok {
			for _, value := range deliveries {
				if delivery, ok := value.(map[string]any); ok {
					c.updateHistoryDelivery(stringValue(delivery, "delivery_id"), delivery)
				}
			}
		}
	}
	return result, err
}

func (c *runtimeProfileClient) updateHistoryDelivery(id string, delivery map[string]any) {
	if c.profile.history == nil || id == "" || delivery == nil {
		return
	}
	item, err := c.profile.history.GetDelivery(id)
	if err != nil {
		return
	}
	merged := objectValue(item, "delivery")
	for key, value := range delivery {
		merged[key] = value
	}
	item["delivery"] = merged
	if c.profile.history.ImportInboxPageNamed("decisions", []map[string]any{item}, "", false) == nil {
		c.profile.historyChanged()
	}
}
