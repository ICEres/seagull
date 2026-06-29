#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

WEB_URL="${1:-}"
if [ -z "$WEB_URL" ]; then
  WEB_URL="$(terraform -chdir=infra/terraform/envs/dev output -raw web_url)"
fi

SOCIAL_API_URL="$(terraform -chdir=infra/terraform/envs/dev output -raw social_api_url)"
MESSAGE_API_URL="$(terraform -chdir=infra/terraform/envs/dev output -raw message_api_url)"
ADMIN_WEB_URL="$(terraform -chdir=infra/terraform/envs/dev output -raw admin_web_url 2>/dev/null || true)"
SOCIAL_AUTH_CLIENT_ID="$(terraform -chdir=infra/terraform/envs/dev output -raw social_auth_client_id)"

mkdir -p .local

fetch() {
  local url="$1"
  local output="$2"
  local host
  local authoritative_ip
  local curl_args=()

  host="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlparse(sys.argv[1]).hostname or "")' "$url")"
  if [ -n "$host" ] && ! python3 -c 'import socket, sys; socket.getaddrinfo(sys.argv[1], 443)' "$host" >/dev/null 2>&1; then
    authoritative_ip="$(dig "@${SMOKE_WEB_AUTHORITATIVE_DNS:-1.1.1.1}" "$host" A +short | sed -n '1p' || true)"
    if [ -n "$authoritative_ip" ]; then
      curl_args=(--resolve "$host:443:$authoritative_ip")
    fi
  fi

  curl -fsSL "${curl_args[@]}" "$url" -o "$output"
}

fetch_ready() {
  local url="$1"
  local output="$2"

  for attempt in $(seq 1 30); do
    if fetch "$url" "$output"; then
      if grep -q "<title>Seagull</title>" "$output"; then
        return 0
      fi
    fi

    if [ "$attempt" -eq 30 ]; then
      echo "frontend did not become ready at $url" >&2
      exit 1
    fi

    sleep 10
  done
}

fetch_ready "$WEB_URL/" .local/web-smoke-index.html

fetch "$WEB_URL/config.js" .local/web-smoke-config.js
grep -q "$SOCIAL_API_URL" .local/web-smoke-config.js
grep -q "$MESSAGE_API_URL" .local/web-smoke-config.js
grep -q "$SOCIAL_AUTH_CLIENT_ID" .local/web-smoke-config.js
grep -q '"mode":"cognito"' .local/web-smoke-config.js

fetch "$WEB_URL/inbox" .local/web-smoke-inbox.html
grep -q "<title>Seagull</title>" .local/web-smoke-inbox.html

if [ -n "$ADMIN_WEB_URL" ]; then
  ADMIN_HOST="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlparse(sys.argv[1]).hostname or "")' "$ADMIN_WEB_URL")"
  fetch_ready "$ADMIN_WEB_URL/" .local/web-smoke-admin-index.html
  fetch "$ADMIN_WEB_URL/admin" .local/web-smoke-admin-page.html
  grep -q "<title>Seagull</title>" .local/web-smoke-admin-page.html
  grep -q "$ADMIN_HOST" .local/web-smoke-config.js
fi

echo "Web smoke passed for $WEB_URL"
if [ -n "$ADMIN_WEB_URL" ]; then
  echo "Admin web smoke passed for $ADMIN_WEB_URL"
fi
