#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/infra/terraform/envs/dev/.terraform/build/ai-provider"
PACKAGE_DIR="$BUILD_DIR/package"

rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

cp -p "$ROOT_DIR/packages/gulls/services/ai-provider/aws/lambda_function.py" "$PACKAGE_DIR/lambda_function.py"
cp -Rp "$ROOT_DIR/packages/gulls/services/ai-provider/src/ai_provider" "$PACKAGE_DIR/ai_provider"

find "$PACKAGE_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$PACKAGE_DIR" -name "*.pyc" -type f -delete

echo "$PACKAGE_DIR"
