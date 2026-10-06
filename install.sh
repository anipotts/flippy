#!/usr/bin/env bash
# Install Flippy: picks the macOS or Linux installer.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
case "$(uname)" in
    Darwin) exec "$ROOT/scripts/install_mac.sh" "$@" ;;
    Linux) exec "$ROOT/scripts/install_linux.sh" "$@" ;;
    *) echo "flippy: no installer for $(uname)" >&2; exit 1 ;;
esac
