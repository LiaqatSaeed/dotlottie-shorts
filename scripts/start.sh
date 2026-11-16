#!/usr/bin/env bash
# Starts the one server the editor needs (it serves static files - docs/editor.html,
# dist/*.lottie - AND the POST /speak endpoint, so the editor must be loaded from this
# same origin or the "type a phrase" field gets a 501 from a plain static server instead).
# Needs the project's own venv for kokoro_onnx. Ctrl+C stops it.
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/python3 scripts/export_server.py 8744 &
EXPORT_PID=$!
trap 'kill "$EXPORT_PID" 2>/dev/null || true' EXIT

sleep 1
URL="http://localhost:8744/docs/editor.html"
echo "Editor: $URL"
if command -v open >/dev/null; then open "$URL"; fi

wait "$EXPORT_PID"
