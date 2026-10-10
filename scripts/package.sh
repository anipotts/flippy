#!/usr/bin/env bash
# Build the release downloads from HEAD: dist/flippy-<version>-macos.tar.gz and -linux.tar.gz.
# Each has the shared code plus its own platform's (flippy/mac or flippy/linux, its installer and requirements),
# and a PACKAGE file naming the platform, which is how flippy/updates.py knows to update it from releases.
#   scripts/package.sh            (version from VERSION)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -z "$(git status --porcelain)" ] || { echo "package requires a clean committed tree (including untracked files)" >&2; exit 1; }
REVISION="$(git rev-parse HEAD)"
VERSION="$(git show "$REVISION:VERSION")"
[[ "$VERSION" =~ ^[0-9]+(\.[0-9]+){1,3}([a-zA-Z0-9.-]*)?$ ]] || { echo "invalid VERSION" >&2; exit 1; }
OUT="$ROOT/dist"
mkdir -p "$OUT"
COMMON=(':!tests' ':!scripts/release.sh' ':!scripts/package.sh' ':!scripts/make_dmg.sh' ':!.gitignore' ':!.codex' ':!script' ':!scripts/dev.sh' ':!scripts/doctor.py' ':!scripts/action_fixture.py')
MAC_ONLY=('flippy/mac' 'packaging/macos' 'scripts/install_mac.sh' 'scripts/build_mac.sh' 'requirements-mac.txt')
LINUX_ONLY=('flippy/linux' 'scripts/install_linux.sh' 'requirements-linux.txt' 'docs/linux-port.md')

build() {  # build <platform> <paths of the other platform...>
    local plat="$1"; shift
    local name="flippy-$VERSION-$plat" tmp
    local excludes=("${COMMON[@]}")
    for p in "$@"; do excludes+=(":!$p"); done
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' RETURN
    git archive --format=tar --prefix="$name/" "$REVISION" -- . "${excludes[@]}" | tar -x -C "$tmp"
    echo "$plat" > "$tmp/$name/PACKAGE"
    echo "$REVISION" > "$tmp/$name/REVISION"
    test -f "$tmp/$name/flippy/daemon.py"
    test -f "$tmp/$name/bin/flippy-daemon"
    test -f "$tmp/$name/install.sh"
    if [ "$plat" = macos ]; then
        test -f "$tmp/$name/packaging/macos/Launcher.swift"
        test -f "$tmp/$name/requirements-mac.txt"
        test -f "$tmp/$name/scripts/build_mac.sh"
        test -f "$tmp/$name/scripts/wait_stopped.py"
        test ! -d "$tmp/$name/flippy/linux"
    else
        test -f "$tmp/$name/requirements-linux.txt"
        test ! -d "$tmp/$name/flippy/mac"
    fi
    tar -czf "$OUT/$name.tar.gz" -C "$tmp" "$name"
    rm -rf "$tmp"
    trap - RETURN
    echo "$OUT/$name.tar.gz"
}
build macos "${LINUX_ONLY[@]}"
build linux "${MAC_ONLY[@]}"
