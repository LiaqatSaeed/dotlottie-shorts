#!/usr/bin/env python3
"""
Text-to-speech narration, with a choice of engine:

- "openai": OpenAI's audio API (paid, per-character cost). Reads
  OPENAI_API_KEY the same way generate_plan.py does (env var or local
  .env, never a CLI argument).
- "kokoro": Kokoro TTS (github.com/thewh1teagle/kokoro-onnx) - free,
  open source (Apache 2.0 weights), 50+ voices, runs locally on CPU.
  Needs `pip install kokoro-onnx soundfile` and the model files
  downloaded once - see scripts/setup_kokoro.sh.

Both are cached by (engine, voice, text) hash, so re-running the
pipeline on the same plan doesn't re-synthesize or re-pay for anything.
"""
import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".cache" / "audio"
KOKORO_DIR = REPO_ROOT / ".cache" / "kokoro"

OPENAI_MODEL = "tts-1"
DEFAULT_VOICE = {"openai": "alloy", "kokoro": "af_sarah"}

_kokoro_instance = None  # lazy-loaded singleton - the model is ~300MB, load once per process


def _load_dotenv_key():
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _synthesize_openai(text, voice):
    api_key = os.environ.get("OPENAI_API_KEY") or _load_dotenv_key()
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. Set it in your own shell or .env file "
            "first - never pass it as a command-line argument."
        )

    body = {"model": OPENAI_MODEL, "voice": voice, "input": text, "response_format": "mp3"}
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"OpenAI TTS error {e.code}: {e.read().decode()}")


def _get_kokoro():
    global _kokoro_instance
    if _kokoro_instance is None:
        try:
            from kokoro_onnx import Kokoro
        except ImportError:
            raise SystemExit(
                "kokoro-onnx isn't installed. Run scripts/setup_kokoro.sh first "
                "(installs kokoro-onnx + soundfile and downloads the model files)."
            )
        model_path = KOKORO_DIR / "kokoro-v1.0.onnx"
        voices_path = KOKORO_DIR / "voices-v1.0.bin"
        if not model_path.exists() or not voices_path.exists():
            raise SystemExit(f"Kokoro model files not found under {KOKORO_DIR} - run scripts/setup_kokoro.sh first.")
        _kokoro_instance = Kokoro(str(model_path), str(voices_path))
    return _kokoro_instance


def _synthesize_kokoro(text, voice):
    import soundfile as sf

    kokoro = _get_kokoro()
    samples, sample_rate = kokoro.create(text, voice=voice, speed=1.0, lang="en-us")

    with tempfile.NamedTemporaryFile(suffix=".wav") as wav_file:
        sf.write(wav_file.name, samples, sample_rate)
        # Downstream code (build_short.py, audio_envelope.py) expects mp3
        # bytes, same as the OpenAI path - transcode with ffmpeg so nothing
        # else in the pipeline needs to know which engine produced the audio.
        result = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", wav_file.name, "-f", "mp3", "pipe:1"],
            capture_output=True, check=True,
        )
        return result.stdout


def synthesize(text: str, engine: str = "openai", voice: str = None) -> bytes:
    """Return mp3 bytes for `text`, using a local cache keyed by
    (engine, voice, text)."""
    if engine not in ("openai", "kokoro"):
        raise ValueError(f"Unknown voice engine '{engine}' - must be 'openai' or 'kokoro'")
    voice = voice or DEFAULT_VOICE[engine]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{engine}:{voice}:{text}".encode()).hexdigest()
    cache_path = CACHE_DIR / f"{key}.mp3"
    if cache_path.exists():
        return cache_path.read_bytes()

    if engine == "openai":
        audio_bytes = _synthesize_openai(text, voice)
    else:
        audio_bytes = _synthesize_kokoro(text, voice)

    cache_path.write_bytes(audio_bytes)
    return audio_bytes


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--engine", choices=["openai", "kokoro"], default="openai")
    parser.add_argument("--voice", default=None)
    args = parser.parse_args()

    audio = synthesize(args.text, engine=args.engine, voice=args.voice)
    Path(args.out).write_bytes(audio)
    print(f"Wrote {args.out} ({len(audio)} bytes)")
