#!/usr/bin/env bash
# Build the macOS disk image from the macOS download (scripts/package.sh): Flippy.dmg holds the code in a
# "Flippy" folder and "Install Flippy", which copies it to ~/flippy and runs install.sh. macOS only (hdiutil).
#   scripts/make_dmg.sh dist/flippy-0.3.0-macos.tar.gz dist/Flippy.dmg
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARBALL="${1:?usage: scripts/make_dmg.sh <flippy-VERSION-macos.tar.gz> <out.dmg>}"
OUT="${2:?usage: scripts/make_dmg.sh <flippy-VERSION-macos.tar.gz> <out.dmg>}"
[ "$(uname)" = Darwin ] || { echo "make_dmg needs macOS (hdiutil)" >&2; exit 1; }
NAME="$(basename "$TARBALL" .tar.gz)"            # flippy-0.3.0-macos
VERSION="$(echo "$NAME" | sed -E 's/^flippy-(.*)-macos$/\1/')"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
tar -xzf "$TARBALL" -C "$STAGE"
test -f "$STAGE/$NAME/PACKAGE" && [ "$(cat "$STAGE/$NAME/PACKAGE")" = macos ] || { echo "not a macOS download" >&2; exit 1; }
mkdir "$STAGE/image"
mv "$STAGE/$NAME" "$STAGE/image/Flippy"
cp "$ROOT/packaging/macos/Install Flippy.command" "$STAGE/image/"
chmod +x "$STAGE/image/Install Flippy.command"
cat > "$STAGE/image/Read Me.txt" <<TXT
Flippy $VERSION for macOS

Double-click "Install Flippy". It copies Flippy to the flippy folder in your home folder and sets it up
(a Terminal window shows the progress), then Flippy starts in the menu bar.

If macOS says "Install Flippy" can't be opened because it's from an unidentified developer:
open System Settings > Privacy & Security, scroll down, click "Open Anyway", then double-click it again.

Needs Homebrew (https://brew.sh) and the Xcode Command Line Tools; the installer offers them if missing.
More: https://github.com/kap-il/flippy
TXT
rm -f "$OUT"
hdiutil create -quiet -volname "Flippy $VERSION" -srcfolder "$STAGE/image" -ov -format UDZO "$OUT"
echo "$OUT"
