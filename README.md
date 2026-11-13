# dotlottie-shorts

An open-source engine for generating short, vector-based animated clips (10–15s) as [dotLottie](https://dotlottie.io/) files from a text prompt — with embedded, synced audio.

## Why

Lottie/dotLottie animations are tiny, infinitely scalable, and run natively on web, mobile, and app runtimes — a much lighter alternative to baked video for things like product explainers, onboarding clips, and UI storytelling. There is currently no open tool that goes from a prompt to a short, templated, *multi-scene* animated clip with audio; existing AI-Lottie tools (Lottie AI, OmniLottie, Vanikya) stop at single looping clips (icons, spinners, one mascot animation).

This project narrows the problem to something actually buildable today: instead of freeform AI-generated animation (not reliable with current models), it composes short clips from a library of pre-built, parameterized templates (characters, backgrounds, motions), with AI responsible for selecting and sequencing templates and filling in text/timing/audio cues — not inventing animation from scratch.

## Scope (v0)

- Single use case: short product-explainer clips (problem → product UI mockup → benefit callouts → CTA)
- Fixed template library (pre-rigged characters/backgrounds, authored once, not AI-generated)
- AI step: given a prompt/product description, select templates + fill in text, colors, timing, and pick/sync an audio track
- Output format: [dotLottie](https://dotlottie.io/) (`.lottie`) with embedded audio, playable via [dotlottie-web](https://github.com/LottieFiles/dotlottie-web)
- Optional export: render to MP4 (frames + ffmpeg audio mux) for platforms that don't support Lottie playback

## Non-goals (for now)

- Freeform character animation, lip-sync, or narrative storytelling beyond the explainer template set
- Replacing or competing with LottieFiles' own tooling — this is meant to explore a gap (multi-scene generation with audio) above their current single-clip AI tools

## First template

`templates/characters/wave-character.json` — a hand-authored, valid Lottie animation (character made of simple shapes, waving one arm, 3s loop @30fps, 512x512). `templates/characters/wave-character.config.json` describes its parameterizable fields (background/skin/outfit color), matched by shape name rather than string-token replacement, so the source JSON stays valid, renderable Lottie on its own.

Package any template's Lottie JSON into a `.lottie` (dotLottie) container:

```bash
scripts/package-dotlottie.sh templates/characters/wave-character.json wave-character dist/wave-character.lottie
```

Preview it locally:

- Raw Lottie JSON (via `lottie-web`): serve the repo root and open `docs/preview.html`.
- Packaged `.lottie` (via `dotlottie-web`, the actual target runtime): open `docs/preview-dotlottie.html` the same way.

Both were verified to render and animate correctly in a browser.

## Sequencing pipeline

`src/build_short.py` is what actually turns templates into a *short* rather than a single looping clip: it takes a **plan** (a JSON list of scenes — which template, what param overrides, in what order), applies each scene's params by shape name, wraps each scene as a precomp asset, and places sequential precomp layers on one top-level timeline — so scene 2 only starts once scene 1's frames end, same mechanism Lottie/After Effects uses natively for cuts between shots.

```bash
python3 src/build_short.py --plan plans/demo-explainer.json --out dist/demo-explainer.lottie
```

`plans/demo-explainer.json` is a hand-written 3-scene example (problem → product → CTA, same `wave-character` template with different colors per scene) — verified in-browser to actually play three distinct scenes back to back on one timeline, not one clip looping.

**What's a stub right now:** the plan file is hand-written, not AI-generated. The real next step is a "plan generator" — given a prompt/product description plus the available templates' `.config.json` schemas, an LLM produces a plan JSON like `demo-explainer.json` automatically. That's a prompting/JSON-validation problem, not a new rendering mechanism — the composer already handles whatever plan it's given.

**What's still a toy:** with only one character template, "scenes" currently only vary by color. Real visual variety needs more templates (different characters, backgrounds, text overlays) — the composer and plan format don't change when those are added, since both are template-agnostic (every template is just a Lottie JSON + a `.config.json` describing its params).

## Status

First template + sequencing pipeline built and verified end-to-end (plan → multi-scene `.lottie` → confirmed playing distinct scenes in-browser). Not yet built: the AI plan-generation step, a second template, and audio.

## License

MIT — see [LICENSE](LICENSE).
