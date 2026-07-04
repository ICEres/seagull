#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_URL="${1:-}"
if [ -z "$API_URL" ]; then
  API_URL="$(terraform -chdir=infra/terraform/envs/dev output -raw ai_provider_api_url)"
fi

ADMIN_SECRET="${AI_PROVIDER_ADMIN_SECRET:-}"
AUTH_TOKEN="${AI_PROVIDER_BEARER_TOKEN:-${SOCIAL_API_BEARER_TOKEN:-}}"
MESSAGE_API_URL="${MESSAGE_API_URL:-}"
if [ -z "$MESSAGE_API_URL" ]; then
  MESSAGE_API_URL="$(terraform -chdir=infra/terraform/envs/dev output -raw message_api_url)"
fi

mkdir -p .local

echo "Health:"
curl -fsS "$API_URL/health" | tee .local/ai-provider-smoke-health.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/ai-provider-smoke-health.json")); assert data["ok"] is True; assert data["storage"] == "dynamodb"'

if [ -z "$ADMIN_SECRET" ]; then
  echo "AI provider health smoke passed for $API_URL"
  echo "Set AI_PROVIDER_ADMIN_SECRET for credit/run smoke."
  exit 0
fi

PROBE="ai-smoke-$(date +%s)"
OWNER_ID="owner-$PROBE"
AGENT_ID="agent-$PROBE"
AUTH_CURL_ARGS=()
if [ -n "$AUTH_TOKEN" ]; then
  AUTH_CURL_ARGS=(-H "authorization: Bearer $AUTH_TOKEN")
fi

echo "Grant server credits:"
curl -fsS \
  -X POST "$API_URL/admin/ai-credits/server-grants" \
  -H "content-type: application/json" \
  -H "x-seagull-admin-secret: $ADMIN_SECRET" \
  "${AUTH_CURL_ARGS[@]}" \
  -d "{
    \"admin_actor_id\": \"ci-ai-smoke\",
    \"credit_amount\": 100,
    \"reason\": \"$PROBE server grant\"
  }" | tee .local/ai-provider-smoke-server-grant.json
echo
echo

echo "Grant owner credits:"
curl -fsS \
  -X POST "$API_URL/owners/$OWNER_ID/ai-credits/grants" \
  -H "content-type: application/json" \
  -H "x-seagull-admin-secret: $ADMIN_SECRET" \
  "${AUTH_CURL_ARGS[@]}" \
  -d "{
    \"admin_actor_id\": \"ci-ai-smoke\",
    \"credit_amount\": 100,
    \"reason\": \"$PROBE owner grant\"
  }" | tee .local/ai-provider-smoke-owner-grant.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/ai-provider-smoke-owner-grant.json")); assert data["entry"]["credit_delta"] == 100'

echo "Create fake AI run:"
curl -fsS \
  -X POST "$API_URL/ai-runs" \
  -H "content-type: application/json" \
  -H "x-seagull-admin-secret: $ADMIN_SECRET" \
  "${AUTH_CURL_ARGS[@]}" \
  -d "{
    \"provider\": \"fake\",
    \"model\": \"fake-small\",
    \"actor_agent_id\": \"$AGENT_ID\",
    \"owner_user_id\": \"$OWNER_ID\",
    \"input_messages\": [
      {\"role\": \"user\", \"content\": \"hello from deployed smoke\"}
    ],
    \"max_output_tokens\": 8,
    \"trace_id\": \"$PROBE\"
  }" | tee .local/ai-provider-smoke-run.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/ai-provider-smoke-run.json")); run=data["run"]; assert run["state"] == "completed"; assert run["usage_id"]; assert "Fake response" in run["output_text"]'

echo "Owner credit balance:"
curl -fsS \
  "$API_URL/owners/$OWNER_ID/ai-credits/balance" \
  -H "x-seagull-admin-secret: $ADMIN_SECRET" \
  "${AUTH_CURL_ARGS[@]}" | tee .local/ai-provider-smoke-balance.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/ai-provider-smoke-balance.json")); assert data["balance"]["available_credits"] < 100'

REQUESTER_HANDLE="@ai-smoke-requester-$PROBE:seagull.local"
RESPONDER_HANDLE="@ai-smoke-responder-$PROBE:seagull.local"

echo "Register message-hub requester:"
curl -fsS \
  -X POST "$MESSAGE_API_URL/agent-registrations" \
  -H "content-type: application/json" \
  -d "{
    \"handle\": \"$REQUESTER_HANDLE\",
    \"display_name\": \"AI smoke requester\",
    \"scopes\": [\"agent:read\", \"agent:inbox\", \"agent:post\", \"agent:ack\"],
    \"name\": \"$PROBE requester runtime\",
    \"node_id\": \"ai-provider-smoke\"
  }" | tee .local/ai-provider-smoke-requester-registration.json
echo
echo

echo "Register message-hub responder:"
curl -fsS \
  -X POST "$MESSAGE_API_URL/agent-registrations" \
  -H "content-type: application/json" \
  -d "{
    \"handle\": \"$RESPONDER_HANDLE\",
    \"display_name\": \"AI smoke responder\",
    \"scopes\": [\"agent:read\", \"agent:inbox\", \"agent:post\", \"agent:ack\"],
    \"name\": \"$PROBE responder runtime\",
    \"node_id\": \"ai-provider-smoke\"
  }" | tee .local/ai-provider-smoke-responder-registration.json
echo
echo

REQUESTER_TOKEN="$(python3 -c 'import json; print(json.load(open(".local/ai-provider-smoke-requester-registration.json"))["token"])')"
RESPONDER_TOKEN="$(python3 -c 'import json; print(json.load(open(".local/ai-provider-smoke-responder-registration.json"))["token"])')"
RESPONDER_AGENT_ID="$(python3 -c 'import json; print(json.load(open(".local/ai-provider-smoke-responder-registration.json"))["agent"]["agent_id"])')"

echo "Create message-hub task:"
curl -fsS \
  -X POST "$MESSAGE_API_URL/agent/tasks" \
  -H "content-type: application/json" \
  -H "authorization: Bearer $REQUESTER_TOKEN" \
  -d "{
    \"recipient_handle\": \"$RESPONDER_HANDLE\",
    \"objective\": \"Summarize this async AI provider smoke task.\"
  }" | tee .local/ai-provider-smoke-task.json
echo
echo

TASK_ID="$(python3 -c 'import json; print(json.load(open(".local/ai-provider-smoke-task.json"))["task_id"])')"
TASK_MESSAGE_ID="$(python3 -c 'import json; print(json.load(open(".local/ai-provider-smoke-task.json"))["task"]["request_message_id"])')"

echo "Accept message-hub task:"
curl -fsS \
  -X POST "$MESSAGE_API_URL/agent/tasks/$TASK_ID/accept" \
  -H "content-type: application/json" \
  -H "authorization: Bearer $RESPONDER_TOKEN" \
  -d '{}' | tee .local/ai-provider-smoke-task-accept.json
echo
echo

echo "Create queued fake AI run:"
curl -fsS \
  -X POST "$API_URL/ai-runs" \
  -H "content-type: application/json" \
  -H "x-seagull-admin-secret: $ADMIN_SECRET" \
  "${AUTH_CURL_ARGS[@]}" \
  -d "{
    \"async\": true,
    \"provider\": \"fake\",
    \"model\": \"fake-small\",
    \"actor_agent_id\": \"$RESPONDER_AGENT_ID\",
    \"owner_user_id\": \"$OWNER_ID\",
    \"input_messages\": [
      {\"role\": \"user\", \"content\": \"Summarize this async AI provider smoke task.\"}
    ],
    \"max_output_tokens\": 8,
    \"task_id\": \"$TASK_ID\",
    \"message_id\": \"$TASK_MESSAGE_ID\",
    \"trace_id\": \"$PROBE-async\",
    \"idempotency_key\": \"$PROBE-async\",
    \"message_hub\": {
      \"responder_handle\": \"$RESPONDER_HANDLE\",
      \"agent_token\": \"$RESPONDER_TOKEN\"
    }
  }" | tee .local/ai-provider-smoke-queued-run.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/ai-provider-smoke-queued-run.json")); assert data["queued"] is True; assert data["run"]["state"] == "queued"'
ASYNC_RUN_ID="$(python3 -c 'import json; print(json.load(open(".local/ai-provider-smoke-queued-run.json"))["run"]["run_id"])')"

echo "Wait for queued AI run:"
for _ in $(seq 1 30); do
  curl -fsS \
    "$API_URL/ai-runs/$ASYNC_RUN_ID" \
    -H "x-seagull-admin-secret: $ADMIN_SECRET" \
    "${AUTH_CURL_ARGS[@]}" | tee .local/ai-provider-smoke-async-run.json
  echo
  ASYNC_STATE="$(python3 -c 'import json; print(json.load(open(".local/ai-provider-smoke-async-run.json"))["run"]["state"])')"
  if [ "$ASYNC_STATE" = "completed" ]; then
    break
  fi
  sleep 2
done
python3 -c 'import json; data=json.load(open(".local/ai-provider-smoke-async-run.json")); run=data["run"]; assert run["state"] == "completed"; assert run["usage_id"]; assert "Fake response" in run["output_text"]'

echo "Wait for message-hub task result:"
for _ in $(seq 1 30); do
  curl -fsS \
    "$MESSAGE_API_URL/agent/inbox?limit=10" \
    -H "authorization: Bearer $REQUESTER_TOKEN" | tee .local/ai-provider-smoke-requester-inbox.json
  echo
  if TASK_ID="$TASK_ID" python3 - <<'PY'
import json
import os
data = json.load(open(".local/ai-provider-smoke-requester-inbox.json"))
needle = f"seagull://tasks/{os.environ['TASK_ID']}/results/"
for item in data.get("items", []):
    message = item.get("message", {})
    if message.get("intent") == "task_result":
        for ref in message.get("refs", []):
            if isinstance(ref, dict) and str(ref.get("url", "")).startswith(needle):
                raise SystemExit(0)
raise SystemExit(1)
PY
  then
    break
  fi
  sleep 2
done
TASK_ID="$TASK_ID" python3 - <<'PY'
import json
import os
data = json.load(open(".local/ai-provider-smoke-requester-inbox.json"))
needle = f"seagull://tasks/{os.environ['TASK_ID']}/results/"
for item in data.get("items", []):
    message = item.get("message", {})
    if message.get("intent") == "task_result":
        for ref in message.get("refs", []):
            if isinstance(ref, dict) and str(ref.get("url", "")).startswith(needle):
                raise SystemExit(0)
raise AssertionError("task result was not delivered to message hub")
PY

echo "AI provider smoke passed for $API_URL"
