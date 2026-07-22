#!/usr/bin/env bash
set -euo pipefail

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
    \"name\": \"$PROBE caller runtime\",
    \"node_id\": \"agent-urls-smoke\"
  }" | tee .local/agent-urls-smoke-sender.json
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
    \"name\": \"$PROBE weather runtime\",
    \"node_id\": \"agent-urls-smoke\"
  }" | tee .local/agent-urls-smoke-recipient.json
echo
echo

SENDER_TOKEN="$(python3 -c 'import json; print(json.load(open(".local/agent-urls-smoke-sender.json"))["token"])')"
RECIPIENT_PATH="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$RECIPIENT_HANDLE")"

echo "Public agent card:"
curl -fsS "$API_URL/agents/$RECIPIENT_PATH" | tee .local/agent-urls-smoke-card.json
echo
echo

RECIPIENT_HANDLE="$RECIPIENT_HANDLE" python3 -c 'import json, os; agent=json.load(open(".local/agent-urls-smoke-card.json"))["agent"]; assert agent["handle"] == os.environ["RECIPIENT_HANDLE"]; assert "webhook_url" not in agent'

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

echo "PASS: public agent URL smoke for $API_URL (final status: $STATUS)"
