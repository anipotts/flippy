#!/usr/bin/env bash
# Publish a Flippy release: bump VERSION, commit, tag, push, and create the GitHub Release with the
# macOS and Linux downloads (scripts/package.sh) attached.
# Installs see it within a day and offer to update (flippy/updates.py).
#   scripts/release.sh 0.3 "What changed, one line per bullet"
# The notes' first line is what the "Flippy <version> is out" card shows, so make it the headline.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${1:?usage: scripts/release.sh <version> \"<notes>\"}"
NOTES="${2:?usage: scripts/release.sh <version> \"<notes>\"}"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "release from main" >&2; exit 1; }
[ -z "$(git status --porcelain )" ] || { echo "commit or stash your changes first" >&2; exit 1; }
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "main isn't in sync with origin/main" >&2; exit 1; }
git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null && { echo "v$VERSION already exists" >&2; exit 1; }

if [ "$(cat VERSION)" != "$VERSION" ]; then
    echo "$VERSION" > VERSION
    git commit -q -m "Release $VERSION" VERSION
fi
# Verify the exact release commit before creating any tag or publishing it.
PYTHON="${FLIPPY_PYTHON:-python3}"
"$PYTHON" -m unittest discover -s tests
bash -n install.sh scripts/install_mac.sh scripts/install_linux.sh scripts/package.sh
scripts/package.sh
[ -z "$(git status --porcelain)" ] || { echo "checks changed the release tree" >&2; exit 1; }
git tag -a "v$VERSION" -m "Flippy $VERSION"
git push -q origin main "v$VERSION"
gh release create "v$VERSION" --title "Flippy $VERSION" --notes "$NOTES" \
    "dist/flippy-$VERSION-macos.tar.gz#Flippy $VERSION for macOS" "dist/flippy-$VERSION-linux.tar.gz#Flippy $VERSION for Linux (COSMIC)"
echo "Released Flippy $VERSION"
