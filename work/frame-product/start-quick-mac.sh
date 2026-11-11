#!/bin/sh
# FRAME Quick Edit Mac launcher. Runs only on localhost.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE"
echo ""
echo "FRAME QUICK EDIT — Mac launcher"
echo "==============================="
if [ "$(uname -s)" != "Darwin" ]; then
  echo "This launcher is intended for macOS." >&2; exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is missing. Install it from https://www.python.org/downloads/ then rerun." >&2; exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "FFmpeg not found; installing through Homebrew..."
    brew install ffmpeg
  else
    echo "FFmpeg is required. Install Homebrew from https://brew.sh and run: brew install ffmpeg" >&2; exit 1
  fi
fi
if ! command -v codex >/dev/null 2>&1; then
  echo "WARNING: Codex CLI not found. Video analysis/edit proposals need Codex CLI installed and authenticated."
  echo "You can still open the interface. See https://github.com/openai/codex"
else
  echo "Codex CLI: found (make sure you are signed in using codex login)"
fi
if [ ! -d .venv ]; then
  echo "Creating isolated Python environment..."
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install --disable-pip-version-check -r requirements.txt
PORT="${PORT:-8765}"
case "$PORT" in *[!0-9]*|'') echo "PORT must be numeric" >&2; exit 1;; esac
echo "Starting on http://127.0.0.1:$PORT/quick"
echo "Press Ctrl+C in this Terminal window to stop."
(
  sleep 2
  open "http://127.0.0.1:$PORT/quick"
) &
PORT="$PORT" python app.py
