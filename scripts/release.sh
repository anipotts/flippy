#!/usr/bin/env bash
# Publish a Flippy release: bump VERSION, commit, tag, push, and create the GitHub Release.
# Installs see it within a day and offer to update (flippy/updates.py).
#   scripts/release.sh 0.3 "What changed, one line per bullet"
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${1:?usage: scripts/release.sh <version> \"<notes>\"}"
NOTES="${2:?usage: scripts/release.sh <version> \"<notes>\"}"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "release from main" >&2; exit 1; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "commit or stash your changes first" >&2; exit 1; }
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "main isn't in sync with origin/main" >&2; exit 1; }
git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null && { echo "v$VERSION already exists" >&2; exit 1; }

if [ "$(cat VERSION)" != "$VERSION" ]; then
    echo "$VERSION" > VERSION
    git commit -q -m "Release $VERSION" VERSION
fi
git tag -a "v$VERSION" -m "Flippy $VERSION"
git push -q origin main "v$VERSION"
gh release create "v$VERSION" --title "Flippy $VERSION" --notes "$NOTES"
echo "Released Flippy $VERSION"
