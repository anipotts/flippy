#!/usr/bin/env bash
# Build the release downloads from HEAD: dist/flippy-<version>-macos.tar.gz and -linux.tar.gz.
# Each has the shared code plus its own platform's (flippy/mac or flippy/linux, its installer and requirements),
# and a PACKAGE file naming the platform, which is how flippy/updates.py knows to update it from releases.
#   scripts/package.sh            (version from VERSION)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="$(cat VERSION)"
OUT="$ROOT/dist"
mkdir -p "$OUT"
COMMON=(':!tests' ':!scripts/release.sh' ':!scripts/package.sh' ':!.gitignore')
MAC_ONLY=('flippy/mac' 'packaging/macos' 'scripts/install_mac.sh' 'requirements-mac.txt')
LINUX_ONLY=('flippy/linux' 'scripts/install_linux.sh' 'requirements-linux.txt' 'docs/linux-port.md')

build() {  # build <platform> <paths of the other platform...>
    local plat="$1"; shift
    local name="flippy-$VERSION-$plat" tmp
    local excludes=("${COMMON[@]}")
    for p in "$@"; do excludes+=(":!$p"); done
    tmp="$(mktemp -d)"
    git archive --format=tar --prefix="$name/" HEAD -- . "${excludes[@]}" | tar -x -C "$tmp"
    echo "$plat" > "$tmp/$name/PACKAGE"
    tar -czf "$OUT/$name.tar.gz" -C "$tmp" "$name"
    rm -rf "$tmp"
    echo "$OUT/$name.tar.gz"
}
build macos "${LINUX_ONLY[@]}"
build linux "${MAC_ONLY[@]}"
