#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_URL="${1:-}"
if [ -z "$API_URL" ]; then
  if ! API_URL="$(terraform -chdir=infra/terraform/envs/dev output -raw message_api_url 2>/dev/null)"; then
    API_URL="$(terraform -chdir=infra/terraform/envs/dev output -raw api_endpoint)"
  fi
fi

mkdir -p .local

PROBE="agent-urls-smoke-$(date +%s)"
SENDER_HANDLE="@caller-$PROBE:seagull.local"
RECIPIENT_HANDLE="@weather-$PROBE:seagull.local"

echo "Health:"
curl -fsS "$API_URL/health"
echo
echo

echo "Register throwaway sender and issue runtime token:"
curl -fsS \
  -X POST "$API_URL/agent-registrations" \
  -H "content-type: application/json" \
  -d "{
    \"handle\": \"$SENDER_HANDLE\",
    \"display_name\": \"Caller\",
    \"scopes\": [\"agent:read\", \"agent:post\"],
    \"name\": \"$PROBE caller runtime\"
  }" -o .local/agent-urls-smoke-sender.json
echo "Registered sender: $SENDER_HANDLE"
echo
echo

echo "Register throwaway recipient:"
curl -fsS \
  -X POST "$API_URL/agent-registrations" \
  -H "content-type: application/json" \
  -d "{
    \"handle\": \"$RECIPIENT_HANDLE\",
    \"display_name\": \"Weather\",
    \"capabilities\": [\"weather.forecast\"],
    \"scopes\": [\"agent:read\", \"agent:inbox\", \"agent:post\", \"agent:ack\"],
    \"name\": \"$PROBE weather runtime\"
  }" -o .local/agent-urls-smoke-recipient.json
echo "Registered recipient: $RECIPIENT_HANDLE"
echo
echo

SENDER_TOKEN="$(python3 -c 'import json; print(json.load(open(".local/agent-urls-smoke-sender.json"))["token"])')"
RECIPIENT_TOKEN="$(python3 -c 'import json; print(json.load(open(".local/agent-urls-smoke-recipient.json"))["token"])')"
RECIPIENT_PATH="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$RECIPIENT_HANDLE")"

echo "Public agent card:"
curl -fsS "$API_URL/agents/$RECIPIENT_PATH" | tee .local/agent-urls-smoke-card.json
echo
echo

RECIPIENT_HANDLE="$RECIPIENT_HANDLE" python3 -c 'import json, os; agent=json.load(open(".local/agent-urls-smoke-card.json"))["agent"]; assert agent["handle"] == os.environ["RECIPIENT_HANDLE"]; assert "webhook_url" not in agent'

echo "HTML card via Accept negotiation:"
curl -fsS -H "accept: text/html" "$API_URL/agents/$RECIPIENT_PATH" > .local/agent-urls-smoke-card.html
RECIPIENT_HANDLE="$RECIPIENT_HANDLE" python3 -c 'import os; page=open(".local/agent-urls-smoke-card.html").read(); assert page.startswith("<!doctype html>"), page[:80]; assert os.environ["RECIPIENT_HANDLE"] in page'
echo "ok"
echo

echo "Discovery descriptor and handle resolution:"
curl -fsS "$API_URL/.well-known/gulls" | tee .local/agent-urls-smoke-discovery.json
echo
curl -fsS "$API_URL/.well-known/gulls?resource=$RECIPIENT_PATH" | tee .local/agent-urls-smoke-resolution.json
echo
RECIPIENT_HANDLE="$RECIPIENT_HANDLE" python3 <<'PY'
import json, os
descriptor = json.load(open(".local/agent-urls-smoke-discovery.json"))
assert descriptor["service"] == "gulls-message-hub", descriptor
assert descriptor["agent_url_template"] == "/agents/{name}", descriptor
resolution = json.load(open(".local/agent-urls-smoke-resolution.json"))
assert resolution["subject"] == os.environ["RECIPIENT_HANDLE"], resolution
assert any(link["rel"] == "self" for link in resolution["links"]), resolution
PY
echo

echo "Post message to the public agent URL:"
curl -fsS \
  -X POST "$API_URL/agents/$RECIPIENT_PATH/messages" \
  -H "content-type: application/json" \
  -H "authorization: Bearer $SENDER_TOKEN" \
  -H "idempotency-key: $PROBE" \
  -d "{
    \"content\": \"Hello from the public agent URL smoke.\",
    \"intent\": \"message\"
  }" | tee .local/agent-urls-smoke-send.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/agent-urls-smoke-send.json")); assert data["delivery_id"]; assert data["message_id"]; assert data["thread_id"]; assert data["status_url"].startswith("/agents/"); assert data["thread_url"].startswith("/threads/")'

STATUS_URL="$(python3 -c 'import json; print(json.load(open(".local/agent-urls-smoke-send.json"))["status_url"])')"

echo "Replay with the same idempotency key:"
curl -fsS \
  -X POST "$API_URL/agents/$RECIPIENT_PATH/messages" \
  -H "content-type: application/json" \
  -H "authorization: Bearer $SENDER_TOKEN" \
  -H "idempotency-key: $PROBE" \
  -d "{
    \"content\": \"Hello from the public agent URL smoke.\",
    \"intent\": \"message\"
  }" | tee .local/agent-urls-smoke-replay.json
echo
echo

python3 -c 'import json; first=json.load(open(".local/agent-urls-smoke-send.json")); replay=json.load(open(".local/agent-urls-smoke-replay.json")); assert first == replay'

echo "Poll delivery status:"
STATUS=""
for attempt in $(seq 1 10); do
  curl -fsS "$API_URL$STATUS_URL" -H "authorization: Bearer $SENDER_TOKEN" | tee .local/agent-urls-smoke-status.json
  echo
  STATUS="$(python3 -c 'import json; print(json.load(open(".local/agent-urls-smoke-status.json"))["status"])')"
  if [ "$STATUS" = "delivered" ] || [ "$STATUS" = "accepted" ] || [ "$STATUS" = "replied" ]; then
    break
  fi
  echo "status is $STATUS (attempt $attempt); retrying..."
  sleep 2
done

if [ "$STATUS" != "delivered" ] && [ "$STATUS" != "accepted" ] && [ "$STATUS" != "replied" ]; then
  echo "delivery never reached delivered/accepted (last status: $STATUS)" >&2
  exit 1
fi

echo "Guest send is refused under the default contacts_only posture:"
GUEST_REFUSED_CODE="$(curl -sS -o .local/agent-urls-smoke-guest-refused.json -w '%{http_code}' \
  -X POST "$API_URL/agents/$RECIPIENT_PATH/messages" \
  -H "content-type: application/json" \
  -d '{"content": "Guest knock."}')"
if [ "$GUEST_REFUSED_CODE" != "403" ]; then
  echo "expected 403 for a guest send under contacts_only, got $GUEST_REFUSED_CODE" >&2
  cat .local/agent-urls-smoke-guest-refused.json >&2
  exit 1
fi
echo "ok (403)"
echo

echo "Open the inbox posture and send as a guest:"
curl -fsS \
  -X POST "$API_URL/agent/inbox-posture" \
  -H "content-type: application/json" \
  -H "authorization: Bearer $RECIPIENT_TOKEN" \
  -d '{"inbox_posture": "open"}' > /dev/null
curl -fsS \
  -X POST "$API_URL/agents/$RECIPIENT_PATH/messages" \
  -H "content-type: application/json" \
  -d '{"content": "Hello from an anonymous guest."}' | tee .local/agent-urls-smoke-guest-send.json
echo
echo

GUEST_STATUS_URL="$(python3 -c 'import json; data=json.load(open(".local/agent-urls-smoke-guest-send.json")); assert set(data) == {"delivery_id", "status_url"}, data; assert "?token=" in data["status_url"]; print(data["status_url"])')"

echo "Poll the signed guest status URL (no Authorization):"
curl -fsS "$API_URL$GUEST_STATUS_URL" | tee .local/agent-urls-smoke-guest-status.json
echo
python3 -c 'import json; data=json.load(open(".local/agent-urls-smoke-guest-status.json")); assert data["status"] in {"accepted", "quarantined"}, data'
echo

echo "token_required posture: refused without an invite, accepted with one:"
curl -fsS \
  -X POST "$API_URL/agent/inbox-posture" \
  -H "content-type: application/json" \
  -H "authorization: Bearer $RECIPIENT_TOKEN" \
  -d '{"inbox_posture": "token_required"}' > /dev/null
INVITE_REFUSED_CODE="$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST "$API_URL/agents/$RECIPIENT_PATH/messages" \
  -H "content-type: application/json" \
  -d '{"content": "Guest without invite."}')"
if [ "$INVITE_REFUSED_CODE" != "403" ]; then
  echo "expected 403 for a guest send under token_required, got $INVITE_REFUSED_CODE" >&2
  exit 1
fi
curl -fsS \
  -X POST "$API_URL/agent/guest-invites" \
  -H "content-type: application/json" \
  -H "authorization: Bearer $RECIPIENT_TOKEN" \
  -d '{}' | tee .local/agent-urls-smoke-invite.json
echo
INVITE_TOKEN="$(python3 -c 'import json; print(json.load(open(".local/agent-urls-smoke-invite.json"))["invite_token"])')"
curl -fsS \
  -X POST "$API_URL/agents/$RECIPIENT_PATH/messages?invite=$INVITE_TOKEN" \
  -H "content-type: application/json" \
  -d '{"content": "Guest with invite."}' | tee .local/agent-urls-smoke-invite-send.json
echo
python3 -c 'import json; data=json.load(open(".local/agent-urls-smoke-invite-send.json")); assert set(data) == {"delivery_id", "status_url"}, data'
echo

echo "PASS: public agent URL smoke for $API_URL (final status: $STATUS)"
