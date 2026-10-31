#!/bin/bash
# Builds the gulls CLI as a universal binary and copies it into the app
# bundle's Resources. Runs as an Xcode post-build script phase; can also be
# invoked standalone with BUILT_PRODUCTS_DIR/UNLOCALIZED_RESOURCES_FOLDER_PATH set.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_AGENT_DIR="$(cd "$SCRIPT_DIR/../../../connect/local-agent" && pwd)"
GOCACHE="${GOCACHE:-${TMPDIR:-/tmp}/seagull-go-build}"
export GOCACHE

DEST_DIR="$BUILT_PRODUCTS_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH"
mkdir -p "$DEST_DIR"

# Version stamp from git so `gulls version` inside the bundle is meaningful.
VERSION="$(git -C "$LOCAL_AGENT_DIR" describe --tags --always --dirty 2>/dev/null || echo dev)"
LDFLAGS="-X seagull/packages/gulls/connect/local-agent/internal/agentcli.Version=$VERSION"

BUILD_TMP="$(mktemp -d)"
trap 'rm -rf "$BUILD_TMP"' EXIT

cd "$LOCAL_AGENT_DIR"
GOOS=darwin GOARCH=arm64 go build -ldflags "$LDFLAGS" -o "$BUILD_TMP/gulls-arm64" ./cmd/gulls
GOOS=darwin GOARCH=amd64 go build -ldflags "$LDFLAGS" -o "$BUILD_TMP/gulls-amd64" ./cmd/gulls
lipo -create -output "$DEST_DIR/gulls" "$BUILD_TMP/gulls-arm64" "$BUILD_TMP/gulls-amd64"

# Use the app's resolved signing identity for the nested binary as well.
SIGNING_IDENTITY="${EXPANDED_CODE_SIGN_IDENTITY:-${CODE_SIGN_IDENTITY:--}}"
codesign --force --sign "$SIGNING_IDENTITY" --identifier ai.gulls.mac.cli "$DEST_DIR/gulls"
echo "Bundled gulls ($VERSION) into $DEST_DIR/gulls"
