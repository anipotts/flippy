#!/usr/bin/env bash
# Default: isolated Demo. --app explicitly builds/runs the normal Flippy profile.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export FLIPPY_PROFILE=demo
if [ "${1:-}" = --app ]; then
  export FLIPPY_PROFILE=default
  shift
fi
if [ "$FLIPPY_PROFILE" = default ]; then
  export FLIPPY_APP="$HOME/Applications/Flippy.app"
else
  export FLIPPY_APP="${FLIPPY_DEMO_APP:-$HOME/Applications/Flippy Demo.app}"
fi
PY="$ROOT/.venv/bin/python"
cd "$ROOT"
stop_owned() {
  "$ROOT/bin/flippy-ask" stop-owned >/dev/null
  "$PY" - <<'PY'
import socket, time
from flippy.profile import current
deadline = time.monotonic() + 30
while True:
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(1)
            sock.connect(current().socket)
    except (FileNotFoundError, ConnectionRefusedError): break
    if time.monotonic() >= deadline:
        raise SystemExit('Flippy has not stopped; rebuild aborted while cleanup is pending')
    time.sleep(.1)
PY
}
case "${1:-run}" in
  build) "$ROOT/scripts/build_mac.sh" "$FLIPPY_APP" "$FLIPPY_PROFILE" ;;
  run|--verify)
    stop_owned
    "$ROOT/scripts/build_mac.sh" "$FLIPPY_APP" "$FLIPPY_PROFILE"
    /usr/bin/open -n "$FLIPPY_APP"
    if [ "${1:-}" = --verify ]; then
      for attempt in {1..100}; do
        if "$ROOT/bin/flippy-ask" ping 2>/dev/null; then exit 0; fi
        sleep .1
      done
      echo 'Flippy did not answer ping; inspect its log' >&2; exit 1
    fi ;;
  ask) shift; exec "$ROOT/bin/flippy-ask" "$@" ;;
  stop) stop_owned ;;
  doctor) exec "$PY" "$ROOT/scripts/doctor.py" ;;
  *) echo 'usage: scripts/dev.sh [--app] [build|run|--verify|ask <command>|stop|doctor]' >&2; exit 2 ;;
esac
