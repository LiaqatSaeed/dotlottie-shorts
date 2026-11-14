"""
A small library of simple decorative icon "props" a scene can display
(e.g. a map, a star) to tie the visual to what's being said, instead of
just a character on a flat color. Each prop is defined in its own local
coordinate space centered on (0, 0); embed_prop() in build_short.py places
it by wrapping it in a small layer positioned wherever the scene wants it.

Each entry in PROPS is a list of "group specs": {"shapes": [...], "style": {...}}.
"shapes" are raw Lottie shape items (el/rc/sh, no fill/stroke/transform).
"style" is the paint item for that group - a fill ("ty": "fl") or stroke
("ty": "st") dict, minus "nm"/"o" which embed_prop fills in.
"""

STAR_POINTS = [
    [0.0, -24.0], [5.88, -8.09], [22.83, -7.42], [9.51, 3.09], [14.11, 19.42],
    [0.0, 10.0], [-14.11, 19.42], [-9.51, 3.09], [-22.83, -7.42], [-5.88, -8.09],
]


def _straight_path(points, closed=True):
    zeros = [[0, 0] for _ in points]
    return {"ty": "sh", "nm": "path", "d": 1, "ks": {"a": 0, "k": {
        "c": closed, "i": zeros, "o": zeros, "v": points,
    }}}


PROPS = {
    "star": [
        {
            "shapes": [_straight_path(STAR_POINTS)],
            "style": {"ty": "fl", "c": {"a": 0, "k": [0.95, 0.75, 0.15, 1]}},
        },
    ],
    "heart": [
        {
            "shapes": [
                {"ty": "el", "nm": "lobe-l", "p": {"a": 0, "k": [-9, -6]}, "s": {"a": 0, "k": [22, 22]}},
                {"ty": "el", "nm": "lobe-r", "p": {"a": 0, "k": [9, -6]}, "s": {"a": 0, "k": [22, 22]}},
                _straight_path([[-19, -2], [19, -2], [0, 20]]),
            ],
            "style": {"ty": "fl", "c": {"a": 0, "k": [0.85, 0.25, 0.35, 1]}},
        },
    ],
    "idea": [
        {
            "shapes": [{"ty": "el", "nm": "bulb", "p": {"a": 0, "k": [0, -6]}, "s": {"a": 0, "k": [28, 28]}}],
            "style": {"ty": "fl", "c": {"a": 0, "k": [0.95, 0.85, 0.25, 1]}},
        },
        {
            "shapes": [{"ty": "rc", "nm": "base", "p": {"a": 0, "k": [0, 14]}, "s": {"a": 0, "k": [12, 10]}, "r": {"a": 0, "k": 2}}],
            "style": {"ty": "fl", "c": {"a": 0, "k": [0.55, 0.52, 0.5, 1]}},
        },
    ],
    # Note: avoid "st" (stroke) shape items here - they silently fail to
    # render in the dotlottie-web/ThorVG version this pipeline targets
    # (no console error, the shape is just never drawn). Thin rotated
    # filled rectangles reproduce the same look using only "fl", which is
    # already proven reliable everywhere else in this pipeline.
    # Groups are listed front-to-back (earlier = on top, same convention as
    # the character templates), so the decorative lines/marks must come
    # BEFORE the opaque paper background or it covers them.
    "map": [
        {
            "shapes": [{"ty": "rc", "nm": "x-mark-1", "p": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [12, 3]}, "r": {"a": 0, "k": 1.5}}],
            "style": {"ty": "fl", "c": {"a": 0, "k": [0.7, 0.25, 0.2, 1]}},
            "transform": {"p": [10, 14], "r": 45},
        },
        {
            "shapes": [{"ty": "rc", "nm": "x-mark-2", "p": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [12, 3]}, "r": {"a": 0, "k": 1.5}}],
            "style": {"ty": "fl", "c": {"a": 0, "k": [0.7, 0.25, 0.2, 1]}},
            "transform": {"p": [10, 14], "r": -45},
        },
        {
            "shapes": [{"ty": "rc", "nm": "fold-line", "p": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [43, 3]}, "r": {"a": 0, "k": 1.5}}],
            "style": {"ty": "fl", "c": {"a": 0, "k": [0.5, 0.4, 0.25, 1]}},
            "transform": {"r": 49},
        },
        {
            "shapes": [{"ty": "rc", "nm": "paper", "p": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [42, 48]}, "r": {"a": 0, "k": 4}}],
            "style": {"ty": "fl", "c": {"a": 0, "k": [0.92, 0.84, 0.64, 1]}},
        },
    ],
}
