#!/usr/bin/env python3
"""
Compose a "short" from a plan: a sequence of template instances (each with
its own param overrides) stitched one after another into a single dotLottie
file, so the output is a multi-scene short rather than one looping clip.

Usage:
  python3 src/build_short.py --plan plans/demo-explainer.json --out dist/demo-explainer.lottie
"""
import argparse
import copy
import json
import os
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def deep_set_fill_colors(node, color_overrides):
    """Recursively walk a Lottie layer/shape tree and rewrite fill colors
    whose shape item 'nm' matches a key in color_overrides."""
    if isinstance(node, dict):
        if node.get("ty") == "fl" and node.get("nm") in color_overrides:
            node["c"]["k"] = color_overrides[node["nm"]]
        for v in node.values():
            deep_set_fill_colors(v, color_overrides)
    elif isinstance(node, list):
        for item in node:
            deep_set_fill_colors(item, color_overrides)


def load_template(template_path, params):
    with open(template_path) as f:
        data = json.load(f)
    data = copy.deepcopy(data)
    color_overrides = {}
    for key, value in params.items():
        # params map e.g. "outfitColor" -> value; config files map param key
        # to a target shape name. We look up that mapping from the sibling
        # .config.json if present, else assume the key *is* the shape name.
        color_overrides[key] = value
    config_path = Path(str(template_path).replace(".json", ".config.json"))
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        shape_name_overrides = {}
        for param_def in config.get("params", []):
            key = param_def["key"]
            if key in params:
                for target in param_def.get("targets", []):
                    shape_name = target.get("shapeName")
                    if shape_name:
                        shape_name_overrides[shape_name] = params[key]
        color_overrides = shape_name_overrides
    deep_set_fill_colors(data, color_overrides)
    return data


def compose(plan):
    """Wrap each scene's layers as a precomp asset, then place sequential
    precomp layers in the main composition so scenes play one after another."""
    assets = []
    main_layers = []
    cursor = 0
    canvas_w = canvas_h = None
    fr = None

    for i, scene in enumerate(plan["scenes"]):
        template_path = REPO_ROOT / scene["template"]
        scene_data = load_template(template_path, scene.get("params", {}))
        if canvas_w is None:
            canvas_w, canvas_h, fr = scene_data["w"], scene_data["h"], scene_data["fr"]
        duration = scene_data["op"] - scene_data["ip"]
        scene_id = f"scene-{i}"

        assets.append({
            "id": scene_id,
            "nm": scene.get("label", scene_id),
            "fr": scene_data["fr"],
            "layers": scene_data["layers"],
        })
        main_layers.append({
            "ddd": 0,
            "ind": i + 1,
            "ty": 0,
            "nm": scene.get("label", scene_id),
            "refId": scene_id,
            "sr": 1,
            "ks": {
                "o": {"a": 0, "k": 100},
                "r": {"a": 0, "k": 0},
                "p": {"a": 0, "k": [0, 0, 0]},
                "a": {"a": 0, "k": [0, 0, 0]},
                "s": {"a": 0, "k": [100, 100, 100]},
            },
            "ao": 0,
            "w": canvas_w,
            "h": canvas_h,
            "ip": cursor,
            "op": cursor + duration,
            "st": cursor,
            "bm": 0,
        })
        cursor += duration

    return {
        "v": "5.9.0",
        "fr": fr,
        "ip": 0,
        "op": cursor,
        "w": canvas_w,
        "h": canvas_h,
        "nm": plan.get("animationId", "short"),
        "ddd": 0,
        "assets": assets,
        "layers": main_layers,
    }


def package_dotlottie(lottie_json, animation_id, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": "1.0",
        "generator": "dotlottie-shorts",
        "animations": [{"id": animation_id}],
    }
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr(f"animations/{animation_id}.json", json.dumps(lottie_json))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="Path to a plan JSON file")
    parser.add_argument("--out", required=True, help="Output .lottie path")
    args = parser.parse_args()

    with open(args.plan) as f:
        plan = json.load(f)

    combined = compose(plan)
    animation_id = plan.get("animationId", "short")
    package_dotlottie(combined, animation_id, args.out)

    duration_s = combined["op"] / combined["fr"]
    print(f"Wrote {args.out} ({len(plan['scenes'])} scenes, {duration_s:.1f}s total)")


if __name__ == "__main__":
    main()
