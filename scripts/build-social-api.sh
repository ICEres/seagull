#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/infra/terraform/envs/dev/.terraform/build/social-api"
PACKAGE_DIR="$BUILD_DIR/package"

rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

cp -p "$ROOT_DIR/packages/sea-gull/services/social-api/aws/lambda_function.py" "$PACKAGE_DIR/lambda_function.py"
cp -Rp "$ROOT_DIR/packages/sea-gull/services/social-api/src/social_api" "$PACKAGE_DIR/social_api"
cp -Rp "$ROOT_DIR/packages/gulls/packages/protocol/src/seagull_protocol" "$PACKAGE_DIR/seagull_protocol"

find "$PACKAGE_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$PACKAGE_DIR" -name "*.pyc" -type f -delete

echo "$PACKAGE_DIR"
