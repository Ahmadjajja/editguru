#!/bin/sh
# macOS launchd owns the local service so it survives the initiating terminal.
set -eu
export PATH="${PATH:+$PATH:}/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/frame-quick-edit"
LABEL=com.dantegarcia.frame-quick-edit.local
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'Frame needs Python 3.9 or newer. Install Python, then run this launcher again.' >&2
  exit 1
fi
export PORT="${PORT:-8876}"
case "$PORT" in
  ''|*[!0-9]*|??????*) printf '%s\n' 'Choose a PORT between 1 and 65535.' >&2; exit 1 ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  printf '%s\n' 'Choose a PORT between 1 and 65535.' >&2
  exit 1
fi
mkdir -p "$STATE"
if launchctl list "$LABEL" >/dev/null 2>&1; then
  launchctl remove "$LABEL"
  sleep 1
fi
launchctl submit -l "$LABEL" -o "$STATE/editor.log" -e "$STATE/editor.log" -- /usr/bin/env PORT="$PORT" /bin/sh "$HERE/start-local.sh"
attempt=0
while [ "$attempt" -lt 20 ]; do
  if python3 - "$HERE" "$PORT" <<'PYTHON'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import quick_runtime
try:
    ready = quick_runtime.health('http://127.0.0.1:' + sys.argv[2], frame=Path(sys.argv[1]).resolve())
except (RuntimeError, ValueError) as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(2)
raise SystemExit(0 if ready else 1)
PYTHON
  then
    printf 'FRAME running: http://127.0.0.1:%s/frame\nLog: %s/editor.log\n' "$PORT" "$STATE"
    exit 0
  else
    status=$?
  fi
  if [ "$status" -ne 1 ]; then
    printf 'Check the editor log: %s/editor.log\n' "$STATE" >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 1
done
printf 'Frame has not become ready yet. First-run setup may still be running.\nCheck %s/editor.log before starting another copy. The background job has not been stopped.\n' "$STATE" >&2
exit 2
