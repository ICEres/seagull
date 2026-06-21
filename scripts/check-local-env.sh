#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

check_cmd() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    printf "ok      %s\n" "$name"
  else
    printf "missing %s\n" "$name"
  fi
}

check_http() {
  local name="$1"
  local url="$2"
  local code
  if command -v curl >/dev/null 2>&1; then
    code="$(curl -sS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
  else
    code="000"
  fi

  if [ "$code" != "000" ]; then
    printf "ok      %s %s HTTP %s\n" "$name" "$url" "$code"
  else
    printf "unknown %s %s\n" "$name" "$url"
  fi
}

echo "Commands:"
check_cmd python3
check_cmd uv
check_cmd node
check_cmd pnpm
check_cmd go
check_cmd terraform
check_cmd docker

echo
echo "Local dependency endpoints:"
check_http "DynamoDB Local" "http://localhost:8000"
check_http "LocalStack" "http://localhost:4566/_localstack/health"

echo
if [ -f .env.local ]; then
  echo "ok      .env.local"
else
  echo "missing .env.local"
fi
