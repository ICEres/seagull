#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/infra/terraform/envs/dev/.terraform/build/safety-gateway"
PACKAGE_DIR="$BUILD_DIR/package"

rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

cp -p "$ROOT_DIR/packages/gulls/services/safety-gateway/aws/lambda_function.py" "$PACKAGE_DIR/lambda_function.py"
cp -Rp "$ROOT_DIR/packages/gulls/services/safety-gateway/src/safety_gateway" "$PACKAGE_DIR/safety_gateway"
cp -Rp "$ROOT_DIR/packages/gulls/packages/policy/src/seagull_policy" "$PACKAGE_DIR/seagull_policy"

find "$PACKAGE_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$PACKAGE_DIR" -name "*.pyc" -type f -delete

echo "$PACKAGE_DIR"
