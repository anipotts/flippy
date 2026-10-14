#!/usr/bin/env bash
# Default: isolated Demo. --app explicitly builds/runs the normal Flippy profile.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${1:-}" = --app ]; then
  export FLIPPY_PROFILE=default FLIPPY_APP="$HOME/Applications/Flippy.app"
  shift
else
  export FLIPPY_PROFILE=demo FLIPPY_APP="${FLIPPY_DEMO_APP:-$HOME/Applications/Flippy Demo.app}"
fi
PY="$ROOT/.venv/bin/python"
cd "$ROOT"
stop_owned() {
  "$ROOT/bin/flippy-ask" stop-owned >/dev/null
  "$PY" "$ROOT/scripts/wait_stopped.py"
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
