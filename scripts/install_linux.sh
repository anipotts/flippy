#!/usr/bin/env bash
# Install Flippy on Linux (COSMIC/Wayland, Pop!_OS 24.04): the README's steps, automated.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LS_VERSION=v1.3.0
LS_SRC="$HOME/.local/src/gtk4-layer-shell"
BIN_DIR="$HOME/.local/bin"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# 1. System packages.
say "Installing system packages (sudo)"
sudo apt-get install -y git python3-venv python3-gi python3-gi-cairo python3-cairo python3-dbus python3-pil \
    gir1.2-gtk-4.0 gir1.2-adw-1 \
    meson ninja-build libgtk-4-dev libwayland-dev gobject-introspection libgirepository1.0-dev

# 2. gtk4-layer-shell (not packaged for Ubuntu/Pop!_OS 24.04), into ~/.local.
if ! ls "$HOME"/.local/lib/*/libgtk4-layer-shell.so >/dev/null 2>&1; then
    say "Building gtk4-layer-shell $LS_VERSION"
    [ -d "$LS_SRC" ] || git clone --branch "$LS_VERSION" https://github.com/wmww/gtk4-layer-shell "$LS_SRC"
    (cd "$LS_SRC" && meson setup build --prefix "$HOME/.local" -Dexamples=false -Ddocs=false -Dtests=false -Dvapi=false \
        && ninja -C build install)
fi

# 3. Python environment (system site-packages for PyGObject/GTK).
[ -x "$ROOT/.venv/bin/python" ] || python3 -m venv --system-site-packages "$ROOT/.venv"
say "Installing Python packages"
"$ROOT/.venv/bin/pip" install -q --upgrade -r "$ROOT/requirements-linux.txt"

# 4. Commands on PATH.
mkdir -p "$BIN_DIR"
ln -sf "$ROOT/bin/flippy-ask" "$BIN_DIR/flippy-ask"
ln -sf "$ROOT/bin/flippy-daemon" "$BIN_DIR/flippy-daemon"

cat <<MSG

Done. Two things left:
  1. Log in to Claude if you haven't: run \`claude\` once and /login with your Pro/Max account.
  2. Add the hotkeys in COSMIC Settings -> Keyboard -> Keyboard shortcuts -> Custom shortcuts:
       Super+Shift+Space   $BIN_DIR/flippy-ask
       Super+Alt           $BIN_DIR/flippy-ask draw
MSG
