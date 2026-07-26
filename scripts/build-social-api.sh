#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/infra/terraform/envs/dev/.terraform/build/social-api"
PACKAGE_DIR="$BUILD_DIR/package"

rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

cp -p "$ROOT_DIR/packages/seagulls/services/social-api/aws/lambda_function.py" "$PACKAGE_DIR/lambda_function.py"
cp -Rp "$ROOT_DIR/packages/seagulls/services/social-api/src/social_api" "$PACKAGE_DIR/social_api"
cp -Rp "$ROOT_DIR/packages/gulls/packages/protocol/src/seagull_protocol" "$PACKAGE_DIR/seagull_protocol"
cp -Rp "$ROOT_DIR/packages/pet/packages/assets/src/pet_assets" "$PACKAGE_DIR/pet_assets"
# The Feed dual-write writes gulls records into the gulls Feed tables, so the
# social API needs the hub's domain models and storage adapter.
cp -Rp "$ROOT_DIR/packages/gulls/services/message-hub/src/message_hub" "$PACKAGE_DIR/message_hub"
cp -Rp "$ROOT_DIR/packages/gulls/packages/policy/src/seagull_policy" "$PACKAGE_DIR/seagull_policy"
cp -Rp "$ROOT_DIR/packages/gulls/packages/common/src/seagull_common" "$PACKAGE_DIR/seagull_common"

find "$PACKAGE_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$PACKAGE_DIR" -name "*.pyc" -type f -delete

echo "$PACKAGE_DIR"
