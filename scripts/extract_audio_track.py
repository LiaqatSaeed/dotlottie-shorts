#!/usr/bin/env python3
"""
Extract the embedded per-scene narration audio from a composed .lottie and
mix it into one audio track matching the full timeline, using ffmpeg's
adelay+amix (each scene's audio starts exactly at that scene's start frame).

Usage:
  python3 scripts/extract_audio_track.py --lottie dist/the-explorer.lottie --out dist/the-explorer-audio.mp3
"""
import argparse
import base64
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path


def load_composed(lottie_path):
    with zipfile.ZipFile(lottie_path) as z:
        manifest = json.loads(z.read("manifest.json"))
        anim_id = manifest["animations"][0]["id"]
        data = json.loads(z.read(f"animations/{anim_id}.json"))
    return data


def find_scene_audio_clips(data):
    """Return [(start_frame, audio_bytes), ...] for every scene that has a
    narration audio layer, by walking the main precomp layers and their
    referenced assets."""
    fps = data["fr"]
    assets_by_id = {a["id"]: a for a in data["assets"]}
    clips = []

    for layer in data["layers"]:
        if layer.get("ty") != 0:  # precomp layer
            continue
        start_frame = layer["ip"]
        scene_asset = assets_by_id.get(layer["refId"])
        if not scene_asset:
            continue
        for sub_layer in scene_asset.get("layers", []):
            if sub_layer.get("ty") == 6:  # audio layer
                audio_asset = assets_by_id.get(sub_layer["refId"])
                if audio_asset and audio_asset.get("p", "").startswith("data:audio"):
                    b64 = audio_asset["p"].split(",", 1)[1]
                    clips.append((start_frame / fps, base64.b64decode(b64)))
    return clips, data["op"] / fps


def mix_audio(clips, total_duration_s, out_path):
    if not clips:
        raise SystemExit("No narration audio found in this .lottie - nothing to extract.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        inputs = []
        filters = []
        for i, (start_s, audio_bytes) in enumerate(clips):
            clip_path = tmp / f"clip{i}.mp3"
            clip_path.write_bytes(audio_bytes)
            inputs += ["-i", str(clip_path)]
            delay_ms = round(start_s * 1000)
            filters.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]")

        mix_inputs = "".join(f"[a{i}]" for i in range(len(clips)))
        filter_complex = ";".join(filters) + f";{mix_inputs}amix=inputs={len(clips)}:normalize=0[aout]"

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-t", str(total_duration_s),
            str(out_path),
        ]
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lottie", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data = load_composed(args.lottie)
    clips, total_duration_s = find_scene_audio_clips(data)
    print(f"Found {len(clips)} narration clip(s), total duration {total_duration_s:.2f}s")
    mix_audio(clips, total_duration_s, args.out)
    print(f"Wrote {args.out}")
