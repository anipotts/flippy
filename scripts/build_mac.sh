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
HASH="$(shasum -a 256 "$ROOT/packaging/macos/Launcher.swift" | cut -d ' ' -f 1)-$TARGET"
# Python-only changes do not rebuild a valid launcher or change its ad hoc identity.
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
"$PY" "$ROOT/packaging/macos/make_icon.py" "$STAGE/Resources/Flippy.icns"
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
        'FlippyRoot': root, 'FlippyProfile': profile, 'FlippyLauncherHash': digest,
    }, f)
PY
codesign --force --sign - "$TMP/$NAME.app"
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
