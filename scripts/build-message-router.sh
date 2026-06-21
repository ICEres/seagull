#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/infra/terraform/envs/dev/.terraform/build/message-router"

mkdir -p "$BUILD_DIR"

cd "$ROOT_DIR/apps/message-hub/router"

GOOS=linux \
GOARCH=arm64 \
CGO_ENABLED=0 \
GOCACHE="${GOCACHE:-/private/tmp/seagull-go-build}" \
go build -trimpath -ldflags="-s -w" -o "$BUILD_DIR/bootstrap" ./cmd/lambda

echo "$BUILD_DIR/bootstrap"
