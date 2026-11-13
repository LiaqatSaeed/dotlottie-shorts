#!/usr/bin/env python3
"""
Compose a "short" from a plan: a sequence of template instances (each with
its own param overrides) stitched one after another into a single dotLottie
file, so the output is a multi-scene short rather than one looping clip.

Usage:
  python3 src/build_short.py --plan plans/demo-explainer.json --out dist/demo-explainer.lottie
"""
import argparse
import base64
import copy
import json
import os
import zipfile
from pathlib import Path

import math

from generate_audio import synthesize as synthesize_narration
from audio_envelope import extract_features, audio_duration_seconds

PAD_SECONDS = 0.3  # headroom after narration ends, so it doesn't cut off exactly at the last frame

# Rough viseme classification from two cheap per-frame signal features:
# RMS (loudness) and zero-crossing rate (a standard proxy for how
# high-frequency/noise-like a frame is). Thresholds were picked by
# inspecting real narration clips, not guessed - see audio_envelope.py's
# docstring for why ZCR is the second axis instead of just volume tiers.
SILENCE_RMS = 0.02
WIDE_ZCR = 0.30   # breathy/sibilant-ish: quieter but noisier (e.g. "h", "s")
ROUND_ZCR = 0.10  # strong low-frequency vowel: loud and periodic (e.g. "o", "ah")
MOUTH_STATES = ["mouth-closed", "mouth-round", "mouth-wide", "mouth-mid"]


def classify_viseme(rms, zcr):
    if rms <= SILENCE_RMS:
        return "mouth-closed"
    if zcr > WIDE_ZCR:
        return "mouth-wide"
    if zcr < ROUND_ZCR:
        return "mouth-round"
    return "mouth-mid"

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


def find_group_transform(layers, group_name):
    """Find a shape group by its 'nm' across all shape layers, and return its
    transform item ('ty': 'tr') dict - the thing whose 'o' (opacity) we key
    to fade that group in/out."""
    for layer in layers:
        for shape in layer.get("shapes", []):
            if shape.get("ty") == "gr" and shape.get("nm") == group_name:
                for item in shape["it"]:
                    if item.get("ty") == "tr":
                        return item
    return None


def mouth_opacity_keyframes(active_states, this_state):
    """Turn a per-frame list of active-state names into hold keyframes for
    one mouth shape's opacity - 100 whenever it's the active state, else 0.
    Only emits a keyframe when the state changes, to keep the JSON small."""
    def value_at(i):
        return 100 if active_states[i] == this_state else 0

    keyframes = []
    prev_value = None
    for t in range(len(active_states)):
        value = value_at(t)
        if value != prev_value:
            keyframes.append({"t": t, "s": [value], "h": 1})
            prev_value = value
    if not keyframes:
        keyframes = [{"t": 0, "s": [0], "h": 1}]
    keyframes.append({"t": len(active_states), "s": [keyframes[-1]["s"][0]]})
    return keyframes


def embed_lip_sync(scene_data, audio_bytes):
    """Key each mouth shape group's opacity so exactly one is visible per
    frame, picked by classify_viseme() from the narration's audio features."""
    fps = scene_data["fr"]
    frame_count = scene_data["op"] - scene_data["ip"]
    features = extract_features(audio_bytes, fps, frame_count)
    active_states = [classify_viseme(f["rms"], f["zcr"]) for f in features]

    transforms = {name: find_group_transform(scene_data["layers"], name) for name in MOUTH_STATES}
    if any(tr is None for tr in transforms.values()):
        return  # template doesn't have all mouth shapes - nothing to sync

    for name, tr in transforms.items():
        tr["o"] = {"a": 1, "k": mouth_opacity_keyframes(active_states, name)}


def extend_scene_duration(scene_data, new_duration):
    """Stretch a scene's (and every one of its layers') out-point to
    new_duration, assuming all ip/op currently start at 0 - true for every
    template here. Any property with no keyframe past the template's
    original length simply holds its last value for the extra time, which
    is exactly what we want: the character finishes its motion and then
    holds its final pose while narration keeps playing."""
    scene_data["op"] = scene_data["ip"] + new_duration
    for layer in scene_data["layers"]:
        layer["op"] = new_duration


def embed_audio(scene_data, audio_bytes, audio_id):
    """Add pre-synthesized narration audio as an Audio layer (ty=6) spanning
    the scene's full duration, referencing a base64-embedded asset - the
    same embedding convention Lottie uses for inline images."""
    b64 = base64.b64encode(audio_bytes).decode()

    scene_data.setdefault("assets", []).append({
        "id": audio_id,
        "e": 1,
        "u": "",
        "p": f"data:audio/mpeg;base64,{b64}",
    })

    duration = scene_data["op"] - scene_data["ip"]
    next_ind = max((layer.get("ind", 0) for layer in scene_data["layers"]), default=0) + 1
    scene_data["layers"].append({
        "ddd": 0,
        "ind": next_ind,
        "ty": 6,
        "nm": "narration",
        "refId": audio_id,
        "sr": 1,
        "ks": {
            "o": {"a": 0, "k": 100},
            "r": {"a": 0, "k": 0},
            "p": {"a": 0, "k": [0, 0, 0]},
            "a": {"a": 0, "k": [0, 0, 0]},
            "s": {"a": 0, "k": [100, 100, 100]},
        },
        "ao": 0,
        "ip": 0,
        "op": duration,
        "st": 0,
        "bm": 0,
    })


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
        scene_id = f"scene-{i}"
        fps = scene_data["fr"]

        if scene.get("narration"):
            audio_bytes = synthesize_narration(scene["narration"])
            template_duration = scene_data["op"] - scene_data["ip"]
            audio_frames = math.ceil((audio_duration_seconds(audio_bytes) + PAD_SECONDS) * fps)
            if audio_frames > template_duration:
                extend_scene_duration(scene_data, audio_frames)
            embed_audio(scene_data, audio_bytes, audio_id=f"{scene_id}-narration")
            embed_lip_sync(scene_data, audio_bytes)
        if canvas_w is None:
            canvas_w, canvas_h, fr = scene_data["w"], scene_data["h"], scene_data["fr"]
        duration = scene_data["op"] - scene_data["ip"]

        # scene_data may have picked up extra top-level assets (e.g. the
        # embedded audio asset from embed_audio) - those belong in the
        # document's single global asset list, not nested under the precomp.
        assets.extend(scene_data.get("assets", []))
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
