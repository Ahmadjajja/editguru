# FRAME Style Schema — `frame-style/1`

Status: design spec, 2026-11-09. A subset is implemented in `quick_style.py`;
this document also describes planned fields and is not a guarantee of support.
See `RECIPES_HANDOFF.md` and `RECIPE_TRANSFER.md` for current behavior.

## Product rules this schema enforces

1. **Reference-first.** A style is created only from a source: the creator's own
   video, a brand-supplied reference, or a starter. No blank-prompt editing.
2. **Deterministic.** `compile(style, footage_analysis, overrides)` is a pure
   function. Same inputs → same plan, byte for byte. Models are used to *extract*
   a style (reviewed and confirmed once) and to *translate* an explicit user
   request into ops. Models never run inside `compile`.
3. **No unrequested taste.** The agent may only change a style field when the
   user explicitly asks. `locked` fields need an explicit unlock.
4. **Provenance travels with assets.** Brand assets can only be used in projects
   for that brand.
5. **Explicit learning only.** Style updates come from `quick_learning`
   feedback (`reviewed: true`) and from edits the user makes, never from silence,
   undo, or a successful render.

## Existing architecture reused

| Need | Existing piece | Change required |
|---|---|---|
| Store a style | `quick_asset_library.save_recipe(kind='style')` | Accept `format: frame-style/1`; legacy flat recipes = `look` only |
| Reference video | `video_references` + `quick_reference_import` | Add `extract_style` action |
| Extracted assets (music, logo, outro) | Library kinds `audio`, `image`, `clip` | Add `provenance` to metadata; brand-scope check in `_visible` |
| Frame, color, volume | `quick_studio.DEFAULT` (`aspect`, `fit`, `brightness`, `contrast`, `saturation`, `volume`) | None |
| Captions | `quick_studio.transcript_captions` (6 words / 2.2 s, hardcoded) | Parameterize grouping; add font asset, case, emphasis color |
| Pacing | `tighten_pacing` + `editor.detect_silence` / `trim_pauses` | Expose silence threshold and padding |
| B-roll, logo, music layers | `quick_asset_assembly.plan_assembly` / `apply_assembly` | Placement rules resolve to items |
| Punch-in zooms | — | **New**: per-clip `scale` on the base track in `render_timeline` |
| Plan preview | `plan_assembly` (dry run, no write) | Generalize to `plan_style` |
| Live progress | `activity.json` + `log_activity` | Replace the 1.5 s poll with a push stream (SSE) |
| Undo / interrupt | Versioned commands, `expected_version`, `undo` | One op per version |
| Learning | `quick_learning` (explicit, evidence-backed) | Feedback can name a style field to update |
| Transcript | `editor.transcribe` (faster-whisper) + `analysis.json` cache | None |

## Schema

```jsonc
{
  "format": "frame-style/1",
  "name": "Brand X — launch spec",
  "revision": 3,                       // increments on every confirmed change
  "parent_style_id": null,             // library id this was derived from

  "provenance": {
    "source_kind": "brand_reference",  // brand_reference | own_video | starter
    "reference_project_ids": ["<32-hex>"],
    "reference_sha256": ["<sha256>"],
    "use_scope": { "type": "brand", "brand": "Brand X" },  // or { "type": "creator" }
    "rights_note": "Sent by Brand X 2026-11-09 for sponsored deliverables",
    "starter": null                    // { "style_id", "min_changed_fields" } when source_kind = starter
  },

  "frame":  { "aspect": "9:16", "fit": "cover" },                        // → studio
  "look":   { "brightness": 0.02, "contrast": 1.08, "saturation": 1.1 }, // → studio
  "audio":  { "voice_volume": 1.0,
              "music": { "slot": "music_bed", "volume": 0.18 } },        // → studio.volume + audio layer

  "pacing": {                                                            // → tighten_pacing
    "remove_pauses": true,
    "silence_db": -38, "min_pause_s": 0.35, "pad_s": 0.12,
    "cut_first_s": 0
  },

  "structure": {                                                         // beats from the transcript
    "max_duration_s": 45,
    "beats": [
      { "role": "hook",  "target_s": [1.5, 3.0] },
      { "role": "body" },
      { "role": "cta",   "slot_overlays": ["logo"] },
      { "role": "outro", "slot": "outro_card" }
    ]
  },

  "captions": {                                                          // → transcript_captions + studio.captions
    "source": "speech",
    "max_words": 3, "max_s": 1.2,
    "x": 0.5, "y": 0.72, "size": 0.055,
    "color": "#FFFFFF", "emphasis_color": "#FFD400",
    "font_slot": "caption_font",
    "case": "upper"                    // upper | sentence | as_spoken
  },

  "emphasis": {                                                          // NEW renderer support
    "punch_in": { "scale": 1.12, "on": "beat_start", "roles": ["hook", "cta"] }
  },

  "broll": {                                                             // → apply_assembly items
    "per_10s": 1.0, "max_s": 2.5,
    "placement": { "x": 0.5, "y": 0.5, "width": 1.0 },
    "source": "user_selected"         // user_selected | slot. Never auto-generated.
  },

  "slots": [                                                             // library assets the style needs
    { "id": "logo",         "kind": "image", "required": true,  "asset_id": "<32-hex>",
      "placement": { "x": 0.88, "y": 0.08, "width": 0.14 } },
    { "id": "music_bed",    "kind": "audio", "required": false, "asset_id": "<32-hex>" },
    { "id": "outro_card",   "kind": "clip",  "required": true,  "asset_id": "<32-hex>" },
    { "id": "caption_font", "kind": "font",  "required": false, "asset_id": null }
  ],

  "locked": ["captions.font_slot", "slots.logo", "frame.aspect"],

  "evidence": {                       // one entry per extracted field; drives the review screen
    "captions.max_words": { "method": "measured", "reference": "<32-hex>", "at_s": [3.1, 9.8] },
    "pacing.min_pause_s": { "method": "user_set" }
  }
}
```

`method` is one of `measured` (computed from the reference), `extracted` (an asset
pulled from the reference), `user_set`, or `feedback` (comes from a
`quick_learning` record id). The schema has no `inferred` method: a model guess
is shown to the user for confirmation and saved as `user_set`.

## Lifecycle

1. **Import reference.** Uses the existing `import_reference_video`.
2. **Extract (new `quick_style_extract.py`).** Deterministic measurement first:
   - shot lengths: FFmpeg `scdet`
   - pauses: `detect_silence`
   - color: `signalstats`
   - loudness: `ebur128`
   - caption grouping: transcript word timings vs. on-screen text regions

   Music separation (demucs) and logo/outro capture become library assets with
   `provenance`. A model only labels the beat roles.
3. **Review.** Every field shows its `evidence` clip. The user confirms or edits,
   then `save_recipe(kind='style')`. Nothing unconfirmed is saved.
4. **Plan (`plan_style`, dry run).** Compiles to an ordered list of *existing*
   commands, grouped by lane:
   - **pacing:** `tighten_pacing`, `split_clip`, `delete_segment`
   - **framing:** `set_studio` frame/look, clip `scale`
   - **captions:** `generate_studio_captions` with params
   - **brand:** `apply_asset_assembly` slots
   - **audio:** music layer

   The plan carries `plan_digest = sha256(style revision, source sha256,
   analysis digest, compiler version)`.
5. **Assemble live.** The client receives the full plan up front and animates
   each op as the server commits it (one op = one timeline version). Each lane
   is one "agent" cursor in the UI. These are real ops that already exist, shown
   as they land.
6. **Interrupt.** Pausing stops the queue at version N. The request is
   translated into explicit ops or a style-field change, shown to the user, and
   applied after they confirm. The remaining plan is then recompiled from
   version N. Manual timeline/slider edits use the same commands, so agent and
   hand edits share one history and one undo stack.
7. **Learn.** Explicit feedback (`record_edit_feedback`) can target a style field.
   An update creates `revision + 1` with `method: feedback`. Prior revisions
   stay restorable.

## Starter rule ("make it your own")

A style with `source_kind: starter` can't be exported as the creator's own until
`min_changed_fields` (default 5) non-provenance fields differ from the starter
revision. The count comes from a field-level diff, so it can be checked.

## Brand scope rule

A library asset whose provenance has `use_scope.type = brand` can only be placed
in a project whose `brand` matches. Enforced in `quick_asset_assembly._visible`
(the existing project-scope check), so it can't be bypassed.

## Build order

1. Commit the currently untracked modules (`quick_studio`, `quick_learning`,
   `quick_asset_*`, tests). They hold the pieces this spec depends on.
2. `frame-style/1` validation + `save_recipe` support, with legacy recipes still accepted.
3. `plan_style` compiler with captions/pacing/frame/look/slots, plus a
   determinism test (same inputs → same digest).
4. Renderer: caption font/case/emphasis, base-track `scale` for punch-ins.
5. Push stream for live assembly; one-op-per-version apply loop with interrupt.
6. `quick_style_extract` + review screen.
7. Brand scope and starter rule enforcement.

## Frontend: Swarmcut becomes the FRAME editor

Decision (2026-11-09): carry the whole Swarmcut artifact design into FRAME:
- Simple and Pro modes
- 9:16 program monitor with agent cursors
- seven-track timeline
- transcript word editing
- media pool, SFX pads, grade wheels, mix meters, scopes
- command bar and agent log
- brand/white-label panel

Source: claude.ai artifact "Swarmcut" (Preact + htm, single file).

What changes is where decisions and state live.

### Swarmcut keeps

- All UI and interaction: Simple/Pro, transcript click-to-cut, drag/snap clips, ripple, wheels, sliders, keyboard map.
- Canvas preview (`drawFrame`) for instant playback. No encode is needed to see an edit.
- The cursor choreography (`cursorTarget`, `agentStep` timing, lanes, areas). It now animates ops the server has committed instead of ops the browser invented.
- Word-timing pause detection with protected words (`silences`) and retake detection (`findRetakes`). These beat the server's energy-only `detect_silence`, so they move into the compiler as deterministic functions.

### FRAME backend takes over

| Swarmcut today | Combined |
|---|---|
| Project state in browser memory | `timeline.json` via versioned commands; the browser keeps an optimistic copy |
| `buildPlan` with hardcoded taste (teal/warm grade, "Warm Commercial" look, lime captions, whoosh on every B-roll cut, music −22 dB) | `plan_style(style)`: every value comes from the style. **No hardcoded creative defaults remain.** A field the style doesn't set stays untouched. |
| `runCommand` regex parser | Kept as a fast path for exact phrases. Anything else goes to the agent, which turns it into explicit ops or a style-field change, shown to the user before it's applied |
| One undo reverts a whole swarm pass | One op = one version, so the user can undo a single agent action; "revert pass" = restore the pre-pass checkpoint |
| Browser export (`mp4-muxer`, canvas) | Preview export only. Final export = FFmpeg `render_timeline` + `quick_studio.render`, with duration/audio verification |
| Media pool in memory | `quick_asset_library` + project assets; brand-scope enforced |
| Brand panel (app white-label) | Kept for the app's look. Separate from a video style's brand slots |

### Track mapping

| Swarmcut track | FRAME model |
|---|---|
| A-ROLL `v1` | `clips` (source in/out) |
| B-ROLL `v2` | `studio.layers` kind `video`/`image` |
| TEXT `t1` | `studio.captions` |
| SFX `s1` | `studio.layers` kind `audio` (library `sound_effect`) |
| MUSIC `a2` | `studio.layers` kind `audio` (style slot `music_bed`) |
| VOICE `a1` | `studio.volume` |
| GRADE `fx` | `studio` look fields; **gap:** Swarmcut has lift/gamma/gain wheels, temp, tint, exposure and looks. `quick_studio` only has brightness/contrast/saturation. Extend the FFmpeg grade (`colorbalance`, `colortemperature`, `lut3d`) so preview and export match |

### Gaps to close for parity

1. Grade parity between canvas preview and FFmpeg export: the wheels, temp/tint and looks.
2. Caption styles (Lime Pop, Stagger Stack, Karaoke, Minimal) and fonts in `quick_studio.caption_image`, which today hardcodes Arial Bold.
3. Synthesized SFX in Swarmcut become real `sound_effect` library assets.
4. Push channel (SSE) so cursors move when the server commits, not on the 1.5 s poll.
5. Layer limits (16 layers, 150 captions, 300 s) are enough for shorts; revisit for long-form.
