#!/usr/bin/env bash
# Install Flippy on macOS: Python deps in .venv, ~/Applications/Flippy.app, flippy-ask on PATH.
# Re-run it any time to update (it rebuilds the app in place).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${FLIPPY_APP_DIR:-$HOME/Applications}"
APP="$APP_DIR/Flippy.app"
BIN_DIR="$HOME/.local/bin"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mflippy install:\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Tools: Xcode Command Line Tools (to build the app's launcher), Homebrew cairo (pycairo builds against it).
if ! xcode-select -p >/dev/null 2>&1; then
    xcode-select --install || true
    die "install the Xcode Command Line Tools (a dialog just opened), then run ./install.sh again"
fi
command -v brew >/dev/null || die "Flippy needs Homebrew for cairo: see https://brew.sh, then run ./install.sh again"
for pkg in cairo pkgconf; do
    brew list --versions "$pkg" >/dev/null 2>&1 || { say "Installing $pkg (Homebrew)"; brew install "$pkg"; }
done
new_enough() { [ -x "$1" ] && "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; }
PY="$(brew --prefix)/bin/python3"
new_enough "$PY" || PY="$(command -v python3 || true)"
if ! new_enough "$PY"; then
    say "Installing Python (Homebrew)"
    brew install python
    PY="$(brew --prefix)/bin/python3"
fi

# 2. Python environment.
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    say "Creating the Python environment (.venv)"
    "$PY" -m venv "$ROOT/.venv"
fi
say "Installing Python packages (the first run downloads Claude Code, ~200 MB)"
"$ROOT/.venv/bin/pip" install -q --upgrade pip
PKG_CONFIG_PATH="$(brew --prefix)/lib/pkgconfig:${PKG_CONFIG_PATH:-}" \
    "$ROOT/.venv/bin/pip" install -q --upgrade -r "$ROOT/requirements-mac.txt"

# 3. Reuse the same build-only helper as the isolated demo.
say "Building $APP"
FLIPPY_PROFILE=default "$ROOT/bin/flippy-ask" stop-owned >/dev/null
FLIPPY_PROFILE=default "$ROOT/.venv/bin/python" "$ROOT/scripts/wait_stopped.py"
"$ROOT/scripts/build_mac.sh" "$APP" default

# 4. flippy-ask on PATH (scripting, and `flippy-ask setup` / `settings`).
mkdir -p "$BIN_DIR"
ln -sf "$ROOT/bin/flippy-ask" "$BIN_DIR/flippy-ask"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) say "Add $BIN_DIR to your PATH to use flippy-ask from a terminal" ;; esac

# 5. Start it; the setup window takes it from here.
say "Starting Flippy (look for the pointer icon in the menu bar)"
open "$APP"
