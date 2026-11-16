#!/usr/bin/env python3
"""
Add our standard mouth shapes (mouth-closed/mid/round/wide) to a
third-party Lottie animation that doesn't have them, so it can speak via
this pipeline's existing lip-sync/audio machinery - which only cares about
shape *names*, not which character drew them.

Also makes the result playable at any output canvas size even though the
source was authored on its own native stage (e.g. 1080x1080, not our
512x512): wraps every top-level layer that has no parent under one new
null layer ("scene-root-scale") whose scale/anchor normalize the native
stage down to our 512-equivalent content size. build_short.py's
fit_scene_to_canvas() recognizes this layer by name and repositions it for
whatever canvas the plan asks for, instead of walking every layer like it
does for our own natively-512 templates.

Usage:
  python3 scripts/adapt_character_lottie.py --in external-refs/_extract/char/animations/<id>.json \
      --out external-refs/character-speaking.json \
      --mouth-layer Head --mouth-pos 57.646 79.827 --mouth-scale 0.338
"""
import argparse
import copy
import json
import re
from pathlib import Path

NATIVE_STAGE = 512

# Same shapes as our own templates' mouths, just parameterized by scale so
# they can be sized to match whatever head they're being added to.
MOUTH_SHAPES = {
    "mouth-closed": {"size": [46, 10], "dy": 0, "color": [0.55, 0.25, 0.22, 1], "default_on": True},
    "mouth-mid": {"size": [40, 34], "dy": 3, "color": [0.3, 0.12, 0.1, 1], "default_on": False},
    "mouth-round": {"size": [28, 38], "dy": 5, "color": [0.3, 0.12, 0.1, 1], "default_on": False},
    "mouth-wide": {"size": [54, 16], "dy": 1, "color": [0.3, 0.12, 0.1, 1], "default_on": False},
}


def make_mouth_group(name, center, scale, spec):
    w, h = spec["size"][0] * scale, spec["size"][1] * scale
    cx, cy = center[0], center[1] + spec["dy"] * scale
    return {
        "ty": "gr",
        "nm": name,
        "it": [
            {"ty": "el", "nm": f"{name}-shape", "p": {"a": 0, "k": [cx, cy]}, "s": {"a": 0, "k": [w, h]}},
            {"ty": "fl", "nm": "mouth-fill", "c": {"a": 0, "k": spec["color"]}, "o": {"a": 0, "k": 100}},
            {"ty": "tr", "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [100, 100]},
             "r": {"a": 0, "k": 0}, "o": {"a": 0, "k": 100 if spec["default_on"] else 0},
             "sk": {"a": 0, "k": 0}, "sa": {"a": 0, "k": 0}},
        ],
    }


def find_old_mouth_index(shapes):
    """Identify the existing mouth by elimination, not by name - it's
    whichever group in the head layer is painted with a stroke ("st")
    rather than a fill, since every other facial feature we've seen (eyes)
    uses fills."""
    for i, g in enumerate(shapes):
        paints = [it["ty"] for it in g.get("it", []) if it["ty"] in ("fl", "st")]
        if paints == ["st"]:
            return i
    return None


def _shape_local_width(shape):
    """Best-effort width of a shape group's own path/ellipse/rect, in its
    own local coordinate space, used to scale our canonical mouth size
    (46 units wide) to roughly match whatever the old mouth's size was."""
    for it in shape.get("it", []):
        if it["ty"] == "sh" and it["ks"].get("a") == 0:
            verts = [v[0] for v in it["ks"]["k"].get("v", [])]
            if verts:
                return max(verts) - min(verts)
        if it["ty"] in ("el", "rc") and it.get("s", {}).get("a") == 0:
            return it["s"]["k"][0]
    return None


def iter_layer_containers(data):
    """Yield (container_id, layers_list) for the main composition
    (container_id=None) and every precomp asset's own layers (container_id=
    that asset's id) - a character's face often lives inside a nested
    precomp (e.g. a "Head" layer that's really a reference to a sub-
    composition), not in the top-level layer list, and Lottie's asset list
    is flat regardless of how deeply nested the precomp references are, so
    one pass over it already reaches every nesting depth."""
    yield None, data["layers"]
    for asset in data.get("assets", []):
        if "layers" in asset:
            yield asset["id"], asset["layers"]


def find_mouth_layer(data):
    """Scan every layer, in every composition (main + nested precomps),
    for one whose shapes contain an existing mouth by find_old_mouth_index's
    stroke-vs-fill heuristic, and return where it lives plus the mouth
    group's own local position/size - read directly from the data rather
    than guessed, so no manual --mouth-pos/--mouth-scale tuning is needed
    for a new character. Returns None if no layer looks like it has an
    identifiable swappable mouth (caller should fall back to a different
    detection strategy, or to manual parameters, rather than guess blindly)."""
    # The stroke-vs-fill heuristic alone isn't unique to a head/face layer -
    # a limb can have a single stroke-painted outline group too. Check
    # layers whose name suggests a head/face first, and only fall back to
    # scanning everything else if none of those have a detectable mouth.
    def head_first(layer):
        return 0 if re.search(r"head|face", layer.get("nm", ""), re.IGNORECASE) else 1

    for container_id, layers in iter_layer_containers(data):
        for layer in sorted(layers, key=head_first):
            shapes = layer.get("shapes")
            if not shapes:
                continue
            idx = find_old_mouth_index(shapes)
            if idx is None:
                continue
            old = shapes[idx]
            tr = next((it for it in old["it"] if it["ty"] == "tr"), None)
            if tr is None or tr["p"].get("a") != 0:
                continue  # animated or malformed transform - not safe to read a single position from
            pos = tr["p"]["k"]
            width = _shape_local_width(old)
            scale = (width / MOUTH_SHAPES["mouth-closed"]["size"][0]) if width else 0.35
            return container_id, layer["nm"], pos, scale
    return None


def describe_unadaptable_reason(data):
    """adapt()/auto_adapt() only know how to drive one rig convention: a
    single swappable mouth shape (find_mouth_layer above). When that's not
    found, give a specific reason instead of a generic failure, by
    recognizing other known-but-unsupported patterns we've actually seen in
    the wild, so the caller/user knows *why*, not just that it didn't work."""
    has_any_shapes = any(
        layer.get("shapes") for _, layers in iter_layer_containers(data) for layer in layers
    )
    if not has_any_shapes:
        return ("this character has no vector shapes at all (every layer is an image, ty=2) - "
                "it's a raster/frame-by-frame animation, not a vector rig, so shape-based mouth "
                "insertion can't apply to it regardless of layer names")

    beak_like = re.compile(r"beak|jaw|mouth|bill|lip", re.IGNORECASE)
    for _, layers in iter_layer_containers(data):
        for layer in layers:
            if not beak_like.search(layer.get("nm", "")):
                continue
            scale = layer.get("ks", {}).get("s")
            if isinstance(scale, dict) and scale.get("a") == 1 and len(scale.get("k", [])) >= 2:
                return (f"found a layer named '{layer['nm']}' that looks mouth-related and has its "
                        "own scale animation (a continuous open/close mechanism, likely matte-driven) "
                        "rather than a swappable discrete mouth shape - this rig convention isn't "
                        "automated yet, only the shape-swap convention is")
    return ("couldn't automatically find an existing mouth shape on this character "
            "(looked for a stroke-painted shape among otherwise fill-painted shapes "
            "on each layer, including inside nested precomps) - adapt it manually "
            "with adapt_character_lottie.py instead")


def adapt(data, mouth_layer_name, mouth_pos, mouth_scale, canvas_bg_color=(0.95, 0.96, 0.98, 1), mouth_container_id=None):
    data = copy.deepcopy(data)
    native_w, native_h = data["w"], data["h"]

    if mouth_container_id is None:
        target_layers = data["layers"]
    else:
        target_layers = next(a for a in data["assets"] if a["id"] == mouth_container_id)["layers"]
    head_layer = next(l for l in target_layers if l["nm"] == mouth_layer_name)
    old_idx = find_old_mouth_index(head_layer["shapes"])
    if old_idx is not None:
        del head_layer["shapes"][old_idx]

    new_groups = [make_mouth_group(name, mouth_pos, mouth_scale, spec) for name, spec in MOUTH_SHAPES.items()]
    head_layer["shapes"][0:0] = new_groups  # frontmost, same convention as our own templates

    # Re-parent every currently-unparented layer under one new null layer,
    # so a single scale/anchor/position edit (done later, at compose time,
    # once the target canvas is known) correctly resizes/repositions
    # everything regardless of the source rig's own internal parenting.
    max_ind = max(l["ind"] for l in data["layers"])
    wrapper_ind = max_ind + 1
    content_scale = NATIVE_STAGE / max(native_w, native_h)
    for layer in data["layers"]:
        if layer.get("parent") is None:
            layer["parent"] = wrapper_ind

    wrapper = {
        "ddd": 0, "ind": wrapper_ind, "ty": 3, "nm": "scene-root-scale", "sr": 1,
        "ks": {
            "o": {"a": 0, "k": 100}, "r": {"a": 0, "k": 0},
            "p": {"a": 0, "k": [NATIVE_STAGE / 2, NATIVE_STAGE / 2, 0]},  # placeholder; build_short.py sets this per canvas
            "a": {"a": 0, "k": [native_w / 2, native_h / 2, 0]},
            "s": {"a": 0, "k": [content_scale * 100, content_scale * 100, 100]},
        },
        "ao": 0, "ip": data["ip"], "op": data["op"], "st": 0, "bm": 0,
    }
    data["layers"].append(wrapper)

    background = {
        "ddd": 0, "ind": wrapper_ind + 1, "ty": 4, "nm": "background", "sr": 1,
        "ks": {
            "o": {"a": 0, "k": 100}, "r": {"a": 0, "k": 0},
            "p": {"a": 0, "k": [0, 0, 0]}, "a": {"a": 0, "k": [0, 0, 0]}, "s": {"a": 0, "k": [100, 100, 100]},
        },
        "ao": 0,
        "shapes": [{
            "ty": "gr", "nm": "background-group",
            "it": [
                {"ty": "rc", "nm": "bg-shape", "p": {"a": 0, "k": [NATIVE_STAGE / 2, NATIVE_STAGE / 2]}, "s": {"a": 0, "k": [NATIVE_STAGE, NATIVE_STAGE]}, "r": {"a": 0, "k": 0}},
                {"ty": "fl", "nm": "bg-fill", "c": {"a": 0, "k": list(canvas_bg_color)}, "o": {"a": 0, "k": 100}},
                {"ty": "tr", "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [100, 100]},
                 "r": {"a": 0, "k": 0}, "o": {"a": 0, "k": 100}, "sk": {"a": 0, "k": 0}, "sa": {"a": 0, "k": 0}},
            ],
        }],
        "ip": data["ip"], "op": data["op"], "st": 0, "bm": 0,
    }
    data["layers"].append(background)  # backmost

    return data


def auto_adapt(data, canvas_bg_color=(0.95, 0.96, 0.98, 1)):
    """adapt() with mouth-layer/position/scale derived automatically from
    the character's own existing mouth shape instead of requiring them as
    manual CLI arguments - what the live editor's Speak panel uses for an
    arbitrary uploaded character. Tries known rig conventions (currently:
    a single swappable mouth shape, searched through nested precomps too)
    and raises ValueError with a specific reason - distinguishing "no
    vector shapes at all", "found a mouth-like part but it's a different,
    not-yet-supported rig convention", and "nothing recognizable at all" -
    rather than silently guessing a placement with no basis in the
    artwork, or lumping every failure into one generic message."""
    found = find_mouth_layer(data)
    if found is None:
        raise ValueError(describe_unadaptable_reason(data))
    mouth_container_id, mouth_layer_name, mouth_pos, mouth_scale = found
    return adapt(data, mouth_layer_name, mouth_pos, mouth_scale, canvas_bg_color, mouth_container_id=mouth_container_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_path", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mouth-layer", default="Head", help="Name of the layer to add mouth shapes into")
    parser.add_argument("--mouth-pos", nargs=2, type=float, required=True, metavar=("X", "Y"),
                         help="Local position (in that layer's own coordinate space) for the mouth - reuse the old mouth's position")
    parser.add_argument("--mouth-scale", type=float, default=1.0,
                         help="Scale factor applied to our standard mouth sizes, to match this character's head size")
    args = parser.parse_args()

    data = json.load(open(args.in_path))
    result = adapt(data, args.mouth_layer, args.mouth_pos, args.mouth_scale)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(result, open(args.out, "w"), indent=2)
    print(f"Wrote {args.out}")
