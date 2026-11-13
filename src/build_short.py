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

from generate_audio import synthesize as synthesize_narration
from audio_envelope import amplitude_envelope

MOUTH_OPEN_THRESHOLD = 0.08

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


def mouth_opacity_keyframes(envelope, open_when_loud):
    """Turn a per-frame amplitude envelope into hold keyframes for one
    mouth shape's opacity - 100 when the mouth should be visible, else 0.
    Only emits a keyframe when the state changes, to keep the JSON small."""
    def state_at(frame_amp):
        is_loud = frame_amp > MOUTH_OPEN_THRESHOLD
        visible = is_loud if open_when_loud else not is_loud
        return 100 if visible else 0

    keyframes = []
    prev_value = None
    for t, amp in enumerate(envelope):
        value = state_at(amp)
        if value != prev_value:
            keyframes.append({"t": t, "s": [value], "h": 1})
            prev_value = value
    if not keyframes:
        keyframes = [{"t": 0, "s": [state_at(0)], "h": 1}]
    keyframes.append({"t": len(envelope), "s": [keyframes[-1]["s"][0]]})
    return keyframes


def embed_lip_sync(scene_data, audio_bytes):
    """Key the 'mouth-open'/'mouth-closed' shape groups' opacity to the
    narration's amplitude envelope, so the mouth visibly moves while the
    character speaks."""
    fps = scene_data["fr"]
    frame_count = scene_data["op"] - scene_data["ip"]
    envelope = amplitude_envelope(audio_bytes, fps, frame_count)

    open_tr = find_group_transform(scene_data["layers"], "mouth-open")
    closed_tr = find_group_transform(scene_data["layers"], "mouth-closed")
    if open_tr is None or closed_tr is None:
        return  # template has no mouth shapes - nothing to sync

    open_tr["o"] = {"a": 1, "k": mouth_opacity_keyframes(envelope, open_when_loud=True)}
    closed_tr["o"] = {"a": 1, "k": mouth_opacity_keyframes(envelope, open_when_loud=False)}


def embed_audio(scene_data, text, audio_id):
    """Synthesize narration for `text` and add it as an Audio layer (ty=6)
    spanning the scene's full duration, referencing a base64-embedded asset -
    the same embedding convention Lottie uses for inline images. Returns the
    raw audio bytes so the caller can also drive lip sync off them."""
    audio_bytes = synthesize_narration(text)
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
    return audio_bytes


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
        if scene.get("narration"):
            audio_bytes = embed_audio(scene_data, scene["narration"], audio_id=f"{scene_id}-narration")
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
