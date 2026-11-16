#!/usr/bin/env python3
"""
Assemble a frame sequence (from docs/export-frames.html) plus an extracted
audio track (from extract_audio_track.py) into a final MP4.

Usage:
  python3 scripts/assemble_video.py --frames-dir dist --prefix explorer \
      --fps 30 --audio dist/the-explorer-audio.mp3 --out dist/the-explorer.mp4
"""
import argparse
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames-dir", required=True, help="Directory containing <prefix>_NNNNN.png frames")
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--audio", help="Path to an audio track to mux in (optional)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    frames_glob = str(Path(args.frames_dir) / f"{args.prefix}_%05d.png")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    video_only = out_path.with_suffix(".video-only.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-framerate", str(args.fps), "-i", frames_glob,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video_only),
    ], check=True)

    if args.audio:
        # No -shortest here on purpose: narration is usually shorter than
        # the scene it's in (silence after it ends is correct), and using
        # -shortest would wrongly truncate the video to match the audio.
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_only), "-i", args.audio,
            "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
            str(out_path),
        ], check=True)
        video_only.unlink()
    else:
        video_only.rename(out_path)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
