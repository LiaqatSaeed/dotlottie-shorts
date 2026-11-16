#!/usr/bin/env bash
# Starts both servers the editor needs and opens it in the browser:
#   - port 8743: static file server (serves docs/editor.html and dist/*.lottie)
#   - port 8744: export server (POST /speak, needs the project's own venv for kokoro_onnx)
# Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

cleanup() {
  kill "$PREVIEW_PID" "$EXPORT_PID" 2>/dev/null || true
}
trap cleanup EXIT

python3 -m http.server --directory . 8743 &
PREVIEW_PID=$!

.venv/bin/python3 scripts/export_server.py 8744 &
EXPORT_PID=$!

sleep 1
URL="http://localhost:8743/docs/editor.html"
echo "Editor: $URL"
if command -v open >/dev/null; then open "$URL"; fi

wait "$PREVIEW_PID" "$EXPORT_PID"
