#!/usr/bin/env python3
"""
Text-to-speech narration, via OpenAI's audio API. Caches by text hash so
re-running the pipeline on the same plan doesn't re-pay for synthesis.

Reads OPENAI_API_KEY the same way generate_plan.py does (env var or local
.env, never a CLI argument).
"""
import hashlib
import json
import os
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".cache" / "audio"
MODEL = "tts-1"
VOICE = "alloy"


def _load_dotenv_key():
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def synthesize(text: str) -> bytes:
    """Return mp3 bytes for `text`, using a local cache keyed by its hash."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{MODEL}:{VOICE}:{text}".encode()).hexdigest()
    cache_path = CACHE_DIR / f"{key}.mp3"
    if cache_path.exists():
        return cache_path.read_bytes()

    api_key = os.environ.get("OPENAI_API_KEY") or _load_dotenv_key()
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. Set it in your own shell or .env file "
            "first - never pass it as a command-line argument."
        )

    body = {"model": MODEL, "voice": VOICE, "input": text, "response_format": "mp3"}
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
            audio_bytes = resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"OpenAI TTS error {e.code}: {e.read().decode()}")

    cache_path.write_bytes(audio_bytes)
    return audio_bytes


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    audio = synthesize(args.text)
    Path(args.out).write_bytes(audio)
    print(f"Wrote {args.out} ({len(audio)} bytes)")
