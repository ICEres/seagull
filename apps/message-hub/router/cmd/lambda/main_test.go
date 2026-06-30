package main

import (
	"testing"
	"time"
)

func TestParseAgentToken(t *testing.T) {
	tokenID, secret, err := parseAgentToken("sga_tokenid_secret")
	if err != nil {
		t.Fatalf("parseAgentToken returned error: %v", err)
	}
	if tokenID != "tokenid" || secret != "secret" {
		t.Fatalf("unexpected token parts: %q %q", tokenID, secret)
	}

	if _, _, err := parseAgentToken("not-a-token"); err == nil {
		t.Fatal("expected invalid token error")
	}
}

func TestTokenHashMatches(t *testing.T) {
	expected := hashTokenParts("tokenid", "secret")

	if !tokenHashMatches("tokenid", "secret", expected) {
		t.Fatal("expected token hash to match")
	}
	if tokenHashMatches("tokenid", "wrong", expected) {
		t.Fatal("expected token hash mismatch")
	}
}

func TestBearerTokenFromHeaders(t *testing.T) {
	token, err := bearerTokenFromHeaders(map[string]string{"Authorization": "Bearer sga_tokenid_secret"})
	if err != nil {
		t.Fatalf("bearerTokenFromHeaders returned error: %v", err)
	}
	if token != "sga_tokenid_secret" {
		t.Fatalf("unexpected token: %q", token)
	}

	if _, err := bearerTokenFromHeaders(map[string]string{"Authorization": "Basic abc"}); err == nil {
		t.Fatal("expected non-bearer authorization error")
	}
}

func TestHasScope(t *testing.T) {
	if !hasScope([]string{"agent:read", "agent:inbox"}, "agent:inbox") {
		t.Fatal("expected scope match")
	}
	if hasScope([]string{"agent:read"}, "agent:inbox") {
		t.Fatal("expected missing scope")
	}
}

func TestTokenExpired(t *testing.T) {
	now := time.Date(2026, 6, 30, 0, 0, 0, 0, time.UTC)

	if tokenExpired("", now) {
		t.Fatal("empty expiry should not expire")
	}
	if !tokenExpired("not-a-date", now) {
		t.Fatal("invalid expiry should fail closed")
	}
	if !tokenExpired("2026-06-29T23:59:59Z", now) {
		t.Fatal("past expiry should expire")
	}
	if tokenExpired("2026-06-30T00:00:01Z", now) {
		t.Fatal("future expiry should not expire")
	}
}
