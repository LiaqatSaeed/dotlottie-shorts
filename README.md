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

## AI plan generation

`src/generate_plan.py` is the actual "AI" part: given a free-text prompt, it calls an LLM (OpenAI, `gpt-4o-mini`) with the schemas of every template currently on disk (discovered from their `.config.json` files, so the model can never reference a template or param that doesn't exist) and gets back a scene plan - which templates, in what order, what params - validated against those schemas before anything is built. This is what replaces hand-writing `plans/*.json` yourself.

```bash
echo "OPENAI_API_KEY=sk-..." > .env   # gitignored, never commit this
python3 src/generate_plan.py --prompt "a short for a coffee subscription app" --out plans/generated.json
python3 src/build_short.py --plan plans/generated.json --out dist/generated.lottie
```

`plans/generated-brewly-audio.json` is a real, unedited output from this tool (prompt: a coffee-subscription app called Brewly) - it independently chose 4 scenes, thematically fitting colors per beat, and a full voiceover script line per scene ("Discover your new favorite coffee!" → "Explore unique roasters from around the world." → "Get fresh beans delivered weekly!" → "Cancel anytime, no worries!") - none of that was written by hand. Composing and playing it back confirmed the scene-to-scene colors and narration land exactly where the model placed them in the timeline.

## Audio

`src/generate_audio.py` synthesizes narration via OpenAI TTS (cached locally by text hash under `.cache/audio/`, gitignored, so re-running a plan doesn't re-pay for synthesis). `build_short.py` embeds it per scene as a real Lottie **Audio layer** (`ty: 6`) referencing a base64-embedded asset (the same embedding convention Lottie uses for inline images) - add a `"narration": "<line>"` field to any scene in a plan and it gets synthesized and wired in automatically.

This isn't guesswork: the dotLottie/Lottie docs don't publish the exact internal audio schema, so it was verified empirically - instrumenting `HTMLMediaElement.prototype.play` in the browser showed the player actually creates an `<audio>` element and calls `.play()` on a blob built from our embedded asset, once on a current player version (`@lottiefiles/dotlottie-web@0.83.2` - the pinned `0.47.0` used earlier silently did nothing with the audio layer, so the version matters).

**Known limitation:** each scene's audio layer spans the scene's full visual duration regardless of how long the synthesized line actually is - if narration runs longer than the scene, it'll be cut off. Not yet handled: sizing scene duration to narration length, or background music separate from narration.

## Lip sync

The character template has four mouth shapes - `mouth-closed` (thin resting line), `mouth-round` (tall/narrow, for strong vowels), `mouth-wide` (wide/flat, for sibilants/breathy consonants), and `mouth-mid` (fallback for everything else) - layered on top of the head so whichever is active actually shows.

`src/audio_envelope.py` decodes a scene's narration mp3 with ffmpeg and computes two per-frame features: RMS (loudness) and zero-crossing rate (a standard, cheap speech-processing proxy for how noisy/high-frequency a frame is - voiced vowels are loud with low ZCR, sibilants/breathy sounds are quieter but noisier with high ZCR). `build_short.py`'s `classify_viseme()` picks one of the four mouth shapes per frame from those two numbers, and turns that into hold keyframes toggling each shape's opacity. It's not real phoneme alignment, but it's driven by actual signal features, not just a volume toggle - the thresholds were picked by inspecting the RMS/ZCR values on a real narration clip, not guessed.

Verified by seeking the composed `.lottie` to specific frames the classifier assigned to each state and confirming the mouth shape actually matches - a wide flat shape where it picked "mouth-wide", a tall narrow one where it picked "mouth-round", etc.

**Known limitations:** still a rough 4-bucket classification, not real viseme/phoneme detection; thresholds (`SILENCE_RMS`, `WIDE_ZCR`, `ROUND_ZCR` in `build_short.py`) are fixed constants calibrated on one voice, not adaptive per-speaker.

## Second template

`templates/characters/nod-character.json` - a character standing with both arms at sides, idly head-bobbing, instead of waving. It reuses the exact same mouth shapes/coordinates and color-param convention as `wave-character`, so lip sync and the compositor work on it identically with no special-casing.

The point of a second template wasn't just "more variety" - it's proof the template system actually generalizes. `templates/characters/*.config.json`'s free-text `description` field is what the AI plan generator reads to decide which template fits a given scene; giving `nod-character` a "calmer/more neutral... reflective or explanatory beats" description and testing with a meditation-app prompt (`plans/generated-calmly.json`) produced exactly the expected split - the model picked `nod-character` for the calm/explanatory scenes and `wave-character` for the energetic "Start your journey today!" call-to-action, on its own, from that one description field.

## Status

Prompt → AI-generated plan (choosing between 2 templates, with narration) → multi-scene `.lottie` with embedded audio and amplitude-driven lip sync works end-to-end, verified in-browser (pose/motion/mouth-shape/colors) and functionally (actual audio `.play()` calls, correct per-template selection). Not yet built: scene durations that adapt to narration length, and a second LLM provider (Anthropic) as an alternative to OpenAI.

## License

MIT — see [LICENSE](LICENSE).
