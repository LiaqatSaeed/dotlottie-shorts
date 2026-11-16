#!/usr/bin/env bash
# One-time setup for the free, open-source Kokoro TTS voice engine
# (github.com/thewh1teagle/kokoro-onnx). Installs the Python package and
# downloads the model files (~340MB total) into .cache/kokoro/.
#
# Uses the "model-files-v1.0" release specifically, not the newer
# "model-files-v1.1" - the currently published kokoro-onnx PyPI package
# (0.4.7) predates v1.1's float-speed input contract change and fails
# with an ONNXRuntimeError on those files.
set -euo pipefail

cd "$(dirname "$0")/.."

pip install -U kokoro-onnx soundfile

mkdir -p .cache/kokoro
cd .cache/kokoro

BASE_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
[ -f kokoro-v1.0.onnx ] || curl -L -o kokoro-v1.0.onnx "$BASE_URL/kokoro-v1.0.onnx"
[ -f voices-v1.0.bin ] || curl -L -o voices-v1.0.bin "$BASE_URL/voices-v1.0.bin"

echo "Kokoro TTS ready. Voices: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md"
