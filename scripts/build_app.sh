#!/usr/bin/env bash
# Build the self-contained Flippy.app (dist/Flippy.app) and the disk image you drag it from (dist/Flippy.dmg).
#
# Everything Flippy needs is inside the app: a standalone Python (python-build-standalone), Flippy's packages,
# cairo built here for macOS 13+ (Homebrew's only runs on the macOS it was built for), and the code, which the
# launcher copies to ~/Library/Application Support/Flippy/code on first launch (packaging/macos/Launcher.swift).
# Apple Silicon only. Needs the Xcode Command Line Tools and network access; nothing is installed system-wide.
#   scripts/build_app.sh                         (code from scripts/package.sh: needs a clean committed tree)
#   scripts/build_app.sh dist/flippy-X-macos.tar.gz
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ "$(uname)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo "build_app needs an Apple Silicon Mac" >&2; exit 1; }

# pinned inputs (bump deliberately, then rebuild and test)
PY_RELEASE=20260924 PY_VERSION=3.13.15
PIXMAN=0.46.2 LIBPNG=1.6.58 CAIRO=1.18.4 PYCAIRO=1.29.2
export MACOSX_DEPLOYMENT_TARGET=13.0

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
CACHE="$ROOT/dist/cache"
WORK="$ROOT/dist/build"
APP="$ROOT/dist/Flippy.app"
mkdir -p "$CACHE"
rm -rf "$WORK" "$APP"
mkdir -p "$WORK"
fetch() {  # fetch <url> <file in the cache>
    [ -s "$CACHE/$2" ] && return
    curl -fsSL --retry 3 -o "$CACHE/$2.part" "$1" || { echo "couldn't download $1" >&2; exit 1; }
    mv "$CACHE/$2.part" "$CACHE/$2"
}

# 1. The code: the macOS release download.
TARBALL="${1:-}"
if [ -z "$TARBALL" ]; then
    TARBALL="$(scripts/package.sh | grep -- '-macos.tar.gz$')"
fi
VERSION="$(basename "$TARBALL" .tar.gz | sed -E 's/^flippy-(.*)-macos$/\1/')"
say "Flippy $VERSION from $TARBALL"

# 2. Build tools in a scratch environment (meson, ninja, delocate), not on the system.
say "Build tools"
python3 -m venv "$WORK/tools"
"$WORK/tools/bin/pip" install -q meson ninja delocate
export PATH="$WORK/tools/bin:$PATH"

# 3. cairo for macOS 13+: pixman, libpng, cairo (Quartz, PNG; no FreeType/fontconfig: Flippy draws text with
#    CoreText on macOS).
DEPS="$WORK/deps"
export PKG_CONFIG_LIBDIR="$DEPS/lib/pkgconfig"   # only ours, never Homebrew's
export CFLAGS="-mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET -O2" LDFLAGS="-mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET"
say "libpng $LIBPNG"
fetch "https://downloads.sourceforge.net/project/libpng/libpng16/$LIBPNG/libpng-$LIBPNG.tar.xz" "libpng-$LIBPNG.tar.xz"
tar -xf "$CACHE/libpng-$LIBPNG.tar.xz" -C "$WORK"
(cd "$WORK/libpng-$LIBPNG" && ./configure -q --prefix="$DEPS" --disable-static --disable-tools >/dev/null \
    && make -s -j"$(sysctl -n hw.ncpu)" >/dev/null && make -s install >/dev/null)
say "pixman $PIXMAN"
fetch "https://cairographics.org/releases/pixman-$PIXMAN.tar.gz" "pixman-$PIXMAN.tar.gz"
tar -xf "$CACHE/pixman-$PIXMAN.tar.gz" -C "$WORK"
meson setup "$WORK/pixman-build" "$WORK/pixman-$PIXMAN" --prefix="$DEPS" --libdir=lib --buildtype=release \
    -Dtests=disabled -Ddemos=disabled -Dgtk=disabled -Dlibpng=disabled >/dev/null
ninja -C "$WORK/pixman-build" install >/dev/null
say "cairo $CAIRO"
fetch "https://cairographics.org/releases/cairo-$CAIRO.tar.xz" "cairo-$CAIRO.tar.xz"
tar -xf "$CACHE/cairo-$CAIRO.tar.xz" -C "$WORK"
meson setup "$WORK/cairo-build" "$WORK/cairo-$CAIRO" --prefix="$DEPS" --libdir=lib --buildtype=release \
    -Dfreetype=disabled -Dfontconfig=disabled -Dquartz=enabled -Dpng=enabled -Dzlib=enabled -Dtee=disabled \
    -Dxlib=disabled -Dxcb=disabled -Dglib=disabled -Dspectre=disabled -Dsymbol-lookup=disabled -Dlzo=disabled \
    -Dtests=disabled -Dgtk_doc=false >/dev/null
ninja -C "$WORK/cairo-build" install >/dev/null

# 4. The app's Python.
say "Python $PY_VERSION"
PY_TAR="cpython-$PY_VERSION+$PY_RELEASE-aarch64-apple-darwin-install_only_stripped.tar.gz"
fetch "https://github.com/astral-sh/python-build-standalone/releases/download/$PY_RELEASE/${PY_TAR//+/%2B}" "$PY_TAR"
RES="$APP/Contents/Resources"
mkdir -p "$APP/Contents/MacOS" "$RES"
tar -xzf "$CACHE/$PY_TAR" -C "$RES"           # -> Resources/python
PY="$RES/python/bin/python3"
export PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONNOUSERSITE=1

# 5. Packages: pycairo built against our cairo, its libraries copied into the wheel (delocate), then the rest
#    as prebuilt wheels.
say "pycairo $PYCAIRO (against our cairo)"
"$PY" -m pip wheel -q --no-binary pycairo "pycairo==$PYCAIRO" -w "$WORK/wheels" >/dev/null
delocate-wheel -w "$WORK/fixed" --require-archs arm64 "$WORK/wheels"/pycairo-*.whl >/dev/null
"$PY" -m pip install -q "$WORK/fixed"/pycairo-*.whl
say "Flippy's packages"
grep -v '^pycairo' "$ROOT/requirements-mac.txt" > "$WORK/requirements.txt"
"$PY" -m pip install -q --only-binary :all: -r "$WORK/requirements.txt" certifi
cp "$("$PY" -c 'import certifi; print(certifi.where())')" "$RES/cacert.pem"
# What the app never uses: PyObjC's test suite, pip (the app's packages only change with a new Flippy.dmg),
# Tk/IDLE, and C headers.
SITE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
STD="$(dirname "$SITE")"
rm -rf "$SITE"/PyObjCTest "$SITE"/pip "$SITE"/pip-* "$STD"/ensurepip "$STD"/idlelib "$STD"/tkinter "$STD"/turtledemo \
    "$STD"/lib-dynload/_tkinter* "$RES"/python/lib/libtcl* "$RES"/python/lib/tcl* "$RES"/python/lib/tk* \
    "$RES"/python/lib/itcl* "$RES"/python/lib/thread* "$RES"/python/include "$RES"/python/bin/pip* \
    "$RES"/python/bin/idle* "$RES"/python/bin/pydoc*
"$PY" - <<'PY'
import cairo, objc, PIL, claude_agent_sdk, Quartz  # the app's Python has everything
s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4); cairo.Context(s).paint()
import io; b = io.BytesIO(); s.write_to_png(b); assert b.getvalue().startswith(b"\x89PNG")
PY

# 6. The code, the launcher, the icon and Info.plist.
say "The app"
tar -xzf "$TARBALL" -C "$WORK"
mv "$WORK/flippy-$VERSION-macos" "$RES/code"
find "$RES" -name __pycache__ -type d -prune -exec rm -rf {} +
xcrun --sdk macosx swiftc -module-cache-path "$WORK/modules" -target "arm64-apple-macosx$MACOSX_DEPLOYMENT_TARGET" -O \
    -o "$APP/Contents/MacOS/Flippy" "$ROOT/packaging/macos/Launcher.swift"
"$PY" "$ROOT/packaging/macos/make_icon.py" "$RES/Flippy.icns"
"$PY" - "$APP/Contents/Info.plist" "$VERSION" <<'PY'
import plistlib, sys
out, version = sys.argv[1:]
with open(out, "wb") as f:
    plistlib.dump({
        "CFBundleName": "Flippy", "CFBundleDisplayName": "Flippy", "CFBundleIdentifier": "dev.flippy.app",
        "CFBundleExecutable": "Flippy", "CFBundleIconFile": "Flippy", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version, "CFBundleVersion": version, "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True, "NSHighResolutionCapable": True, "LSArchitecturePriority": ["arm64"],
        "NSScreenCaptureUsageDescription": "Flippy sends a screenshot with each question so your tutor can see what you mean.",
        "FlippyBundled": True, "FlippyProfile": "default",
    }, f)
PY

# 7. Nothing in it may need a newer macOS than 13.
"$PY" - "$APP" "$MACOSX_DEPLOYMENT_TARGET" <<'PY'
import os, subprocess, sys
app, target = sys.argv[1], tuple(int(n) for n in sys.argv[2].split("."))
too_new = []
for d, _, names in os.walk(app):
    for n in names:
        p = os.path.join(d, n)
        if os.path.islink(p) or not (n.endswith((".so", ".dylib")) or os.access(p, os.X_OK)):
            continue
        out = subprocess.run(["vtool", "-show-build", p], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if line.strip().startswith("minos"):
                v = tuple(int(x) for x in line.split()[1].split("."))
                if v > target:
                    too_new.append(f"{os.path.relpath(p, app)} needs macOS {line.split()[1]}")
if too_new:
    sys.exit("these need a newer macOS than the app supports:\n  " + "\n  ".join(too_new))
PY

# 8. Sign (ad hoc: no Apple Developer ID), then the disk image: Flippy.app and a link to Applications.
say "Signing"
codesign --force --deep --sign - "$APP" 2>/dev/null
codesign --verify --deep --strict "$APP"
say "Disk image"
IMG="$WORK/image"
mkdir -p "$IMG"
cp -R "$APP" "$IMG/"
ln -s /Applications "$IMG/Applications"
rm -f "$ROOT/dist/Flippy.dmg"
hdiutil create -quiet -volname "Flippy $VERSION" -srcfolder "$IMG" -ov -format UDZO "$ROOT/dist/Flippy.dmg"
du -sh "$APP" "$ROOT/dist/Flippy.dmg"
echo "$ROOT/dist/Flippy.dmg"
