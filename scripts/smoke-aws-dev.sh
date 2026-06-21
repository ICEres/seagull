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

echo "Health:"
curl -fsS "$API_URL/health"
echo
echo

echo "Register sender:"
curl -fsS \
  -X POST "$API_URL/agents" \
  -H "content-type: application/json" \
  -d '{
    "handle": "@researcher:seagull.local",
    "display_name": "Researcher"
  }'
echo
echo

echo "Register recipient:"
curl -fsS \
  -X POST "$API_URL/agents" \
  -H "content-type: application/json" \
  -d '{
    "handle": "@reviewer:seagull.local",
    "display_name": "Reviewer"
  }'
echo
echo

echo "Create message:"
curl -fsS \
  -X POST "$API_URL/messages" \
  -H "content-type: application/json" \
  -d '{
    "sender_handle": "@researcher:seagull.local",
    "recipient_handles": ["@reviewer:seagull.local"],
    "intent": "message",
    "visibility": "direct",
    "content": "Hello from the Seagull AWS MVP message hub."
  }' | tee .local/aws-smoke-message.json
echo
echo

MESSAGE_ID="$(python3 -c 'import json; data=json.load(open(".local/aws-smoke-message.json")); print(data["message_id"])')"
THREAD_ID="$(python3 -c 'import json; data=json.load(open(".local/aws-smoke-message.json")); print(data["thread_id"])')"
RECIPIENT_PATH="$(python3 -c 'import urllib.parse; print(urllib.parse.quote("@reviewer:seagull.local", safe=""))')"
SENDER_PATH="$(python3 -c 'import urllib.parse; print(urllib.parse.quote("@researcher:seagull.local", safe=""))')"

python3 -c 'import json; data=json.load(open(".local/aws-smoke-message.json")); assert data["message"]["safety_status"] == "approved"'

echo "Inbox:"
curl -fsS "$API_URL/agents/$RECIPIENT_PATH/inbox?limit=5"
echo
echo

echo "Sent:"
curl -fsS "$API_URL/agents/$SENDER_PATH/sent?limit=5"
echo
echo

echo "Thread:"
curl -fsS "$API_URL/threads/$THREAD_ID?limit=10" | tee .local/aws-smoke-thread-before-reply.json
echo
echo

echo "Thread context:"
curl -fsS "$API_URL/threads/$THREAD_ID/context?limit=5"
echo
echo

echo "Create reply:"
curl -fsS \
  -X POST "$API_URL/messages" \
  -H "content-type: application/json" \
  -d "{
    \"sender_handle\": \"@reviewer:seagull.local\",
    \"recipient_handles\": [\"@researcher:seagull.local\"],
    \"intent\": \"reply\",
    \"visibility\": \"direct\",
    \"thread_id\": \"$THREAD_ID\",
    \"content\": \"Reply from the Seagull AWS Phase 1 loop.\"
  }" | tee .local/aws-smoke-reply.json
echo
echo

REPLY_ID="$(python3 -c 'import json; data=json.load(open(".local/aws-smoke-reply.json")); print(data["message_id"])')"

echo "Thread after reply:"
curl -fsS "$API_URL/threads/$THREAD_ID?limit=10" | tee .local/aws-smoke-thread-after-reply.json
echo
echo

MESSAGE_ID="$MESSAGE_ID" REPLY_ID="$REPLY_ID" python3 -c 'import json, os; thread=json.load(open(".local/aws-smoke-thread-after-reply.json")); ids=[m["message_id"] for m in thread["messages"]]; assert os.environ["MESSAGE_ID"] in ids and os.environ["REPLY_ID"] in ids'

echo "Ack:"
curl -fsS \
  -X POST "$API_URL/messages/$MESSAGE_ID/ack" \
  -H "content-type: application/json" \
  -d '{
    "recipient_handle": "@reviewer:seagull.local"
  }'
echo

echo
echo "Blocked safety check:"
BLOCKED_STATUS="$(
  curl -sS \
    -o .local/aws-smoke-blocked.json \
    -w "%{http_code}" \
    -X POST "$API_URL/messages" \
    -H "content-type: application/json" \
    -d '{
      "sender_handle": "@researcher:seagull.local",
      "recipient_handles": ["@reviewer:seagull.local"],
      "intent": "message",
      "visibility": "direct",
      "content": "unsafe: this should be blocked before delivery."
    }'
)"
cat .local/aws-smoke-blocked.json
echo
if [ "$BLOCKED_STATUS" != "403" ]; then
  echo "expected blocked message to return 403, got $BLOCKED_STATUS" >&2
  exit 1
fi
