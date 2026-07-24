package agentcli

import (
	"context"
	"errors"
	"math/rand"
	"net/http"
	"strings"
	"time"

	"github.com/coder/websocket"
)

// Stream support: server->client push of delivery events over WebSocket.
// The model is "push = wake-up, poll = truth": a received event only means
// "check the inbox now"; the inbox fetch remains the source of truth, and
// polling continues as the fallback when the stream is down.

const (
	// API Gateway WebSocket idle timeout is 10 minutes; ping well inside it.
	streamPingInterval = 4*time.Minute + 30*time.Second
	// Backoff for reconnects (API Gateway also hard-drops connections after
	// 2 hours; that just looks like a drop and reconnects here).
	streamBackoffMin    = time.Second
	streamBackoffMax    = time.Minute
	streamStableAfter   = time.Minute
	streamReadLimit     = 1 << 20 // 1MB; events are small, be generous
	streamHandshakeWait = 15 * time.Second
)

// StreamCallbacks receive stream lifecycle and event notifications.
// OnConnect fires on every successful (re)connect — callers should poll there,
// which covers events missed while disconnected. OnEvent receives the raw
// message bytes (treated as a wake-up; no schema is enforced). OnDrop fires
// when an established or attempted connection fails.
type StreamCallbacks struct {
	OnConnect func()
	OnEvent   func(raw []byte)
	OnDrop    func(err error)
}

// RunStream connects to streamURL and keeps the connection alive with pings
// and jittered-backoff reconnects until ctx is cancelled. The bearer token is
// sent as an Authorization header, never in the query string (keeps tokens
// out of API Gateway access logs). Returns only on ctx cancellation or a
// non-retryable error (4xx auth/config rejection on the very first attempt).
func RunStream(ctx context.Context, streamURL string, token string, callbacks StreamCallbacks) error {
	if err := ValidateStreamURL(streamURL); err != nil {
		return err
	}

	backoff := streamBackoffMin
	firstAttempt := true
	for {
		connectedAt := time.Now()
		err := streamOnce(ctx, streamURL, token, callbacks)
		if ctx.Err() != nil {
			return nil
		}
		if firstAttempt && isStreamAuthError(err) {
			// Fail fast on a rejected first connect: the token is missing the
			// agent:inbox scope or the URL is wrong; retrying cannot help.
			return err
		}
		firstAttempt = false
		if callbacks.OnDrop != nil {
			callbacks.OnDrop(err)
		}

		if time.Since(connectedAt) >= streamStableAfter {
			backoff = streamBackoffMin
		}
		jitter := time.Duration(rand.Int63n(int64(backoff) / 2))
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(backoff + jitter):
		}
		if backoff *= 2; backoff > streamBackoffMax {
			backoff = streamBackoffMax
		}
	}
}

func streamOnce(ctx context.Context, streamURL string, token string, callbacks StreamCallbacks) error {
	header := http.Header{}
	if token != "" {
		header.Set("Authorization", "Bearer "+token)
	}

	dialCtx, cancel := context.WithTimeout(ctx, streamHandshakeWait)
	conn, resp, err := websocket.Dial(dialCtx, streamURL, &websocket.DialOptions{HTTPHeader: header})
	cancel()
	if err != nil {
		if resp != nil && (resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden) {
			return &statusError{code: resp.StatusCode, message: err.Error()}
		}
		return err
	}
	defer conn.Close(websocket.StatusNormalClosure, "")
	conn.SetReadLimit(streamReadLimit)

	if callbacks.OnConnect != nil {
		callbacks.OnConnect()
	}

	pingCtx, stopPing := context.WithCancel(ctx)
	defer stopPing()
	go func() {
		ticker := time.NewTicker(streamPingInterval)
		defer ticker.Stop()
		for {
			select {
			case <-pingCtx.Done():
				return
			case <-ticker.C:
				if err := conn.Ping(pingCtx); err != nil {
					return
				}
			}
		}
	}()

	for {
		_, raw, err := conn.Read(ctx)
		if err != nil {
			return err
		}
		if callbacks.OnEvent != nil {
			callbacks.OnEvent(raw)
		}
	}
}

// ValidateStreamURL enforces the ws:// or wss:// scheme.
func ValidateStreamURL(streamURL string) error {
	if strings.HasPrefix(streamURL, "ws://") || strings.HasPrefix(streamURL, "wss://") {
		return nil
	}
	return errors.New("stream URL must start with ws:// or wss://")
}

func isStreamAuthError(err error) bool {
	var status *statusError
	return errors.As(err, &status) &&
		(status.code == http.StatusUnauthorized || status.code == http.StatusForbidden)
}

// NewWakeChannel returns a coalescing wake signal: sends collapse while a
// wake is already pending, so events landing mid-poll trigger exactly one
// follow-up poll.
func NewWakeChannel() chan struct{} {
	return make(chan struct{}, 1)
}

// Wake signals the channel without blocking; a pending wake absorbs it.
func Wake(wake chan struct{}) {
	select {
	case wake <- struct{}{}:
	default:
	}
}
