#!/usr/bin/env bash
# Install Flippy: picks the macOS or Linux installer.
# Works from a checkout (./install.sh) or straight from GitHub:
#   curl -fsSL https://raw.githubusercontent.com/kap-il/flippy/main/install.sh | bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"

if [ ! -f "$ROOT/flippy/daemon.py" ]; then  # piped from the web: get the code first, then run its installer
    DEST="${FLIPPY_DIR:-$HOME/flippy}"
    if ! command -v git >/dev/null || ! git --version >/dev/null 2>&1; then
        [ "$(uname)" = Darwin ] && xcode-select --install 2>/dev/null || true
        echo "flippy: needs git (on macOS: the Xcode Command Line Tools, a dialog may have opened). Then run this again." >&2
        exit 1
    fi
    if [ -d "$DEST/.git" ]; then
        echo "==> Updating Flippy in $DEST"
        git -C "$DEST" pull --ff-only
    else
        echo "==> Downloading Flippy to $DEST"
        git clone --depth 1 https://github.com/kap-il/flippy "$DEST"
    fi
    exec bash "$DEST/install.sh" "$@"
fi
case "$(uname)" in
    Darwin) exec "$ROOT/scripts/install_mac.sh" "$@" ;;
    Linux) exec "$ROOT/scripts/install_linux.sh" "$@" ;;
    *) echo "flippy: no installer for $(uname)" >&2; exit 1 ;;
esac
