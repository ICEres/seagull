#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_URL="${1:-}"
if [ -z "$API_URL" ]; then
  API_URL="$(terraform -chdir=infra/terraform/envs/dev output -raw social_api_url)"
fi

AUTH_TOKEN="${SOCIAL_API_BEARER_TOKEN:-${SOCIAL_API_TOKEN:-}}"
AUTH_CURL_ARGS=()
if [ -n "$AUTH_TOKEN" ]; then
  AUTH_CURL_ARGS=(-H "authorization: Bearer $AUTH_TOKEN")
fi

mkdir -p .local

PROBE="social-smoke-$(date +%s)"
ALICE_SUBJECT="alice-$PROBE"
BOB_SUBJECT="bob-$PROBE"
RESEARCHER_HANDLE="@researcher-$PROBE:seagull.local"
REVIEWER_HANDLE="@reviewer-$PROBE:seagull.local"
ROOM_SLUG="room-$PROBE"

echo "Health:"
curl -fsS "$API_URL/health"
echo
echo

echo "CORS preflight:"
curl -fsS \
  -X OPTIONS "$API_URL/posts" \
  -H "origin: http://127.0.0.1:5173" \
  -H "access-control-request-method: POST" \
  -H "access-control-request-headers: authorization,content-type" \
  -D .local/social-smoke-cors-headers.txt \
  -o /dev/null
python3 -c 'headers=open(".local/social-smoke-cors-headers.txt").read().lower(); assert "204" in headers.splitlines()[0]; assert "access-control-allow-origin" in headers; assert "authorization" in headers'
cat .local/social-smoke-cors-headers.txt | sed -n '1,6p'
echo

if [ -n "$AUTH_TOKEN" ]; then
  echo "Current authenticated user:"
  curl -fsS "${AUTH_CURL_ARGS[@]}" "$API_URL/me" | tee .local/social-smoke-alice.json
  echo
  echo

  ALICE_USER_ID="$(python3 -c 'import json; print(json.load(open(".local/social-smoke-alice.json"))["identity"]["user_id"])')"
  BOB_USER_ID="$ALICE_USER_ID"
else
  echo "Identify Alice:"
  curl -fsS \
    -X POST "$API_URL/identities" \
    -H "content-type: application/json" \
    -d "{
      \"provider\": \"local\",
      \"subject\": \"$ALICE_SUBJECT\",
      \"email\": \"$ALICE_SUBJECT@example.com\",
      \"display_name\": \"Alice\"
    }" | tee .local/social-smoke-alice.json
  echo
  echo

  echo "Identify Bob:"
  curl -fsS \
    -X POST "$API_URL/identities" \
    -H "content-type: application/json" \
    -d "{
      \"provider\": \"local\",
      \"subject\": \"$BOB_SUBJECT\",
      \"email\": \"$BOB_SUBJECT@example.com\",
      \"display_name\": \"Bob\"
    }" | tee .local/social-smoke-bob.json
  echo
  echo

  ALICE_USER_ID="$(python3 -c 'import json; print(json.load(open(".local/social-smoke-alice.json"))["identity"]["user_id"])')"
  BOB_USER_ID="$(python3 -c 'import json; print(json.load(open(".local/social-smoke-bob.json"))["identity"]["user_id"])')"
fi

echo "Create researcher profile:"
curl -fsS \
  "${AUTH_CURL_ARGS[@]}" \
  -X POST "$API_URL/profiles" \
  -H "content-type: application/json" \
  -d "{
    \"owner_user_id\": \"$ALICE_USER_ID\",
    \"handle\": \"$RESEARCHER_HANDLE\",
    \"display_name\": \"Researcher\",
    \"capabilities\": [\"research\", \"planning\"]
  }" | tee .local/social-smoke-researcher.json
echo
echo

echo "Create reviewer profile:"
curl -fsS \
  "${AUTH_CURL_ARGS[@]}" \
  -X POST "$API_URL/profiles" \
  -H "content-type: application/json" \
  -d "{
    \"owner_user_id\": \"$BOB_USER_ID\",
    \"handle\": \"$REVIEWER_HANDLE\",
    \"display_name\": \"Reviewer\",
    \"capabilities\": [\"review\"]
  }" | tee .local/social-smoke-reviewer.json
echo
echo

echo "Create room:"
curl -fsS \
  "${AUTH_CURL_ARGS[@]}" \
  -X POST "$API_URL/rooms" \
  -H "content-type: application/json" \
  -d "{
    \"owner_user_id\": \"$ALICE_USER_ID\",
    \"slug\": \"$ROOM_SLUG\",
    \"name\": \"Smoke Room\"
  }" | tee .local/social-smoke-room.json
echo
echo

echo "Join room:"
curl -fsS \
  "${AUTH_CURL_ARGS[@]}" \
  -X POST "$API_URL/rooms/$ROOM_SLUG/memberships" \
  -H "content-type: application/json" \
  -d "{
    \"owner_user_id\": \"$ALICE_USER_ID\",
    \"agent_handle\": \"$RESEARCHER_HANDLE\"
  }" | tee .local/social-smoke-membership.json
echo
echo

echo "Follow reviewer:"
curl -fsS \
  "${AUTH_CURL_ARGS[@]}" \
  -X POST "$API_URL/follows" \
  -H "content-type: application/json" \
  -d "{
    \"owner_user_id\": \"$ALICE_USER_ID\",
    \"follower_handle\": \"$RESEARCHER_HANDLE\",
    \"followed_handle\": \"$REVIEWER_HANDLE\"
  }" | tee .local/social-smoke-follow.json
echo
echo

echo "Create mention post:"
curl -fsS \
  "${AUTH_CURL_ARGS[@]}" \
  -X POST "$API_URL/posts" \
  -H "content-type: application/json" \
  -d "{
    \"owner_user_id\": \"$ALICE_USER_ID\",
    \"author_handle\": \"$RESEARCHER_HANDLE\",
    \"content\": \"Can $REVIEWER_HANDLE review this social API deployment?\",
    \"visibility\": \"public\"
  }" | tee .local/social-smoke-post.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/social-smoke-post.json")); assert data["post"]["mention_agent_ids"]'

echo "Feed:"
curl -fsS "${AUTH_CURL_ARGS[@]}" "$API_URL/feed?owner_user_id=$ALICE_USER_ID&limit=5" | tee .local/social-smoke-feed.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/social-smoke-feed.json")); assert data["items"]'

REVIEWER_PATH="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$REVIEWER_HANDLE")"

echo "Notifications:"
curl -fsS "${AUTH_CURL_ARGS[@]}" "$API_URL/profiles/$REVIEWER_PATH/notifications?owner_user_id=$BOB_USER_ID&limit=5" | tee .local/social-smoke-notifications.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/social-smoke-notifications.json")); assert data["items"][0]["notification_type"] == "mention"'

POST_ID="$(python3 -c 'import json; print(json.load(open(".local/social-smoke-post.json"))["post"]["post_id"])')"

echo "Moderation:"
curl -fsS \
  "${AUTH_CURL_ARGS[@]}" \
  -X POST "$API_URL/moderation" \
  -H "content-type: application/json" \
  -d "{
    \"owner_user_id\": \"$ALICE_USER_ID\",
    \"target_type\": \"post\",
    \"target_id\": \"$POST_ID\",
    \"action\": \"report\",
    \"reason\": \"smoke test moderation record\"
  }" | tee .local/social-smoke-moderation.json
echo
echo

python3 -c 'import json; data=json.load(open(".local/social-smoke-moderation.json")); assert data["moderation"]["action"] == "report"'

echo "Social API smoke passed for $API_URL"
