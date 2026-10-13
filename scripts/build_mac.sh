#!/usr/bin/env bash
# Build only: no dependency installation, authentication, launch or login items.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${2:-default}"
case "$PROFILE" in
  default) NAME=Flippy; ID=dev.flippy.app ;;
  demo) NAME='Flippy Demo'; ID=dev.flippy.demo ;;
  *) echo 'profile must be default or demo' >&2; exit 2 ;;
esac
APP="${1:-$HOME/Applications/$NAME.app}"
PY="$ROOT/.venv/bin/python"
[ "$(uname)" = Darwin ] || { echo 'macOS is required' >&2; exit 1; }
[ -x "$PY" ] || { echo 'create .venv and install requirements-mac.txt first' >&2; exit 1; }
ARCH="$(uname -m)"
TARGET="$ARCH-apple-macosx13.0"
PLIST_REV=2  # bump when Info.plist below changes, so installed apps get rebuilt

# Sign with a certificate made once on this Mac, in its own keychain (~/.config/flippy-signing), so macOS ties
# Flippy's permissions to the app id and that certificate, and rebuilds keep them. An ad hoc signature ties them to
# one exact build. If the certificate can't be made or used, the app is signed ad hoc as before.
SIGN_DIR="$HOME/.config/flippy-signing"
KEYCHAIN="$SIGN_DIR/flippy-signing.keychain-db"
add_to_search_list() {  # some macOS versions' codesign only finds an identity in a keychain on this list (#19)
  local real; real="$(cd "$(dirname "$KEYCHAIN")" && pwd -P)/$(basename "$KEYCHAIN")"  # as the list stores it
  security list-keychains -d user | grep -qF "\"$real\"" && return 0
  security list-keychains -d user | sed -e 's/^[[:space:]]*"//' -e 's/"$//' | {
    local list=() k; while IFS= read -r k; do list+=("$k"); done
    security list-keychains -d user -s ${list[@]+"${list[@]}"} "$real"
  }
}
signing_identity() {  # prints the certificate's SHA-1, or nothing
  if [ ! -f "$KEYCHAIN" ]; then
    local tmp; tmp="$(mktemp -d)"
    mkdir -p "$SIGN_DIR" && chmod 700 "$SIGN_DIR" &&
      /usr/bin/openssl rand -hex 24 > "$SIGN_DIR/password" && chmod 600 "$SIGN_DIR/password" &&
      printf '%s\n' '[req]' 'distinguished_name=dn' 'prompt=no' 'x509_extensions=ext' '[dn]' 'CN=Flippy Local Signing' \
        '[ext]' 'basicConstraints=critical,CA:false' 'keyUsage=critical,digitalSignature' \
        'extendedKeyUsage=critical,codeSigning' > "$tmp/cfg" &&
      /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 36500 -config "$tmp/cfg" \
        -keyout "$tmp/key.pem" -out "$tmp/cert.pem" 2>/dev/null &&
      /usr/bin/openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$tmp/cert.pem" -out "$tmp/id.p12" -passout pass:x \
        -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1 &&
      security create-keychain -p "$(cat "$SIGN_DIR/password")" "$KEYCHAIN" &&
      security set-keychain-settings "$KEYCHAIN" &&  # never locks itself
      security import "$tmp/id.p12" -k "$KEYCHAIN" -P x -T /usr/bin/codesign >/dev/null &&
      security set-key-partition-list -S apple-tool:,apple: -s -k "$(cat "$SIGN_DIR/password")" "$KEYCHAIN" >/dev/null ||
      { security delete-keychain "$KEYCHAIN" 2>/dev/null; rm -f "$KEYCHAIN" "$SIGN_DIR/password"; }
    rm -rf "$tmp"
  fi
  [ -f "$KEYCHAIN" ] && security unlock-keychain -p "$(cat "$SIGN_DIR/password")" "$KEYCHAIN" 2>/dev/null &&
    add_to_search_list &&
    security find-identity -p codesigning "$KEYCHAIN" | awk '/"Flippy Local Signing"/ { print $2; exit }'
}
SIGN="$(signing_identity 2>/dev/null || true)"
HASH="$(shasum -a 256 "$ROOT/packaging/macos/Launcher.swift" | cut -d ' ' -f 1)-$TARGET-$PLIST_REV-${SIGN:-adhoc}"
# Python-only changes do not rebuild a valid launcher or change its identity.
if "$PY" - "$APP" "$ROOT" "$ID" "$HASH" <<'PY'
import os, plistlib, sys
app, root, identity, digest = sys.argv[1:]
try:
    with open(app + '/Contents/Info.plist', 'rb') as f: info = plistlib.load(f)
    if info.get('CFBundleIdentifier') != identity or info.get('FlippyRoot') != root:
        raise ValueError('target belongs to a different app or checkout')
    version = open(root + '/VERSION').read().strip()
    raise SystemExit(0 if info.get('FlippyLauncherHash') == digest and info.get('CFBundleVersion') == version else 1)
except (OSError, ValueError):
    raise SystemExit(1)
PY
then
  if codesign --verify --strict "$APP" 2>/dev/null; then printf '%s\n' "$APP"; exit 0; fi
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STAGE="$TMP/$NAME.app/Contents"
mkdir -p "$STAGE/MacOS" "$STAGE/Resources"
xcrun --sdk macosx swiftc -module-cache-path "$TMP/modules" -target "$TARGET" -O -o "$STAGE/MacOS/Flippy" "$ROOT/packaging/macos/Launcher.swift"
"$PY" "$ROOT/packaging/make_icon.py" "$STAGE/Resources/Flippy.icns"
"$PY" - "$STAGE/Info.plist" "$ROOT" "$NAME" "$ID" "$PROFILE" "$HASH" <<'PY'
import os, plistlib, sys
out, root, name, identity, profile, digest = sys.argv[1:]
version = open(os.path.join(root, 'VERSION')).read().strip()
with open(out, 'wb') as f:
    plistlib.dump({
        'CFBundleName': name, 'CFBundleDisplayName': name, 'CFBundleIdentifier': identity,
        'CFBundleExecutable': 'Flippy', 'CFBundleIconFile': 'Flippy', 'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': version, 'CFBundleVersion': version, 'LSMinimumSystemVersion': '13.0',
        'LSUIElement': True, 'NSHighResolutionCapable': True,
        'NSScreenCaptureUsageDescription': 'Flippy sends a screenshot with each question so your tutor can see what you mean.',
        'NSAppleEventsUsageDescription': 'Flippy asks apps like Music, Notes and Safari to do things for you, only when you ask.',
        'FlippyRoot': root, 'FlippyProfile': profile, 'FlippyLauncherHash': digest,
    }, f)
PY
if [ -n "$SIGN" ] && ! codesign --force --sign "$SIGN" --keychain "$KEYCHAIN" "$TMP/$NAME.app"; then
  echo 'flippy: the local certificate could not sign Flippy' >&2
  SIGN=''
  # The hash names the identity, so an ad hoc build isn't later taken for a signed one and kept.
  plutil -replace FlippyLauncherHash -string "${HASH%-*}-adhoc" "$STAGE/Info.plist"
fi
if [ -z "$SIGN" ]; then
  echo 'flippy: signing ad hoc, so macOS may ask for permissions again after rebuilds' >&2
  codesign --force --sign - "$TMP/$NAME.app"
fi
codesign --verify --strict "$TMP/$NAME.app"
"$PY" - "$APP" "$ROOT" "$ID" <<'PY'
import os, plistlib, sys
app, root, identity = sys.argv[1:]
if os.path.lexists(app):
    if os.path.islink(app): raise SystemExit('refusing to replace a symlink app target')
    try:
        with open(app + '/Contents/Info.plist', 'rb') as f: info = plistlib.load(f)
    except (OSError, ValueError): raise SystemExit('refusing to replace an unrecognized app target')
    if info.get('CFBundleIdentifier') != identity or info.get('FlippyRoot') != root:
        raise SystemExit('existing target belongs to another app/checkout; choose another output path')
PY
mkdir -p "$(dirname "$APP")"
# This path has just been verified as our generated bundle.
if [ -e "$APP" ]; then rm -rf "$APP"; fi
mv "$TMP/$NAME.app" "$APP"
printf '%s\n' "$APP"
