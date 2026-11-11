#!/bin/sh
# Local-only manual editor. Does not attach to or launch a user browser.
set -eu
export PATH="${PATH:+$PATH:}/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE"
for tool in python3 ffmpeg ffprobe; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    case "$tool" in
      python3) printf '%s\n' 'Frame needs Python 3.9 or newer. Install Python, then run this launcher again.' >&2 ;;
      *) printf '%s\n' 'Frame needs FFmpeg and ffprobe. On macOS run: brew install ffmpeg. On Ubuntu run: sudo apt install ffmpeg. Then run this launcher again.' >&2 ;;
    esac
    exit 1
  fi
done
if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 9))'; then
  printf '%s\n' 'Frame needs Python 3.9 or newer. Update Python, then run this launcher again.' >&2
  exit 1
fi
PYTHON="$HERE/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  python3 -m venv "$HERE/.venv"
fi
# A previous setup may have created the environment before installation finished.
if ! "$PYTHON" -c 'import PIL, requests, numpy' >/dev/null 2>&1; then
  printf '%s\n' 'Setting up Frame dependencies…'
  if ! "$PYTHON" -m pip install 'Pillow>=10,<13' 'requests>=2.32,<3' 'numpy>=1.24,<3'; then
    printf '%s\n' 'Frame setup did not finish. Check your internet connection and run this launcher again; saved projects are preserved.' >&2
    exit 1
  fi
fi
# Optional: speech transcription for captions on uploaded videos. Frame still runs without it.
if ! "$PYTHON" -c 'import faster_whisper' >/dev/null 2>&1; then
  "$PYTHON" -m pip install -q 'faster-whisper>=1.0,<2' >/dev/null 2>&1 || printf '%s\n' 'Note: faster-whisper did not install; uploads will be cut without captions.' >&2
fi
export PORT="${PORT:-8876}"
printf 'FRAME editor: http://127.0.0.1:%s/frame\n' "$PORT"
exec "$PYTHON" "$HERE/app.py"
