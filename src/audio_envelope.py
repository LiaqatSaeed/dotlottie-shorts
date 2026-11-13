#!/usr/bin/env python3
"""
Decode audio bytes (any format ffmpeg understands) to a per-animation-frame
amplitude envelope, used to drive simple open/closed mouth lip sync.

Requires ffmpeg on PATH - no Python audio dependency.
"""
import array
import subprocess

SAMPLE_RATE = 16000  # decode target; plenty for an amplitude envelope


def decode_to_pcm16_mono(audio_bytes: bytes) -> bytes:
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0",
            "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
            "pipe:1",
        ],
        input=audio_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return proc.stdout


def _frame_chunks(samples, fps, frame_count):
    samples_per_frame = max(1, round(SAMPLE_RATE / fps))
    for i in range(frame_count):
        start = i * samples_per_frame
        yield samples[start:start + samples_per_frame]


def amplitude_envelope(audio_bytes: bytes, fps: float, frame_count: int) -> list[float]:
    """Return `frame_count` RMS amplitude values (0-1, roughly) - one per
    animation frame at `fps` - for the given audio."""
    return [f["rms"] for f in extract_features(audio_bytes, fps, frame_count)]


def extract_features(audio_bytes: bytes, fps: float, frame_count: int) -> list[dict]:
    """Return per-frame {'rms': 0-1ish loudness, 'zcr': 0-1 zero-crossing
    rate} for the given audio. RMS says how loud a frame is; ZCR is a cheap,
    standard speech-processing proxy for how much high-frequency/noise-like
    content it has - voiced vowels are loud with LOW zcr, sibilants/breathy
    consonants are quieter-but-noisier with HIGH zcr. Good enough to pick a
    rough viseme shape without real phoneme alignment."""
    pcm = decode_to_pcm16_mono(audio_bytes)
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])

    features = []
    for chunk in _frame_chunks(samples, fps, frame_count):
        if not chunk:
            features.append({"rms": 0.0, "zcr": 0.0})
            continue
        mean_sq = sum(s * s for s in chunk) / len(chunk)
        rms = min(1.0, (mean_sq ** 0.5) / 8000)  # 8000 ~= comfortable speech peak on a 16-bit scale
        if len(chunk) > 1:
            crossings = sum(1 for a, b in zip(chunk, chunk[1:]) if (a >= 0) != (b >= 0))
            zcr = crossings / (len(chunk) - 1)
        else:
            zcr = 0.0
        features.append({"rms": rms, "zcr": zcr})
    return features


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--frames", type=int, required=True)
    args = parser.parse_args()

    env = amplitude_envelope(Path(args.audio).read_bytes(), args.fps, args.frames)
    print(json.dumps(env))
