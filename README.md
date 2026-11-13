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

## Status

First template built and verified. No AI selection/sequencing pipeline yet — that's next.

## License

MIT — see [LICENSE](LICENSE).
