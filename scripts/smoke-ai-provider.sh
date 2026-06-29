#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_URL="${1:-}"
if [ -z "$API_URL" ]; then
  API_URL="$(terraform -chdir=infra/terraform/envs/dev output -raw ai_provider_api_url)"
fi

ADMIN_SECRET="${AI_PROVIDER_ADMIN_SECRET:-${TF_VAR_ai_provider_admin_secret:-}}"

mkdir -p .local

echo "Health:"
curl -fsS "$API_URL/health" | tee .local/ai-provider-smoke-health.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/ai-provider-smoke-health.json")); assert data["ok"] is True; assert data["storage"] == "dynamodb"'

if [ -z "$ADMIN_SECRET" ]; then
  echo "AI provider health smoke passed for $API_URL"
  echo "Set AI_PROVIDER_ADMIN_SECRET or TF_VAR_ai_provider_admin_secret for credit/run smoke."
  exit 0
fi

PROBE="ai-smoke-$(date +%s)"
OWNER_ID="owner-$PROBE"
AGENT_ID="agent-$PROBE"

echo "Grant server credits:"
curl -fsS \
  -X POST "$API_URL/admin/ai-credits/server-grants" \
  -H "content-type: application/json" \
  -H "x-seagull-admin-secret: $ADMIN_SECRET" \
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
curl -fsS "$API_URL/owners/$OWNER_ID/ai-credits/balance" | tee .local/ai-provider-smoke-balance.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/ai-provider-smoke-balance.json")); assert data["balance"]["available_credits"] < 100'

echo "AI provider smoke passed for $API_URL"
