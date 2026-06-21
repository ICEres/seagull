#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT_DIR/infra/terraform/envs/dev"

AWS_PROFILE="${AWS_PROFILE:-personal}"
AWS_REGION="${AWS_REGION:-ap-southeast-2}"
ALICE_PASSWORD="${SEAGULL_ALICE_PASSWORD:-}"
BOB_PASSWORD="${SEAGULL_BOB_PASSWORD:-}"

if [[ -z "$ALICE_PASSWORD" || -z "$BOB_PASSWORD" ]]; then
  echo "Set SEAGULL_ALICE_PASSWORD and SEAGULL_BOB_PASSWORD before running this script." >&2
  exit 1
fi

MESSAGE_API_URL="$(terraform -chdir="$TF_DIR" output -raw message_api_url)"
USER_POOL_ID="$(terraform -chdir="$TF_DIR" output -raw mcp_oauth_user_pool_id)"
SCOPES="agents:read,messages:read,messages:write,messages:ack"

register_agent() {
  local handle="$1"
  local display_name="$2"
  curl -sS -f \
    -X POST "$MESSAGE_API_URL/agents" \
    -H "content-type: application/json" \
    --data "{\"handle\":\"$handle\",\"display_name\":\"$display_name\"}" \
    >/dev/null
}

upsert_user() {
  local username="$1"
  local email="$2"
  local password="$3"
  local owner_user_id="$4"
  local handles="$5"
  local attributes_json

  attributes_json="[
    {\"Name\":\"email\",\"Value\":\"$email\"},
    {\"Name\":\"email_verified\",\"Value\":\"true\"},
    {\"Name\":\"custom:sg_owner_id\",\"Value\":\"$owner_user_id\"},
    {\"Name\":\"custom:sg_handles\",\"Value\":\"$handles\"},
    {\"Name\":\"custom:sg_scopes\",\"Value\":\"$SCOPES\"}
  ]"

  if ! aws --profile "$AWS_PROFILE" --region "$AWS_REGION" cognito-idp admin-get-user \
    --user-pool-id "$USER_POOL_ID" \
    --username "$username" >/dev/null 2>&1; then
    aws --profile "$AWS_PROFILE" --region "$AWS_REGION" cognito-idp admin-create-user \
      --user-pool-id "$USER_POOL_ID" \
      --username "$username" \
      --message-action SUPPRESS \
      --user-attributes "$attributes_json" \
      >/dev/null
  else
    aws --profile "$AWS_PROFILE" --region "$AWS_REGION" cognito-idp admin-update-user-attributes \
      --user-pool-id "$USER_POOL_ID" \
      --username "$username" \
      --user-attributes "$attributes_json" \
      >/dev/null
  fi

  aws --profile "$AWS_PROFILE" --region "$AWS_REGION" cognito-idp admin-set-user-password \
    --user-pool-id "$USER_POOL_ID" \
    --username "$username" \
    --password "$password" \
    --permanent \
    >/dev/null
}

register_agent "@alice:gulls.ai" "Alice"
register_agent "@bob:gulls.ai" "Bob"

upsert_user "seagull-alice" "seagull-alice@example.com" "$ALICE_PASSWORD" "user_alice" "@alice:gulls.ai"
upsert_user "seagull-bob" "seagull-bob@example.com" "$BOB_PASSWORD" "user_bob" "@bob:gulls.ai"

echo "MCP OAuth demo users are ready."
echo "Alice username: seagull-alice"
echo "Bob username: seagull-bob"
