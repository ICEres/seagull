#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

WITH_LOCALSTACK=0
SKIP_DOCKER=0

for arg in "$@"; do
  case "$arg" in
    --with-localstack)
      WITH_LOCALSTACK=1
      ;;
    --skip-docker)
      SKIP_DOCKER=1
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: ./scripts/setup-local.sh [--with-localstack] [--skip-docker]" >&2
      exit 2
      ;;
  esac
done

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    return 1
  fi
}

warn_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Warning: optional command not found: $1" >&2
  fi
}

echo "Setting up Seagull local development..."

if [ ! -f .env.local ]; then
  cp .env.example .env.local
  echo "Created .env.local from .env.example"
else
  echo ".env.local already exists"
fi

mkdir -p .local/dynamodb
echo "Prepared .local/dynamodb"

warn_cmd python3
warn_cmd uv
warn_cmd node
warn_cmd pnpm
warn_cmd go
warn_cmd terraform

if [ "$SKIP_DOCKER" -eq 1 ]; then
  echo "Skipping Docker dependency startup"
  echo "Done. Run 'make local-up' later to start local dependencies."
  exit 0
fi

need_cmd docker

if ! docker compose version >/dev/null 2>&1; then
  echo "Missing required command: docker compose" >&2
  exit 1
fi

echo "Starting DynamoDB Local..."
docker compose -f infra/local/docker-compose.yml up -d dynamodb-local

if [ "$WITH_LOCALSTACK" -eq 1 ]; then
  echo "Starting LocalStack..."
  docker compose -f infra/local/docker-compose.yml --profile localstack up -d localstack
else
  echo "LocalStack not started. Use --with-localstack when queues/events are needed."
fi

echo
echo "Local setup complete."
echo
echo "Useful commands:"
echo "  make local-logs"
echo "  make local-down"
echo "  make check-local-env"
echo
echo "Service endpoints:"
echo "  DynamoDB Local: http://localhost:8000"
echo "  LocalStack:     http://localhost:4566 (optional)"
