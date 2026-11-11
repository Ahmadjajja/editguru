#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TOKEN_FILE="${FRAME_MCP_TOKEN_FILE:-$HOME/.local/share/frame/quick-mcp-token}"
mkdir -p "$(dirname -- "$TOKEN_FILE")"
if [ ! -f "$TOKEN_FILE" ]; then
  (umask 077; "$HERE/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(36))' > "$TOKEN_FILE")
fi
FRAME_MCP_TOKEN=$(cat "$TOKEN_FILE")
export FRAME_MCP_TOKEN
exec "$HERE/.venv/bin/python" "$HERE/quick_mcp.py" --http
