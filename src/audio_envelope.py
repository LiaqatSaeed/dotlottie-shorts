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


def amplitude_envelope(audio_bytes: bytes, fps: float, frame_count: int) -> list[float]:
    """Return `frame_count` RMS amplitude values (0-1, roughly) - one per
    animation frame at `fps` - for the given audio."""
    pcm = decode_to_pcm16_mono(audio_bytes)
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])

    samples_per_frame = max(1, round(SAMPLE_RATE / fps))
    envelope = []
    for i in range(frame_count):
        start = i * samples_per_frame
        end = start + samples_per_frame
        chunk = samples[start:end]
        if not chunk:
            envelope.append(0.0)
            continue
        mean_sq = sum(s * s for s in chunk) / len(chunk)
        rms = mean_sq ** 0.5
        envelope.append(min(1.0, rms / 8000))  # 8000 ~= comfortable speech peak on a 16-bit scale
    return envelope


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
