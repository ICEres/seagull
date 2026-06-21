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
SOCIAL_AUTH_CLIENT_ID="$(terraform -chdir=infra/terraform/envs/dev output -raw social_auth_client_id)"
WEB_HOST="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlparse(sys.argv[1]).hostname or "")' "$WEB_URL")"

mkdir -p .local

curl_args=()
if [ -n "$WEB_HOST" ] && ! python3 -c 'import socket, sys; socket.getaddrinfo(sys.argv[1], 443)' "$WEB_HOST" >/dev/null 2>&1; then
  authoritative_ip="$(dig "@${SMOKE_WEB_AUTHORITATIVE_DNS:-1.1.1.1}" "$WEB_HOST" A +short | sed -n '1p' || true)"
  if [ -n "$authoritative_ip" ]; then
    curl_args=(--resolve "$WEB_HOST:443:$authoritative_ip")
  fi
fi

fetch() {
  if [ "${#curl_args[@]}" -gt 0 ]; then
    curl -fsSL "${curl_args[@]}" "$@"
  else
    curl -fsSL "$@"
  fi
}

for attempt in $(seq 1 30); do
  if fetch "$WEB_URL/" -o .local/web-smoke-index.html; then
    if grep -q "<title>Seagull</title>" .local/web-smoke-index.html; then
      break
    fi
  fi

  if [ "$attempt" -eq 30 ]; then
    echo "frontend did not become ready at $WEB_URL" >&2
    exit 1
  fi

  sleep 10
done

fetch "$WEB_URL/config.js" -o .local/web-smoke-config.js
grep -q "$SOCIAL_API_URL" .local/web-smoke-config.js
grep -q "$MESSAGE_API_URL" .local/web-smoke-config.js
grep -q "$SOCIAL_AUTH_CLIENT_ID" .local/web-smoke-config.js
grep -q '"mode":"cognito"' .local/web-smoke-config.js

fetch "$WEB_URL/inbox" -o .local/web-smoke-inbox.html
grep -q "<title>Seagull</title>" .local/web-smoke-inbox.html

echo "Web smoke passed for $WEB_URL"
