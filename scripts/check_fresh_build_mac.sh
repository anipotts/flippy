#!/usr/bin/env bash
# Build Flippy.app from a fresh HOME (no ~/.config/flippy-signing) and check it is signed by the local certificate (#19).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ "$(uname)" = Darwin ] || { echo 'macOS is required' >&2; exit 1; }
SCRATCH="$(mktemp -d)"
SCRATCH="$(cd "$SCRATCH" && pwd -P)"  # the search list stores resolved paths
cleanup() {
  HOME="$SCRATCH" security delete-keychain "$SCRATCH/.config/flippy-signing/flippy-signing.keychain-db" 2>/dev/null || true
  rm -rf "${SCRATCH:?}"
}
trap cleanup EXIT
# Without Library/Preferences, `security list-keychains -s` silently does nothing.
mkdir -p "$SCRATCH/Library/Preferences" "$SCRATCH/Library/Keychains"
APP="$SCRATCH/out/Flippy.app"
KEYCHAIN="$SCRATCH/.config/flippy-signing/flippy-signing.keychain-db"
fail() { echo "check_fresh_build_mac: FAIL: $*" >&2; exit 1; }

HOME="$SCRATCH" bash "$ROOT/scripts/build_mac.sh" "$APP" default
info="$(codesign -dvv "$APP" 2>&1)"
grep -qx 'Authority=Flippy Local Signing' <<<"$info" || { echo "$info" >&2; fail 'not signed by Flippy Local Signing'; }
codesign --verify --strict "$APP" || fail 'codesign --verify --strict'
listed="$(HOME="$SCRATCH" security list-keychains -d user | grep -cF "\"$KEYCHAIN\"" || true)"
[ "$listed" = 1 ] || { HOME="$SCRATCH" security list-keychains -d user >&2; fail "keychain on search list $listed times, want 1"; }

# A second run keeps the valid bundle instead of rebuilding it.
before="$(stat -f %i "$APP/Contents/Info.plist")"
HOME="$SCRATCH" bash "$ROOT/scripts/build_mac.sh" "$APP" default || fail 'second run exited nonzero'
[ "$(stat -f %i "$APP/Contents/Info.plist")" = "$before" ] || fail 'second run rebuilt the app'
listed="$(HOME="$SCRATCH" security list-keychains -d user | grep -cF "\"$KEYCHAIN\"" || true)"
[ "$listed" = 1 ] || fail "keychain on search list $listed times after second run, want 1"
echo 'check_fresh_build_mac: ok'
