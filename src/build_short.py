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
from props import PROPS

PAD_SECONDS = 0.3  # headroom after narration ends, so it doesn't cut off exactly at the last frame
PROP_POSITION = [420, 90]  # top-right corner, comp coordinates

# Every template is authored on a 512x512 stage. Rather than rescale the
# character art for other aspect ratios, these pick a canvas size and pad
# around the original 512x512 content (recentered), so shorts can target
# the format that actually matters for distribution - vertical for
# YouTube Shorts/TikTok/Reels - without touching any template file.
ASPECT_RATIOS = {
    "9:16": (512, 910),
    "16:9": (910, 512),
    "1:1": (512, 512),
    "4:5": (512, 640),
}
NATIVE_STAGE = 512

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


EYE_GROUPS = [
    f"eye-{side}-{part}"
    for side in ("left", "right")
    for part in ("sclera", "pupil", "highlight")
]
BLINK_INTERVAL = 75  # frames between blinks (~2.5s at 30fps) - not truly random, but not static either
BLINK_CLOSE_FRAMES = 3  # how long the eye stays shut


def blink_scale_keyframes(total_frames, phase):
    """Hold-style keyframes for one eye-part's vertical scale: [100,100]
    (open) most of the time, briefly [100,8] (shut) at regular intervals -
    same crisp on/off style as the mouth-viseme keyframes, since a blink
    is fast enough that easing it would just look like squinting."""
    keyframes = [{"t": 0, "s": [100, 100], "h": 1}]
    t = phase
    while t < total_frames:
        keyframes.append({"t": t, "s": [100, 8], "h": 1})
        reopen_t = min(t + BLINK_CLOSE_FRAMES, total_frames)
        keyframes.append({"t": reopen_t, "s": [100, 100], "h": 1})
        t += BLINK_INTERVAL
    keyframes.append({"t": total_frames, "s": keyframes[-1]["s"]})
    return keyframes


def embed_blinking(scene_data, scene_index=0):
    """Key every eye-part's vertical scale to blink periodically for the
    scene's full duration, so eyes aren't just static dots."""
    total_frames = scene_data["op"] - scene_data["ip"]
    # stagger the phase per scene so every character on screen doesn't blink
    # in perfect unison, without needing real randomness (which would make
    # output non-reproducible from the same plan)
    phase = 20 + (scene_index * 11) % 15
    for name in EYE_GROUPS:
        tr = find_group_transform(scene_data["layers"], name)
        if tr is not None:
            tr["s"] = {"a": 1, "k": blink_scale_keyframes(total_frames, phase)}


def fit_scene_to_canvas(scene_data, canvas_w, canvas_h):
    """Adapt a 512x512-authored scene to a different output canvas by
    padding, not rescaling: resize the background to fill the new canvas,
    and shift every other layer by the same offset that recenters the
    original 512x512 content within it. A no-op when canvas_w/h are 512."""
    dx = (canvas_w - NATIVE_STAGE) / 2
    dy = (canvas_h - NATIVE_STAGE) / 2
    if dx == 0 and dy == 0:
        return

    for layer in scene_data["layers"]:
        is_background = any(
            shape.get("nm") == "background-group" for shape in layer.get("shapes", [])
        )
        if is_background:
            for shape in layer["shapes"]:
                for item in shape.get("it", []):
                    if item.get("nm") == "bg-shape":
                        item["s"]["k"] = [canvas_w, canvas_h]
                        item["p"]["k"] = [canvas_w / 2, canvas_h / 2]
            continue

        pos = layer["ks"]["p"]
        if pos.get("a") == 1:
            for kf in pos["k"]:
                if "s" in kf:
                    kf["s"][0] += dx
                    kf["s"][1] += dy
        else:
            pos["k"][0] += dx
            pos["k"][1] += dy


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


def tile_keyframes(keyframes, period, total_frames):
    """Repeat an animated property's keyframe pattern (authored for one
    `period`-frame cycle, e.g. a wave swing or a head-bob) every `period`
    frames until `total_frames`, instead of freezing after the first cycle.
    The final keyframe of each cycle is dropped before tiling, since its
    value is identical to the next cycle's first keyframe at the same
    relative time - keeping it would create a duplicate keyframe at that t."""
    if total_frames <= period or len(keyframes) < 2:
        return keyframes

    base = keyframes[:-1]
    tiled = []
    offset = 0
    while offset < total_frames:
        for kf in base:
            t = offset + kf["t"]
            if t >= total_frames:
                break
            new_kf = copy.deepcopy(kf)
            new_kf["t"] = t
            tiled.append(new_kf)
        offset += period

    last_value = tiled[-1]["s"] if tiled else keyframes[-1]["s"]
    tiled.append({"t": total_frames, "s": last_value})
    return tiled


# Layers whose animated transform property should loop for a scene's full
# (possibly narration-extended) duration instead of playing once and
# freezing - gives a line reading longer than one gesture cycle some
# continued body language instead of the character going rigid partway
# through. Maps layer name -> which ks property to tile.
LOOPING_GESTURES = {
    "right-arm": "r",
    "pointing-arm": "r",
    "character-body-head": "p",
}


def loop_body_motion(scene_data, period, total_frames):
    if total_frames <= period:
        return
    for layer in scene_data["layers"]:
        prop_key = LOOPING_GESTURES.get(layer.get("nm"))
        if not prop_key:
            continue
        prop = layer["ks"].get(prop_key)
        if prop and prop.get("a") == 1:
            prop["k"] = tile_keyframes(prop["k"], period, total_frames)


def embed_prop(scene_data, prop_name, position=PROP_POSITION):
    """Add a small decorative icon (see props.py) as its own layer at a
    fixed corner position, so a scene can show something relevant to what's
    being said instead of just a character on a flat color."""
    if prop_name not in PROPS:
        return  # unknown prop name - silently skip rather than crash the build

    shapes = []
    for i, group_spec in enumerate(PROPS[prop_name]):
        style = dict(group_spec["style"])
        style.setdefault("o", {"a": 0, "k": 100})
        if style["ty"] == "st":
            style.setdefault("lc", 1)
            style.setdefault("lj", 1)
            style.setdefault("ml", 10)
        xf = group_spec.get("transform", {})
        shapes.append({
            "ty": "gr",
            "nm": f"prop-{prop_name}-group-{i}",
            "it": [
                *group_spec["shapes"],
                style,
                {"ty": "tr", "p": {"a": 0, "k": xf.get("p", [0, 0])}, "a": {"a": 0, "k": [0, 0]},
                 "s": {"a": 0, "k": [100, 100]}, "r": {"a": 0, "k": xf.get("r", 0)}, "o": {"a": 0, "k": 100},
                 "sk": {"a": 0, "k": 0}, "sa": {"a": 0, "k": 0}},
            ],
        })

    duration = scene_data["op"] - scene_data["ip"]
    next_ind = max((layer.get("ind", 0) for layer in scene_data["layers"]), default=0) + 1
    scene_data["layers"].insert(0, {
        "ddd": 0,
        "ind": next_ind,
        "ty": 4,
        "nm": f"prop-{prop_name}",
        "sr": 1,
        "ks": {
            "o": {"a": 0, "k": 100},
            "r": {"a": 0, "k": 0},
            "p": {"a": 0, "k": [position[0], position[1], 0]},
            "a": {"a": 0, "k": [0, 0, 0]},
            "s": {"a": 0, "k": [100, 100, 100]},
        },
        "ao": 0,
        "shapes": shapes,
        "ip": 0,
        "op": duration,
        "st": 0,
        "bm": 0,
    })


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


def compose(plan, aspect_ratio=None, voice_engine=None, voice=None):
    """Wrap each scene's layers as a precomp asset, then place sequential
    precomp layers in the main composition so scenes play one after another."""
    aspect_ratio = aspect_ratio or plan.get("aspectRatio", "9:16")
    voice_engine = voice_engine or plan.get("voiceEngine", "openai")
    voice = voice or plan.get("voice")
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"Unknown aspect ratio '{aspect_ratio}' - must be one of {list(ASPECT_RATIOS)}")
    canvas_w, canvas_h = ASPECT_RATIOS[aspect_ratio]

    assets = []
    main_layers = []
    cursor = 0
    fr = None

    for i, scene in enumerate(plan["scenes"]):
        template_path = REPO_ROOT / scene["template"]
        scene_data = load_template(template_path, scene.get("params", {}))
        scene_id = f"scene-{i}"
        fps = scene_data["fr"]
        template_duration = scene_data["op"] - scene_data["ip"]

        if scene.get("narration"):
            audio_bytes = synthesize_narration(scene["narration"], engine=voice_engine, voice=voice)
            audio_frames = math.ceil((audio_duration_seconds(audio_bytes) + PAD_SECONDS) * fps)
            if audio_frames > template_duration:
                extend_scene_duration(scene_data, audio_frames)
            embed_audio(scene_data, audio_bytes, audio_id=f"{scene_id}-narration")
            embed_lip_sync(scene_data, audio_bytes)
        if scene.get("prop"):
            embed_prop(scene_data, scene["prop"])
        loop_body_motion(scene_data, template_duration, scene_data["op"] - scene_data["ip"])
        embed_blinking(scene_data, scene_index=i)
        fit_scene_to_canvas(scene_data, canvas_w, canvas_h)
        if fr is None:
            fr = scene_data["fr"]
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
    parser.add_argument(
        "--aspect-ratio", choices=list(ASPECT_RATIOS), default=None,
        help="Output canvas shape (default: the plan's own 'aspectRatio' field, else 9:16)",
    )
    parser.add_argument(
        "--voice-engine", choices=["openai", "kokoro"], default=None,
        help="TTS engine (default: the plan's own 'voiceEngine' field, else openai)",
    )
    parser.add_argument(
        "--voice", default=None,
        help="Voice name for the chosen engine (default: the plan's own 'voice' field, else each engine's default)",
    )
    args = parser.parse_args()

    with open(args.plan) as f:
        plan = json.load(f)

    combined = compose(plan, aspect_ratio=args.aspect_ratio, voice_engine=args.voice_engine, voice=args.voice)
    animation_id = plan.get("animationId", "short")
    package_dotlottie(combined, animation_id, args.out)

    duration_s = combined["op"] / combined["fr"]
    print(f"Wrote {args.out} ({len(plan['scenes'])} scenes, {duration_s:.1f}s total)")


if __name__ == "__main__":
    main()
