#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-8866}"
NOTEBOOK="ONT_Fragment_Monitoring_Dashboard.ipynb"
URL="http://127.0.0.1:${PORT}"

if [ ! -f "$NOTEBOOK" ]; then
  echo "Notebook not found: $NOTEBOOK" >&2
  exit 1
fi

voila "$NOTEBOOK" --no-browser --port="$PORT" &
VOILA_PID=$!

sleep 2

if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 &
else
    cmd.exe /c start "$URL" >/dev/null 2>&1 || true
fi

wait $VOILA_PID