#!/usr/bin/env bash
# Packages a template's Lottie JSON into a .lottie (dotLottie) container.
# Usage: scripts/package-dotlottie.sh <template-json> <animation-id> <output.lottie>
set -euo pipefail

SRC_JSON="$1"
ANIM_ID="$2"
OUT_FILE="$3"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

mkdir -p "$WORKDIR/animations"
cp "$SRC_JSON" "$WORKDIR/animations/$ANIM_ID.json"

cat > "$WORKDIR/manifest.json" <<EOF
{
  "version": "1.0",
  "generator": "dotlottie-shorts",
  "animations": [
    { "id": "$ANIM_ID" }
  ]
}
EOF

mkdir -p "$(dirname "$OUT_FILE")"
rm -f "$OUT_FILE"
OUT_FILE_ABS="$(cd "$(dirname "$OUT_FILE")" && pwd)/$(basename "$OUT_FILE")"
( cd "$WORKDIR" && zip -q -X -r "$OUT_FILE_ABS" manifest.json animations )

echo "Wrote $OUT_FILE"
