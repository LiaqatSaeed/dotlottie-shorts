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
    """auto_adapt() tries each known rig convention (find_mouth_layer,
    find_beak_mechanism) before giving up - this only runs once neither
    matched, to give a specific reason instead of a generic failure, so
    the caller/user knows *why*, not just that it didn't work."""
    has_any_shapes = any(
        layer.get("shapes") for _, layers in iter_layer_containers(data) for layer in layers
    )
    if not has_any_shapes:
        return ("this character has no vector shapes at all (every layer is an image, ty=2) - "
                "it's a raster/frame-by-frame animation, not a vector rig, so shape-based mouth "
                "insertion can't apply to it regardless of layer names")

    for _, layers in iter_layer_containers(data):
        for layer in layers:
            if not BEAK_LIKE.search(layer.get("nm", "")):
                continue
            scale = layer.get("ks", {}).get("s")
            if isinstance(scale, dict) and scale.get("a") == 1 and len(scale.get("k", [])) >= 2:
                return (f"found a layer named '{layer['nm']}' that looks mouth-related with its own "
                        "scale animation, but find_beak_mechanism couldn't derive a consistent "
                        "open/close range from it (e.g. its keyframes don't share one x-scale "
                        "value) - this character's mechanism needs a closer look, not a guess")
    return ("couldn't automatically find an existing mouth shape on this character "
            "(looked for a stroke-painted shape among otherwise fill-painted shapes "
            "on each layer, including inside nested precomps) - adapt it manually "
            "with adapt_character_lottie.py instead")


def insert_mouth_shapes(data, mouth_layer_name, mouth_pos, mouth_scale, mouth_container_id=None):
    """Mutates data in place: swaps the mouth-layer's existing single mouth
    shape (if any) for our 4 named, independently-togglable mouth groups.
    Split out from adapt() so the canvas-wrapping step below can run for a
    character that doesn't need (or can't take) this shape-swap step at
    all - e.g. one whose mouth mechanism is driven by scale/matte instead
    (see find_beak_mechanism/embed_lip_sync_scale in build_short.py)."""
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


def add_canvas_wrapper(data, canvas_bg_color=(0.95, 0.96, 0.98, 1)):
    """Mutates data in place: wraps every currently-unparented top-level
    layer under one new null layer whose scale/anchor normalize this
    character's own native stage size to our 512-equivalent content size
    (so a single scale/anchor/position edit, done later at compose time
    once the target canvas is known, correctly resizes/repositions
    everything regardless of the source rig's own internal parenting),
    plus a background rect behind everything - the part of adapt() that's
    needed regardless of which mouth mechanism (if any) this character
    uses, since it's about canvas size, not mouths."""
    native_w, native_h = data["w"], data["h"]
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


def adapt(data, mouth_layer_name, mouth_pos, mouth_scale, canvas_bg_color=(0.95, 0.96, 0.98, 1), mouth_container_id=None):
    data = copy.deepcopy(data)
    insert_mouth_shapes(data, mouth_layer_name, mouth_pos, mouth_scale, mouth_container_id=mouth_container_id)
    return add_canvas_wrapper(data, canvas_bg_color)


BEAK_LIKE = re.compile(r"beak|jaw|mouth|bill|lip", re.IGNORECASE)


def find_beak_mechanism(data):
    """A second known rig convention, found on a real upload (a bird whose
    beak opens by *scaling* a matte-paired layer pair rather than swapping
    between discrete mouth shapes): look for layers, in any one container,
    whose name suggests a mouth/beak/jaw and whose own scale is animated -
    that's the rig's own designed open/closed range, read directly rather
    than invented, same principle as find_mouth_layer's use of tr.p. All
    matching layers in the same container are returned together since a
    mechanism like this is typically built from more than one paired part
    (e.g. a matte layer plus the shape it reveals) that must move in sync.
    Returns (container_id, [layer names], (min_y, max_y), fixed_x) or None."""
    for container_id, layers in iter_layer_containers(data):
        matches = []
        for layer in layers:
            if not BEAK_LIKE.search(layer.get("nm", "")):
                continue
            scale = layer.get("ks", {}).get("s")
            if isinstance(scale, dict) and scale.get("a") == 1 and len(scale.get("k", [])) >= 2:
                matches.append(layer)
        if matches:
            xs = {kf["s"][0] for l in matches for kf in l["ks"]["s"]["k"] if "s" in kf}
            ys = [kf["s"][1] for l in matches for kf in l["ks"]["s"]["k"] if "s" in kf]
            if len(xs) == 1 and ys:
                return container_id, [l["nm"] for l in matches], (min(ys), max(ys)), xs.pop()
    return None


def auto_adapt(data, canvas_bg_color=(0.95, 0.96, 0.98, 1)):
    """Tries known rig conventions in order and returns (adapted_data,
    lip_sync_mechanism) - what the live editor's Speak panel uses for an
    arbitrary uploaded character, so build_short.py knows how to drive
    speech on whichever mechanism was actually found, with no manual
    per-character setup. Currently tries: a single swappable mouth shape
    (searched through nested precomps too), then a scale/matte-driven
    mechanism (also searched through nested precomps). Raises ValueError
    with a specific reason - distinguishing "no vector shapes at all",
    "found a mouth-like part but it's a different, not-yet-supported rig
    convention", and "nothing recognizable at all" - rather than silently
    guessing a placement with no basis in the artwork, or lumping every
    failure into one generic message, when neither convention matches."""
    found = find_mouth_layer(data)
    if found is not None:
        mouth_container_id, mouth_layer_name, mouth_pos, mouth_scale = found
        adapted = adapt(data, mouth_layer_name, mouth_pos, mouth_scale, canvas_bg_color, mouth_container_id=mouth_container_id)
        return adapted, {"type": "shape"}

    beak = find_beak_mechanism(data)
    if beak is not None:
        container_id, layer_names, scale_range, fixed_x = beak
        adapted = add_canvas_wrapper(copy.deepcopy(data), canvas_bg_color)
        return adapted, {"type": "scale", "containerId": container_id, "layers": layer_names, "range": list(scale_range), "x": fixed_x}

    raise ValueError(describe_unadaptable_reason(data))


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
