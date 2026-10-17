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

PROBE="aws-smoke-$(date +%s)"
SENDER_HANDLE="@researcher-$PROBE:seagull.local"
RECIPIENT_HANDLE="@reviewer-$PROBE:seagull.local"

echo "Health:"
curl -fsS "$API_URL/health"
echo
echo

echo "Register sender and issue runtime token:"
curl -fsS \
  -X POST "$API_URL/agent-registrations" \
  -H "content-type: application/json" \
  -d "{
    \"handle\": \"$SENDER_HANDLE\",
    \"display_name\": \"Researcher\",
    \"scopes\": [\"agent:read\", \"agent:inbox\", \"agent:post\", \"agent:ack\"],
    \"name\": \"$PROBE researcher runtime\"
  }" -o .local/aws-smoke-sender-registration.json
echo "Registered sender: $SENDER_HANDLE"
echo
echo

echo "Register recipient and issue runtime token:"
curl -fsS \
  -X POST "$API_URL/agent-registrations" \
  -H "content-type: application/json" \
  -d "{
    \"handle\": \"$RECIPIENT_HANDLE\",
    \"display_name\": \"Reviewer\",
    \"scopes\": [\"agent:read\", \"agent:inbox\", \"agent:post\", \"agent:ack\"],
    \"name\": \"$PROBE reviewer runtime\"
  }" -o .local/aws-smoke-recipient-registration.json
echo "Registered recipient: $RECIPIENT_HANDLE"
echo
echo

SENDER_TOKEN="$(python3 -c 'import json; data=json.load(open(".local/aws-smoke-sender-registration.json")); print(data["token"])')"
RECIPIENT_TOKEN="$(python3 -c 'import json; data=json.load(open(".local/aws-smoke-recipient-registration.json")); print(data["token"])')"
python3 -c 'import json; data=json.load(open(".local/aws-smoke-recipient-registration.json")); assert "token_hash" not in data["record"]; assert data["token"].startswith("sga_")'

echo "Agent me:"
curl -fsS \
  "$API_URL/agent/me" \
  -H "authorization: Bearer $RECIPIENT_TOKEN" | tee .local/aws-smoke-agent-me.json
echo
echo

echo "Create runtime post:"
curl -fsS \
  -X POST "$API_URL/agent/posts" \
  -H "content-type: application/json" \
  -H "authorization: Bearer $SENDER_TOKEN" \
  -d "{
    \"sender_handle\": \"@spoofed:seagull.local\",
    \"recipient_handles\": [\"$RECIPIENT_HANDLE\"],
    \"intent\": \"message\",
    \"visibility\": \"direct\",
    \"content\": \"Hello from the Seagull AWS MVP message hub.\"
  }" | tee .local/aws-smoke-message.json
echo
echo

MESSAGE_ID="$(python3 -c 'import json; data=json.load(open(".local/aws-smoke-message.json")); print(data["message_id"])')"
THREAD_ID="$(python3 -c 'import json; data=json.load(open(".local/aws-smoke-message.json")); print(data["thread_id"])')"
DELIVERY_ID="$(python3 -c 'import json; data=json.load(open(".local/aws-smoke-message.json")); print(data["deliveries"][0]["delivery_id"])')"

python3 -c 'import json; data=json.load(open(".local/aws-smoke-message.json")); sender=json.load(open(".local/aws-smoke-sender-registration.json")); assert data["message"]["safety_status"] == "approved"; assert data["message"]["sender_agent_id"] == sender["agent"]["agent_id"]'

echo "Runtime inbox:"
for attempt in 1 2 3 4 5 6; do
  curl -fsS \
    "$API_URL/agent/inbox?limit=5" \
    -H "authorization: Bearer $RECIPIENT_TOKEN" -o .local/aws-smoke-inbox.json
  if MESSAGE_ID="$MESSAGE_ID" python3 -c 'import json, os, sys; data=json.load(open(".local/aws-smoke-inbox.json")); sys.exit(not any(item["message"]["message_id"] == os.environ["MESSAGE_ID"] for item in data["items"]))'; then
    break
  fi
  sleep 1
done
cat .local/aws-smoke-inbox.json
echo
echo

MESSAGE_ID="$MESSAGE_ID" python3 -c 'import json, os; data=json.load(open(".local/aws-smoke-inbox.json")); ids=[item["message"]["message_id"] for item in data["items"]]; assert os.environ["MESSAGE_ID"] in ids'

echo "Runtime delivery decision reply:"
curl -fsS \
  -X POST "$API_URL/agent/deliveries/$DELIVERY_ID/decision" \
  -H "content-type: application/json" \
  -H "authorization: Bearer $RECIPIENT_TOKEN" \
  -d "{
    \"agent_handle\": \"@spoofed:seagull.local\",
    \"decision\": \"reply\",
    \"content\": \"Reply from the Seagull AWS Phase 1 loop.\"
  }" | tee .local/aws-smoke-decision.json
echo
echo

THREAD_ID="$THREAD_ID" python3 -c 'import json, os; data=json.load(open(".local/aws-smoke-decision.json")); recipient=json.load(open(".local/aws-smoke-recipient-registration.json")); assert data["delivery"]["status"] == "replied"; assert data["reply"]["thread_id"] == os.environ["THREAD_ID"]; assert data["reply"]["message"]["sender_agent_id"] == recipient["agent"]["agent_id"]'

echo "Runtime ack:"
curl -fsS \
  -X POST "$API_URL/agent/deliveries/$DELIVERY_ID/ack" \
  -H "authorization: Bearer $RECIPIENT_TOKEN" | tee .local/aws-smoke-ack.json
echo

python3 -c 'import json; data=json.load(open(".local/aws-smoke-ack.json")); assert data["delivery"]["status"] == "acked"'

echo
echo "Blocked safety check:"
BLOCKED_STATUS="$(
  curl -sS \
    -o .local/aws-smoke-blocked.json \
    -w "%{http_code}" \
    -X POST "$API_URL/agent/posts" \
    -H "content-type: application/json" \
    -H "authorization: Bearer $SENDER_TOKEN" \
    -d "{
      \"recipient_handles\": [\"$RECIPIENT_HANDLE\"],
      \"intent\": \"message\",
      \"visibility\": \"direct\",
      \"content\": \"unsafe: this should be blocked before delivery.\"
    }"
)"
cat .local/aws-smoke-blocked.json
echo
if [ "$BLOCKED_STATUS" != "403" ]; then
  echo "expected blocked message to return 403, got $BLOCKED_STATUS" >&2
  exit 1
fi
