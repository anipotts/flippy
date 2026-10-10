#!/bin/bash
# Flippy's macOS disk image runs this: copy Flippy out of the image into ~/flippy (or $FLIPPY_DIR), then run its
# installer, which sets up Python and builds ~/Applications/Flippy.app. Running it again updates in place.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)/Flippy"
DEST="${FLIPPY_DIR:-$HOME/flippy}"
if [ -d "$DEST/.git" ]; then
    echo "Flippy in $DEST is a git checkout. Update it there instead: cd $DEST && git pull && ./install.sh"
    exit 1
fi
if [ -e "$DEST" ] && [ ! -f "$DEST/PACKAGE" ]; then
    echo "$DEST already exists and isn't a Flippy download. Move it, or run with FLIPPY_DIR set to another folder."
    exit 1
fi
echo "==> Copying Flippy to $DEST"
mkdir -p "$DEST"
# the Python environment is kept (the installer refreshes it); settings live in ~/.config/flippy, not here
rsync -a --delete --exclude .venv --exclude __pycache__ "$SRC/" "$DEST/"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
cd "$DEST"
exec ./install.sh
