#!/bin/sh
# Start FRAME inside an Archil sandbox (any Debian/Ubuntu-based Linux image, e.g. python:3.12).
# Serves the editor and the demo on 0.0.0.0:$PORT so Archil can expose the port publicly.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v ffmpeg >/dev/null 2>&1 || ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
  echo 'Installing FFmpeg and Python venv…'
  apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg python3-venv >/dev/null
fi
export FRAME_BIND="${FRAME_BIND:-0.0.0.0}"
export PORT="${PORT:-8876}"
# Set FRAME_PUBLIC_HOST to the hostname Archil gives the exposed port (no https://, no path).
echo "FRAME on port $PORT · public host: ${FRAME_PUBLIC_HOST:-not set (only localhost works)}"
exec sh "$HERE/start-local.sh"
