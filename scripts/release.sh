#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/release.sh <version> [commit_message]

Examples:
  ./scripts/release.sh v0.1.1
  ./scripts/release.sh v0.2.0 "release: v0.2.0"

Notes:
  - <version> must match: vMAJOR.MINOR.PATCH
  - The script updates metadata.yaml version automatically.
  - The script appends a changelog section if it does not already exist.
  - The script commits, tags, and pushes to origin/main by default.
  - Set NO_PUSH=1 to skip push.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

VERSION="$1"
COMMIT_MSG="${2:-release: ${VERSION}}"

if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "error: invalid version '$VERSION' (expected vMAJOR.MINOR.PATCH)" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: not a git repository: $ROOT_DIR" >&2
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "error: git remote 'origin' is missing" >&2
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "main" ]]; then
  echo "warn: current branch is '$BRANCH' (recommended: main)" >&2
fi

METADATA_PATH="$ROOT_DIR/metadata.yaml"
CHANGELOG_PATH="$ROOT_DIR/CHANGELOG.md"

if [[ ! -f "$METADATA_PATH" ]]; then
  echo "error: metadata.yaml not found at $METADATA_PATH" >&2
  exit 1
fi

if [[ ! -f "$CHANGELOG_PATH" ]]; then
  echo "error: CHANGELOG.md not found at $CHANGELOG_PATH" >&2
  exit 1
fi

TMP_FILE="$(mktemp)"
awk -v ver="$VERSION" '
  BEGIN { updated = 0 }
  /^version:[[:space:]]*/ && updated == 0 {
    print "version: " ver
    updated = 1
    next
  }
  { print }
  END {
    if (updated == 0) {
      exit 2
    }
  }
' "$METADATA_PATH" >"$TMP_FILE" || {
  rm -f "$TMP_FILE"
  echo "error: failed to update version in metadata.yaml" >&2
  exit 1
}
mv "$TMP_FILE" "$METADATA_PATH"

if ! grep -q "^## \[$VERSION\]" "$CHANGELOG_PATH"; then
  TODAY="$(date +%F)"
  cat >>"$CHANGELOG_PATH" <<EOF

## [$VERSION] - $TODAY

### Added
- Release $VERSION.
EOF
fi

git add metadata.yaml CHANGELOG.md

if ! git diff --cached --quiet; then
  git commit -m "$COMMIT_MSG"
else
  echo "info: no staged file changes detected for commit"
fi

if git rev-parse "$VERSION" >/dev/null 2>&1; then
  echo "error: git tag '$VERSION' already exists" >&2
  exit 1
fi

git tag -a "$VERSION" -m "$COMMIT_MSG"

if [[ "${NO_PUSH:-0}" == "1" ]]; then
  echo "info: NO_PUSH=1, skipping push"
  exit 0
fi

git push origin "${BRANCH}"
git push origin "$VERSION"

echo "release completed: $VERSION"
