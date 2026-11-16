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

Caught and fixed two real bugs while building this: the map's stroke-based line/X-mark silently failed to render (no console error) - at the time this looked like this player's ThorVG build not supporting `"st"` stroke shape items, so they were rebuilt as thin rotated filled rectangles instead; and the same front-to-back group-ordering mistake as before (the opaque paper background was listed first/frontmost, hiding the decorative lines behind it). **Correction, found later:** a third-party character's stroke-painted mouth rendered fine in this same player (see "Making a third-party character speak" below), so the "`st` isn't supported" diagnosis above was most likely wrong - the ordering bug was probably the whole story, and the stroke rebuild was unnecessary (left as-is since it works, not reverted).

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

## Voice engine (free, local TTS option)

Narration can now use [Kokoro TTS](https://github.com/thewh1teagle/kokoro-onnx) instead of OpenAI - free, open source (Apache 2.0 weights, MIT wrapper), 54 voices, runs locally on CPU, no per-call cost. `generate_audio.py` picked between whichever engine is requested, caching by `(engine, voice, text)` so switching engines never collides with the other's cache. Run `scripts/setup_kokoro.sh` once (installs `kokoro-onnx`/`soundfile`, downloads the ~340MB model files into `.cache/kokoro/`, gitignored), then pass `--voice-engine kokoro --voice af_heart` (or any of the 54) to either `generate_plan.py` (stored in the plan) or `build_short.py` (overrides it).

**One real compatibility bug found and worked around, not guessed at:** the currently-published `kokoro-onnx` PyPI package (0.4.7) throws an `ONNXRuntimeError` on the newer `model-files-v1.1` release - that release changed the model's `speed` input from int32 to float, and 0.4.7 still sends int32. `setup_kokoro.sh` deliberately downloads `model-files-v1.0` instead, which matches what 0.4.7 actually expects.

Verified end to end: real Kokoro-synthesized audio embedded in a composed `.lottie`, and lip sync correctly reacting to it (closed mouth at a silent frame, open mouth where the voice starts) - confirming the whole pipeline (duration-fitting, audio embedding, lip sync) works identically regardless of which engine produced the narration.

## Eye blinking and looping body language

Two gaps fixed together, since both were about a character going dead/static over a long line:

**Eyes now blink.** Every eye part's vertical scale is keyed to snap shut and reopen every ~2.5s for the scene's whole duration (hold-style keyframes, same crisp on/off technique as the mouth visemes - a blink is fast enough that easing it would just look like squinting). Phase is staggered per scene index, not truly random, so output stays reproducible from the same plan.

**Gestures now loop instead of freezing.** Previously, a scene stretched by a long narration line would play its one authored gesture (the wave swing, the head-bob, the point wag) once in the first ~3s and then stand completely still for the rest - the character's own motion was never extended, only its audio/lip-sync was. `tile_keyframes()` now repeats whichever layer's animated property drives that template's signature motion (`right-arm`/`pointing-arm`'s rotation, or `character-body-head`'s bob position for nod) across the scene's real final duration, dropping each cycle's redundant boundary keyframe so it doesn't double up at the seam.

Verified on a scene stretched to 341 frames (vs. its 90-frame template default): the wave's arm was still actively mid-swing at frame 315, matching the tiled pattern rather than frozen since frame 90, and eyes closed/opened exactly at their scheduled blink frames (20, 95, 170, 245, 320).

**Still open (not done yet):** gaze movement (the eyes don't shift to look anywhere - point-character looking toward its own pointing hand would be the obvious next step) and real pose variety (every template still has exactly one signature gesture; looping it is an improvement over freezing, but it's not new body language).

## Local LLM option (Ollama)

Plan generation doesn't actually need OpenAI specifically - it just needs something that follows instructions and emits valid JSON, and Ollama exposes an OpenAI-compatible `/v1/chat/completions` endpoint, so `generate_plan.py`'s `call_llm()` is one code path with a different base URL/auth per engine, not two implementations. Pass `--llm-engine ollama --llm-model qwen2.5:7b-instruct` (or `llama3.1:8b`, both already usable via `ollama serve`) to run plan generation fully locally, free, no API key.

This is a deliberate, incremental strategy, not a wholesale swap: keep OpenAI where it's still clearly better, and replace each piece with an open-source/local equivalent as that piece proves itself - narration already has this (Kokoro), now planning does too.

**Honest comparison, not just a disclaimer:** ran the same prompt through both. Template selection matched OpenAI's (wave → point → nod, correctly following each template's narrative-role hint) and the plan passed validation on the first try - no hand-holding needed. But narration came out terser ("Welcome to Penny" vs. a fuller sentence) and prop selection was visibly weaker: it picked `map` ("a journey, exploration, finding/going somewhere") for a privacy-explanation scene, a poor semantic fit that OpenAI's runs didn't produce. That's the real, current cost of going local for this piece - not a hypothetical one.

## Interactive editor

`docs/editor.html` is the actual answer to "it just plays by itself and I miss it if I'm not watching" - a real page with playback controls (play/pause, a scrub bar bound to the live frame) and live overrides for mouth shape, eyes, and color theme, instead of a short that only ever autoplays once. Load any `.lottie` by file picker or URL.

The overrides reuse the exact Lottie Slots mechanism already proven for runtime color theming - nothing new was invented for mouth/eyes. `embed_lip_sync()` and `embed_blinking()` now attach a `"sid"` to the opacity/scale properties they generate (`mouth-closed`/`mouth-mid`/`mouth-round`/`mouth-wide`, and one shared `eyesScale` sid across all six eye-part groups), so a host page can call `setScalarSlot()`/`setVectorSlot()` to force a specific mouth shape or eye state, overriding the baked lip-sync/blink animation - and `clearSlot()` hands control back to the automatic animation. Verified this actually overrides an *animated* property (not just a static default, which is all the color slots had been tested against before): forced "wide" stayed locked in through multiple playback frames that the baked animation would otherwise have changed, and clearing it resumed automatic lip sync.

Also confirmed outside this project's own tooling: a `.lottie` built by this pipeline was uploaded to the LottieFiles workspace and played with working audio there too - real third-party validation of the audio-embedding approach, not just this project's own player.

## Gaze movement

Eyes blinked but never looked anywhere until now. `embed_gaze()` keys each pupil/highlight's position to glance away from center and back periodically (same crisp hold-then-snap technique as blinking, since real saccades are near-instant snaps followed by a hold, not an eased glide) - a `"gazeOffset"` sid, same pattern as the mouth/blink slots, so a host page could expose this as a live override too later.

The part worth calling out: this isn't just idle wandering for every template. `point-character` is biased to look toward its own raised/pointing arm instead of wandering randomly - the one place in this project so far where eye movement and body language are made to agree with each other on purpose, rather than animated independently. Verified both behaviors directly from the generated keyframes and in-browser: point-character's pupils shift toward its pointing side (matching its own arm's direction) while wave-character's idle wander starts the opposite way (left first) - genuinely different per-template behavior, not the same animation reused.

## Making a third-party character speak

`scripts/adapt_character_lottie.py` takes a `.lottie` this pipeline didn't author and adds our standard mouth shapes to it, so it can speak via the existing lip-sync/audio machinery - which only ever looked for shapes by *name*, never cared which character drew them. Tried on a real third-party asset (a free LottieFiles walking-character animation, bezier-path art, not our flat shapes): identified its existing static mouth by elimination (the only stroke-painted group among its head's shapes, everything else - eyes - uses fills), replaced it with our four named mouth groups sized to match, and verified real lip sync driven by actual narration audio - mouth closed at frame 0, open at frame 10, matching the synthesized speech.

The harder problem this exposed: that character was authored on its own native 1080x1080 stage, not our 512x512 - and `fit_scene_to_canvas()` only knew how to pad/recenter content assuming 512. Rather than rescale the character's own path coordinates (risky - would mean touching geometry, stroke widths, and a mixed parenting rig where some layers are parented to its control null and others aren't), the adapt script instead wraps every currently-unparented layer under one new null layer whose anchor/scale normalize the native stage to our 512-equivalent size; `fit_scene_to_canvas()` now recognizes that layer by name and only needs to set *where* it lands for a given output canvas, leaving our own three natively-512 templates' handling completely untouched.

**Known rough edge:** the adapted character's hair tip clips slightly at the very top of the frame at some points in its walk-bob cycle - a minor framing nit, not a correctness bug. Blinking and gaze don't apply to it (its eyes aren't named the way ours are), and its walk cycle still freezes if narration runs longer than its own ~1s loop (the same freezing problem our own templates had before `loop_body_motion()`, not yet generalized to arbitrary third-party rigs). Correcting a claim from the Props section above while this was being worked on: that stroke shapes "silently fail to render" on this player looks wrong - this character's stroke-painted mouth rendered fine before being replaced, so the real cause of the earlier map-prop bug was almost certainly the layer-ordering mistake alone.

## Live "type a phrase" speaking field

The editor now has a text field: type anything, pick a character (any of our 3, or your own uploaded/adapted one), hit Speak, and it composes a fresh one-scene `.lottie` on the spot and swaps it into the already-open preview - the actual answer to "can we have a field where I type a phrase and the character starts speaking it."

`scripts/export_server.py` gained a `POST /speak` endpoint that builds a one-scene plan in memory and runs it through the exact same `compose()`/`package_dotlottie()` used by the CLI pipeline - no separate "live" code path to keep in sync with the real one. Synthesizes with Kokoro (free, local, no per-request cost - the obvious choice for something meant to be typed into repeatedly). The server now runs under this project's own virtualenv (`.venv`) so `kokoro-onnx` is actually importable in that process, not whatever system Python happens to be on `PATH`.

Verified both paths live in-browser: the wave-character spoke a typed sentence with mouth closed at frame 0 and open partway through, and switching the dropdown to the third-party adapted character (from the section above) spoke a different typed phrase just as correctly - confirming this feature works for any character the pipeline knows about, not just our own three.

## Status

Prompt → AI-generated plan (OpenAI or free local Ollama for planning, OpenAI or free local Kokoro TTS for narration - 3 expressive characters chosen by narrative role, with props, in a chosen aspect ratio - 9:16 by default) → multi-scene `.lottie` with embedded audio, amplitude-driven lip sync, blinking, and gaze (biased toward its own gesture for point-character), and duration-aware scenes whose gestures loop instead of freezing → openable in an interactive editor with playback controls and live mouth/eyes/color overrides (all via native Lottie Slots) → exportable to a real MP4 with synced audio for channels that can't play `.lottie` directly. Not yet built: real pose variety (each template still has one signature gesture - gaze now agrees with it, but it's still only one gesture), a single unsupervised CLI for the video export (the frame-capture step still needs a browser), and background music separate from narration.

## License

MIT — see [LICENSE](LICENSE).
