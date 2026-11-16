#!/usr/bin/env python3
"""Embed a .lottie file as a base64 data URI into a self-contained HTML
preview page - openable directly as a file, no local server needed."""
import argparse
import base64
import json
import zipfile
from pathlib import Path

TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <script type="module">
    import {{ DotLottie }} from "https://cdn.jsdelivr.net/npm/@lottiefiles/dotlottie-web@0.83.2/+esm";
    window.addEventListener("DOMContentLoaded", () => {{
      new DotLottie({{
        canvas: document.getElementById("anim"),
        src: "data:application/zip;base64,{b64}",
        loop: true,
        autoplay: true,
      }});
    }});
  </script>
  <style>
    body {{ background: #1a1a1a; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; font-family: -apple-system, sans-serif; color: #eee; gap: 16px; }}
    #anim {{ width: {display_w}px; height: {display_h}px; background: #fff; border-radius: 8px; box-shadow: 0 8px 30px rgba(0,0,0,0.4); }}
    p {{ opacity: 0.6; font-size: 14px; max-width: 420px; text-align: center; }}
  </style>
</head>
<body>
  <canvas id="anim" width="{canvas_w}" height="{canvas_h}"></canvas>
  <p>{caption}</p>
</body>
</html>
"""


def read_canvas_size(lottie_path):
    with zipfile.ZipFile(lottie_path) as z:
        manifest = json.loads(z.read("manifest.json"))
        anim_id = manifest["animations"][0]["id"]
        data = json.loads(z.read(f"animations/{anim_id}.json"))
    return data["w"], data["h"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lottie", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--title", default="dotlottie-shorts preview")
    parser.add_argument("--caption", default="")
    parser.add_argument("--max-display-height", type=int, default=640,
                         help="Scale the preview box down to fit this height, preserving aspect ratio")
    args = parser.parse_args()

    canvas_w, canvas_h = read_canvas_size(args.lottie)
    scale = min(1.0, args.max_display_height / canvas_h)
    display_w, display_h = round(canvas_w * scale), round(canvas_h * scale)

    b64 = base64.b64encode(Path(args.lottie).read_bytes()).decode()
    html = TEMPLATE.format(
        title=args.title, b64=b64, caption=args.caption,
        canvas_w=canvas_w, canvas_h=canvas_h, display_w=display_w, display_h=display_h,
    )
    Path(args.out).write_text(html)
    print(f"Wrote {args.out} ({len(html)} bytes, canvas {canvas_w}x{canvas_h})")
