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

A scene's duration now adapts to its narration automatically: `build_short.py` synthesizes the audio first, measures its real length (`audio_envelope.audio_duration_seconds`, +0.3s padding), and if that's longer than the template's default length, stretches the scene's (and every one of its layers') out-point to fit - layers with no keyframes past the template's original length simply hold their last pose for the extra time (verified: a character mid-wave correctly settles to resting arms-down rather than freezing mid-gesture or disappearing), while lip sync is computed *after* this extension so the mouth keeps moving for the narration's full real length, not just the template's original 3s. A short line leaves the scene at the template's normal length; nothing shrinks.

**Known limitation:** background music separate from narration isn't supported yet - only one audio layer (the narration) per scene.

## Lip sync

The character template has four mouth shapes - `mouth-closed` (thin resting line), `mouth-round` (tall/narrow, for strong vowels), `mouth-wide` (wide/flat, for sibilants/breathy consonants), and `mouth-mid` (fallback for everything else) - layered on top of the head so whichever is active actually shows.

`src/audio_envelope.py` decodes a scene's narration mp3 with ffmpeg and computes two per-frame features: RMS (loudness) and zero-crossing rate (a standard, cheap speech-processing proxy for how noisy/high-frequency a frame is - voiced vowels are loud with low ZCR, sibilants/breathy sounds are quieter but noisier with high ZCR). `build_short.py`'s `classify_viseme()` picks one of the four mouth shapes per frame from those two numbers, and turns that into hold keyframes toggling each shape's opacity. It's not real phoneme alignment, but it's driven by actual signal features, not just a volume toggle - the thresholds were picked by inspecting the RMS/ZCR values on a real narration clip, not guessed.

Verified by seeking the composed `.lottie` to specific frames the classifier assigned to each state and confirming the mouth shape actually matches - a wide flat shape where it picked "mouth-wide", a tall narrow one where it picked "mouth-round", etc.

**Known limitations:** still a rough 4-bucket classification, not real viseme/phoneme detection; thresholds (`SILENCE_RMS`, `WIDE_ZCR`, `ROUND_ZCR` in `build_short.py`) are fixed constants calibrated on one voice, not adaptive per-speaker.

## Three templates, three narrative roles

- `wave-character` - greeting/energetic (waves one arm)
- `nod-character` - calm/explanatory (both arms at sides, idle head-bob)
- `point-character` - feature callout/"look at this" (one arm raised, pointing, with a small repeated emphasis wag)

All three share the exact same mouth shapes/coordinates and color-param convention, so lip sync and the compositor need zero special-casing to support any of them - adding a template is just: author the Lottie JSON with those same shape names, write a `.config.json` with a free-text `description`, done.

That `description` field is what the AI plan generator actually uses to decide fit, and it's been tested past just two options: a budgeting-app prompt spanning all three narrative roles at once (`plans/generated-penny.json`) made the model independently pick `wave-character` for "Welcome to Penny," `point-character` for "Track expenses with just one tap!," and `nod-character` for "Your data remains completely private" - matching each template's intended role with no hints beyond the description text.

## A complete example: "The Explorer"

`plans/the-explorer.json` - a real 4-scene story generated from one prompt ("a curious little explorer finds an old map, sets off, points out a hidden treasure spot, then explains they'll share it with everyone back home"), using all three templates for their intended narrative roles (nod → wave → point → nod) with full narration and lip sync, composed to `dist/the-explorer.lottie` (12s).

`scripts/make_standalone_preview.py` packages any composed `.lottie` into a single self-contained HTML file (the `.lottie`'s bytes embedded as a base64 data URI, so there's no fetch and no local server needed) - open it by double-clicking, nothing to run:

```bash
python3 scripts/make_standalone_preview.py --lottie dist/the-explorer.lottie --out dist/the-explorer-standalone.html --title "The Explorer"
```

## Character art upgrade

All three templates now have legs, shoes, hair, and rounded hands - not just a head/body/arm "shape blob." Added by inspecting a free, properly-rigged human-character animation on the LottieFiles marketplace (`Character.lottie`, bezier-path art with separate Head/Body/Arm/Leg layers) for reference - its generic fill names and 1080x1080 canvas made directly reusing it more work than it was worth right now (see `external-refs/` locally, gitignored, not redistributed), but it clarified exactly what was missing from our own shapes, which were then added directly using the existing color-param system (no new params needed - hair/shoes use fixed colors, legs reuse `character-outfit-fill`).

## Props

`src/props.py` defines a small library of decorative icons - `star`, `heart`, `idea`, `map` - each a few simple filled shapes (no strokes: see the note in that file about why). `build_short.py`'s `embed_prop()` places one in a scene's top-right corner as its own layer when the plan sets a `"prop"` field, so a scene can show something relevant to what's being said instead of just a character on a flat color.

The AI plan generator now offers these to the model with a one-line hint each (e.g. "map: fits a journey, exploration... finding/going somewhere") and explicitly tells it to omit the field rather than force one in. Tested with a travel-app prompt (`plans/generated-roamly.json`): the model picked `map` for "discovering new destinations," left the tips scene with no icon, and picked `heart` for "people love how easy it is" - selective, contextual use, not every scene getting a badge.

Caught and fixed two real bugs while building this: the map's stroke-based line/X-mark silently failed to render (no console error) - this player's ThorVG build appears not to support `"st"` stroke shape items, so they were rebuilt as thin rotated filled rectangles instead; and the same front-to-back group-ordering mistake as before (the opaque paper background was listed first/frontmost, hiding the decorative lines behind it).

## Video export (MP4)

Since a `.lottie` only plays in a Lottie-aware player, distributing it anywhere else (YouTube, Slack, a plain `<video>` tag) means rendering it to a real video file. The approach that actually works:

1. `docs/export-frames.html?src=<lottie>&frames=<N>&prefix=<name>` - loads the composed `.lottie`, explicitly calls `setFrame(i)` for every frame (not continuous autoplay - see why below), waits two `requestAnimationFrame`s for the paint to land, captures the canvas via `toBlob()`, and `POST`s each frame as a PNG to `scripts/export_server.py`'s `/save` endpoint (a tiny custom static-file server with one extra endpoint, since filesystem downloads are OS-sandboxed in this environment).
2. `scripts/extract_audio_track.py` pulls every scene's embedded narration straight out of the composed `.lottie`'s own assets (no re-synthesis) and mixes them into one audio track at their correct start times with ffmpeg's `adelay`+`amix`.
3. `scripts/assemble_video.py` encodes the PNG sequence into a video with ffmpeg, then muxes in that audio track (deliberately without `-shortest`, since narration is usually shorter than its scene and the silence after it ends is correct - using `-shortest` would wrongly cut the video short to match the audio).

**Why frame-by-frame instead of just recording playback in real time (the obvious approach):** that was the first attempt - `canvas.captureStream()` + `MediaRecorder`, with scene audio captured by routing each narration `<audio>` element through a `MediaStreamAudioDestinationNode`. It produced an empty or near-empty file every time, in both the embedded preview pane and real Chrome. A plain `requestAnimationFrame`-driven canvas (no dotLottie involved) recorded perfectly in the same environment, which rules out `captureStream`/`MediaRecorder` support generally and points at something specific to how this player paints the canvas during continuous autoplay in an automated context - possibly the "freeze on offscreen" behavior the dotlottie-web README documents misfiring. Rather than chase that further, the pipeline switched to explicit per-frame `setFrame()` calls, which sidestep continuous playback entirely and are the same mechanism already proven reliable throughout this whole project (every lip-sync/template/prop check in this README was verified by scrubbing to exact frames).

Verified end to end on "The Explorer": 360 PNG frames captured and spot-checked against known-good frames from earlier manual verification (pixel-identical), assembled into a 12.000s H.264 video, muxed with a real AAC audio track extracted from the same file, confirmed via `ffprobe` to have both streams and real encoded audio packets throughout.

**Known limitations:** the frame-capture step needs a browser to drive it (`docs/export-frames.html`), not a single unsupervised CLI command yet; a 360-frame short takes on the order of 10-15s of real wall-clock time to capture (roughly one render per `requestAnimationFrame` pair, plus a network round-trip per frame).

## Runtime theming (Lottie Slots)

Every template's `character-skin-fill`, `character-outfit-fill`, and `bg-fill` color properties now carry a `"sid"` (slot ID: `skinColor`/`outfitColor`/`backgroundColor`) - the native Lottie mechanism for marking a property as runtime-overridable, independent of our own Python color-param system. This means a single exported `.lottie` can be re-colored by *any* downstream consumer - a website, an app, a buyer who licenses the character - entirely at runtime via the player's API, with zero regeneration through this pipeline. That's the point of staying Lottie-native rather than converting everything to video: the deliverable itself stays editable after the fact.

Verified in-browser (`docs/preview-slots.html`) on a single unmodified `wave-character.lottie`: clicking buttons called `dl.setColorSlot('outfitColor', [...])` live, and both the body and legs (which share that slot) recolored together while the shoes (an unslotted, fixed color) correctly stayed put - confirmed for all three slots (outfit, skin, background) simultaneously on one loaded instance, no rebuild.

**Relationship to the build-time color params:** these are two independent mechanisms that happen to target the same properties. The Python pipeline (`build_short.py`) still bakes in colors at compose time per scene, driven by the AI-generated plan - that's unchanged and is how this project actually varies colors scene-to-scene today. The slot IDs are an *additional* capability layered on top, for a downstream consumer to further re-theme an already-built `.lottie` without going through this pipeline at all.

## Aspect ratio

Every template is authored on a 512x512 stage, but a short actually needs to target the format its destination requires - vertical 9:16 for YouTube Shorts/TikTok/Reels, which is now the default, plus 1:1, 16:9, and 4:5. Rather than rescale any character art, `build_short.py`'s `fit_scene_to_canvas()` resizes just the background to fill the new canvas and shifts every other layer by the offset that recenters the original 512x512 content within it - so no template file needs touching to support a new shape. Pass `--aspect-ratio` to either `generate_plan.py` (stored in the plan) or `build_short.py` (overrides the plan).

Verified visually at 320x568 (9:16): the background fills edge-to-edge with no mismatched letterboxing, and the character/prop stay centered as a group.

**Known limitation:** a scene's prop icon is positioned relative to the original 512x512 square's corner, now recentered - so on a much taller/wider canvas it sits near the character rather than at the true corner of the full frame.

## Character redesign: an actual face

All three templates now have eyes (white sclera + dark pupil + a tiny highlight dot for sparkle), asymmetric raised eyebrows (one arched higher than the other, for a goofy/curious look rather than a neutral one), and rosy cheek blush - on top of the legs/shoes/hair from the earlier art upgrade. Added programmatically (a small Python script inserts the same 10 shape groups into each template's head, matching their shared coordinate conventions), not hand-edited three times.

Hit the exact same front-to-back ordering mistake as every previous shape addition in this project, twice in one go: sclera was listed before pupil/highlight (hiding them completely), and separately the eyebrows were initially too close to the hairline and the same color, making them blend into it rather than actually being hidden - two different bugs that looked similar at a glance, caught by zooming in on the actual rendered face rather than assuming the insertion worked.

## Status

Prompt → AI-generated plan (choosing between 3 expressive characters - eyes, eyebrows, blush, legs - by narrative role, with narration and props, in a chosen aspect ratio - 9:16 by default) → multi-scene `.lottie` with embedded audio, amplitude-driven lip sync, and duration-aware scenes, runtime-re-themeable via native Lottie Slots → exportable to a real MP4 with synced audio for channels that can't play `.lottie` directly. Not yet built: a single unsupervised CLI for the video export (the frame-capture step still needs a browser), background music separate from narration, and a second LLM provider (Anthropic) as an alternative to OpenAI.

## License

MIT — see [LICENSE](LICENSE).
