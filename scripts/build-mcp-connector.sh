#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/infra/terraform/envs/dev/.terraform/build/mcp-connector"
PACKAGE_DIR="$BUILD_DIR/package"

rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

cp -p "$ROOT_DIR/packages/gulls/connect/mcp-connector/aws/lambda_function.py" "$PACKAGE_DIR/lambda_function.py"
cp -Rp "$ROOT_DIR/packages/gulls/connect/mcp-connector/src/seagull_mcp" "$PACKAGE_DIR/seagull_mcp"
cp -Rp "$ROOT_DIR/packages/gulls/packages/common/src/seagull_common" "$PACKAGE_DIR/seagull_common"

find "$PACKAGE_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$PACKAGE_DIR" -name "*.pyc" -type f -delete

echo "$PACKAGE_DIR"
