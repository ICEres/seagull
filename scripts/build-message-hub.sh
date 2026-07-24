#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/infra/terraform/envs/dev/.terraform/build/message-hub-api"
PACKAGE_DIR="$BUILD_DIR/package"

rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

cp -p "$ROOT_DIR/packages/gulls/services/message-hub/aws/lambda_function.py" "$PACKAGE_DIR/lambda_function.py"
cp -Rp "$ROOT_DIR/packages/gulls/services/message-hub/src/message_hub" "$PACKAGE_DIR/message_hub"
cp -Rp "$ROOT_DIR/packages/gulls/packages/policy/src/seagull_policy" "$PACKAGE_DIR/seagull_policy"
cp -Rp "$ROOT_DIR/packages/gulls/packages/common/src/seagull_common" "$PACKAGE_DIR/seagull_common"

find "$PACKAGE_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$PACKAGE_DIR" -name "*.pyc" -type f -delete

echo "$PACKAGE_DIR"
