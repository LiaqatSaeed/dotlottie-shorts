#!/usr/bin/env python3
"""
Generate a scene plan (the input to build_short.py) from a free-text prompt,
using an LLM to pick templates and fill their declared params. This is the
piece that actually makes this "AI-generated," not hand-written JSON.

Reads the API key from the OPENAI_API_KEY environment variable only -
never pass it as a CLI argument (it would end up in shell history).

Usage:
  export OPENAI_API_KEY=sk-...   # set this in your own shell, once
  python3 src/generate_plan.py --prompt "a short for a coffee subscription app" \
      --out plans/generated.json
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
MODEL = "gpt-4o-mini"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from props import PROPS  # noqa: E402

PROP_HINTS = {
    "star": "celebration, achievement, a highlight moment",
    "heart": "love, care, a favorite, something people appreciate",
    "idea": "an insight, tip, or realization - a lightbulb moment",
    "map": "a journey, exploration, or plan - finding/going somewhere",
}


def discover_templates():
    """Load every *.config.json under templates/ so the model only ever
    sees templates and params that actually exist on disk."""
    configs = []
    for config_path in TEMPLATES_DIR.rglob("*.config.json"):
        with open(config_path) as f:
            config = json.load(f)
        template_rel_path = config_path.parent.relative_to(REPO_ROOT) / config["source"]
        configs.append({
            "templatePath": str(template_rel_path),
            "id": config["id"],
            "description": config.get("description", ""),
            "params": [
                {"key": p["key"], "type": p["type"], "default": p.get("default")}
                for p in config.get("params", [])
            ],
        })
    return configs


def build_system_prompt(available_templates):
    prop_list = "\n".join(f'- "{name}": fits {hint}' for name, hint in PROP_HINTS.items())
    return (
        "You write short-film scene plans for an animation pipeline. "
        "You may ONLY use the templates and param keys listed below - "
        "never invent a template path or a param key that isn't listed. "
        "Each scene must set every param the template declares.\n\n"
        f"Available templates:\n{json.dumps(available_templates, indent=2)}\n\n"
        "Each scene may also show a small decorative icon in the corner - "
        f"pick one ONLY if it genuinely fits that scene's content:\n{prop_list}\n"
        "Omit the 'prop' field entirely for a scene if none of these fit - "
        "do not force one in.\n\n"
        "Respond with a JSON object of this exact shape:\n"
        '{"animationId": "<kebab-case id>", "scenes": [\n'
        '  {"label": "<short label>", "template": "<templatePath from above>", '
        '"narration": "<one short spoken line for this scene, 4-10 words>", '
        '"prop": "<one of the icon names above, or omit this field>", '
        '"params": {"<paramKey>": <value matching that param\'s type>}}\n'
        "]}\n"
        "Plan 3 to 6 scenes that tell a coherent short story arc "
        "(e.g. problem -> product -> benefit -> call to action) using color "
        "choices that fit the mood of each beat, and narration lines that "
        "read naturally as a voiceover script across the whole short. Color "
        "params are [r, g, b, a] floats in 0-1. Every scene must include a "
        "'narration' line - it is required, not optional."
    )


def load_dotenv_key():
    """Minimal .env loader (no new dependency) - only read, never written by
    this script. The user creates .env themselves; see .env.example."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def call_openai(prompt, available_templates):
    api_key = os.environ.get("OPENAI_API_KEY") or load_dotenv_key()
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. Set it in your own shell first:\n"
            "  export OPENAI_API_KEY=sk-...\n"
            "Never pass it as a command-line argument or paste it in chat."
        )

    body = {
        "model": MODEL,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": build_system_prompt(available_templates)},
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"OpenAI API error {e.code}: {e.read().decode()}")

    return data["choices"][0]["message"]["content"]


def validate_plan(plan, available_templates):
    by_path = {t["templatePath"]: t for t in available_templates}
    if "scenes" not in plan or not isinstance(plan["scenes"], list) or not plan["scenes"]:
        raise ValueError("Plan must have a non-empty 'scenes' list")

    for i, scene in enumerate(plan["scenes"]):
        if not isinstance(scene.get("narration"), str) or not scene["narration"].strip():
            raise ValueError(f"Scene {i}: missing or empty 'narration'")
        if "prop" in scene and scene["prop"] not in PROPS:
            raise ValueError(f"Scene {i}: unknown prop '{scene['prop']}' - must be one of {list(PROPS)}")
        template_path = scene.get("template")
        if template_path not in by_path:
            raise ValueError(f"Scene {i}: unknown template '{template_path}'")
        if not (REPO_ROOT / template_path).exists():
            raise ValueError(f"Scene {i}: template file missing on disk: {template_path}")

        declared_keys = {p["key"] for p in by_path[template_path]["params"]}
        given_keys = set(scene.get("params", {}).keys())
        unknown = given_keys - declared_keys
        if unknown:
            raise ValueError(f"Scene {i}: unknown param keys {unknown}")

        for param_def in by_path[template_path]["params"]:
            value = scene.get("params", {}).get(param_def["key"])
            if param_def["type"] == "color":
                if (not isinstance(value, list) or len(value) != 4
                        or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in value)):
                    raise ValueError(
                        f"Scene {i}: param '{param_def['key']}' must be a [r,g,b,a] "
                        f"list of floats in 0-1, got {value!r}"
                    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    available_templates = discover_templates()
    if not available_templates:
        raise SystemExit("No templates found under templates/ - nothing to plan with.")

    raw = call_openai(args.prompt, available_templates)
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit(f"Model did not return valid JSON:\n{raw}")

    validate_plan(plan, available_templates)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2))
    print(f"Wrote {out_path} ({len(plan['scenes'])} scenes)")


if __name__ == "__main__":
    main()
