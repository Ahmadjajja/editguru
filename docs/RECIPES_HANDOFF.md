# FRAME: Style Recipes & Live Assembly — Handoff (2026-11-10)

Shared doc (same content, editable): https://claude.ai/artifact/F3yCFxbSVsVzEeL6aMJWFt

## Summary
FRAME now assembles a video live in front of the user from a documented recipe; every step is saved, interruptible and repeatable. Branch `feat/style-swarm-2026-11-09`.

- **Style mode** (`/swarm`): upload raw talking-head footage, pick a style (saved from your own edit, measured from a reference video, or the FRAME starter); agent cursors apply it on a 7-track timeline. Pause, change anything, resume; FFmpeg export.
- **Recipe replay** (`/swarm?recipe=chatgpt-mastery-9x16`): agents replay the documented production of the ChatGPT Mastery 9:16 Mangaka ad — 15 real steps, the actual requests quoted, each step's real output shown, every real asset placed on the timeline. Change the intro and re-render with the production's own compositor.

Thesis: taste is the hard part, so FRAME never invents style. The user starts from something real; agents only perform documented, deterministic steps. The richer the documentation, the more of the whole feel is repeatable.

## Run
```
PORT=8890 sh ~/frame-creative-agent/work/frame-product/restart-local.sh
~/frame-creative-agent/work/frame-product/.venv/bin/pip install opencv-python-headless   # recipe re-render
```
Recipe: http://127.0.0.1:8890/swarm?recipe=chatgpt-mastery-9x16 — Replay production → Pause/Resume → Change & re-render (intro prompt, background brightness, ~30 s) → Download new cut / Approved final.
Style: http://127.0.0.1:8890/swarm — Upload footage (auto-transcribe) → Styles… (reference / save this edit / starter) → Assemble with style → Pause, change, Resume → Export MP4. Details: docs/HACKATHON_DEMO.md.

## How it works
- Editor = Swarmcut artifact + `swarm/frame-bridge.js`; FRAME's Python service is the source of truth. No model decides anything at run time.
- `frame-style/1` (`quick_style.py`, spec in docs/STYLE_SCHEMA.md): frame, look, pacing, captions, levels, asset slots, locked fields, evidence; every style names its source; brand assets only enter that brand's projects.
- Deterministic plan: style + word timings → ordered ops with a digest. No transcript → audio-level pauses.
- Live assembly: agent cursors perform the plan; changes made while paused are recorded and kept; tagged images land on their trigger words.
- Saving: every editor change → new `timeline.json` version via `sync_editor_state` (full editor state kept for exact reload). Single-pass FFmpeg renderer, up to 240 cuts.
- Reference measurement: frame shape, color vs your footage, pause tightness → numbered recipe → saved after the user confirms.
- Recipes (`quick_recipe.py`, `recipes/<name>/recipe.json`): steps with the request, what was done, real output, and real assets at final times (from timing.json, render.py scene map, caption cues, SFX cue sheets, cut list). Re-render = production's own V8/V9 scripts with only chosen values changed, cached per value set.

## Limitations
- Recipe replay reproduces one finished production; it does not yet apply its look to new footage or a new story. Only the intro prompt and background brightness are changeable. Timeline clips are a map, not a live composite. Rebuild matched byte for byte on the Mac per the record, not in a Linux sandbox (different FFmpeg).
- Style mode preview-only: grade wheels/temp/tint/looks, caption fonts and animation, built-in SFX/synth beat. Reference measurement: frame, color, pauses only. Style passes save in batched versions; editor undo reverts a whole pass. One video per project. Transcription untested on the Mac from Claude's side (fallback: paste script / import .srt).
- Branch not pushed yet; Mac disk was nearly full during the session.

## Next decisions (product: Dante + ChatGPT)
1. Recipe hub: every video saves its full recipe automatically — where it lives and what makes it complete.
2. Apply a recipe to new content: which parts are fixed brand identity vs per-video parameters.
3. Plain-language formulas → style/recipe approved once, then deterministic.
4. Export parity for preview-only features.
5. Push and decide whether this merges into the main FRAME line.

## Codex continuation — reusable content slice (2026-11-10)

A dedicated `/recipe-apply` screen now transfers portrait containment and white captions to new footage/script, with reviewed deterministic plans, durable pause/edit/resume and export provenance. See [RECIPE_TRANSFER.md](RECIPE_TRANSFER.md) for demo steps, tests and explicit limits. The original production replay remains unchanged. Shared services were not restarted, so they will not load these changes until deliberately restarted.
