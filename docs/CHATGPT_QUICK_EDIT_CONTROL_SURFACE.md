# FRAME — ChatGPT Quick Edit Control Surface
**Priority:** P0 | **Date:** 2026-11-02 | **Status:** Build specification, not implementation evidence
**Owner:** Dante (creative approval); Codex (implementation + test); ChatGPT (independent verification)
**Source branch:** `feat/frame-product-pilot-2026-11-01`. Verify latest branches/PRs before writing code.

## One-line product
**Instagram Edits-speed editing controls, optimized for ChatGPT:** the VIDEO remains in ChatGPT's existing side viewer; FRAME occupies the LEFT control surface only. A creator selects moments, applies cuts, changes timing/captions/sound and previews immediately. No duplicated video player inside FRAME.

## Hard UX rule
Two surfaces, one synchronized editing state:
- **Right / host side viewer:** video playback and image. Treat as host-owned, not a FRAME-rendered preview.
- **Left / FRAME control panel:** everything actionable: compact timeline, clip selection, transport/timecode, trim/split, captions, audio, presets, conversational Katana instructions, undo, export.
- **If the actual ChatGPT host API cannot provide synchronized playhead/seek/preview controls to an app:** document the limitation; do not falsely claim native side-viewer integration. Make an honest adjacent browser proof with the same two-pane split. A separate FRAME player in the left panel is expressly prohibited.

## Intended interaction: creation in seconds
1. Open FRAME from ChatGPT with a source clip already attached or select source via supported host handoff. Avoid duplicate upload when host makes the file accessible.
2. Left UI initially shows waveform/thumbnail timeline, current time, selected clip and one oversized **Quick Edit** action.
3. Creator taps a timeline segment or drags a range; use magnetic snapping to silence, speech boundaries, or cut points where real analysis exists.
4. Actions appear contextually: **Trim**, **Split**, **Remove pause**, **Captions**, **Speed**, **Sound**, **Replace**. Strong default: **Cut dead air**.
5. A quick-edit interaction inspired by short-form editors: choose action -> see proposed change as a small diff (e.g., removed 0.7 s) -> **Apply** or **Undo**. One action, one outcome, no modal labyrinth.
6. Katana prompt stays one tap away: "Make the first 3 seconds tighter." It proposes precisely which timeline segments it would change, and applies after confirmation or in auto mode with instant undo.
7. Playback in the host side viewer reflects the active edit version. Download the actual MP4; show render progress/failure honestly.

## Layout blueprint (LEFT PANEL ONLY)
Top bar: `FRAME | project title | Undo ↶ | Export`
Current position: `00:03.2 / 00:17.8 | Play/Pause | - / + zoom` (controls synchronized with host video; if unavailable disable with clear explanation).
Primary zone: horizontally scrollable compact timeline with time ruler, clip blocks, cut markers, audio waveform/silence shading, caption markers and draggable playhead. No miniature video preview, no fake clip frames.
Selection zone: `Selected 00:02.1–00:04.5` and one horizontal context-toolbar: `Trim | Split | Delete | Captions | Speed | Audio`.
Quick edit zone: `Cut pauses` `Tighten hook` `Add captions` `Beat sync` as bounded presets backed by actual capabilities; unavailable actions visibly disabled.
Katana zone: minimal prompt field `Describe an edit…`, optional last action/decision, Apply/Undo.
Bottom: `Version 3 · Saved` and `Download MP4`.
Responsive: narrow control panel preserves timeline and primary action; secondary tools under single **More** menu. Keyboard shortcuts in desktop pilot: Space play/pause; S split; Cmd/Ctrl+Z undo; Delete remove selection (unless text input focused).

## Scope of v0 / must actually work
- Import one real source clip (via accessible file bridge or supported upload).
- Represent timeline in an explicit data structure: `source_id, segments[{id, source_in_ms, source_out_ms, timeline_in_ms, timeline_out_ms, playback_rate}], playhead_ms, selected_ids, captions, audio_changes, version`.
- Split at playhead; trim segment boundaries; delete selected segment and close gap; undo/redo; timeline duration recalculation. Persist project state.
- One high-value AI quick edit: identify and remove dead air with editable proposed boundaries, using existing transcription/silence detection where available.
- Captions toggle only if existing backend can render legible captions. Do not fake capabilities.
- Render export via the existing FRAME FFmpeg/media pipeline, then full-decode verify output. Side viewer plays the current exported/preview version where integration allows.
- Keep **control panel rendering** independent from **video rendering**: no duplicate preview on left.
- No new compositing engine, no new project library, no generic template remix, no advanced effects.

## Higgsfield quick edit inspiration — adaptation, not a dependency
Borrow the **mechanic** (minimal selection, fast contextual edit, immediate before/after, reversible action), not their branding or unverified API. Investigate exact feature behavior before claiming parity. Integrate Higgsfield only if an authorized, documented interface exists and materially lowers latency; otherwise use FRAME's current edit engine. No undocumented/private endpoints.

## Technical feasibility gate — first thing to test
1. Determine whether current ChatGPT app/plugin host can expose its *side viewer media*, current file, timeline timecode, seeking and playback synchronization to FRAME controls.
2. Record each capability as `SUPPORTED / UNSUPPORTED / UNKNOWN` with SDK/API citation and minimal live probe.
3. If host controls are unsupported, build the functional proof as a side-by-side browser workspace that mirrors the intended ChatGPT layout; preserve host-facing interface boundaries for later. Label this explicitly **browser fallback**, not "works inside ChatGPT."
4. Never claim a ChatGPT UI element can be embedded, moved or controlled unless proven.

## Build order / stop-scope
**A. Interaction skeleton**: left-panel timeline and selection, without video preview, real segments and undo.
**B. Real edit**: split/trim/delete + quick remove pauses; persist serialized edit decisions.
**C. Render and sync**: pass edit plan to current pipeline, playback on right where supported, export MP4.
**D. Proof**: 1 complete recorded test, inspect media & playhead events, fix only blockers.
Avoid storage, tutorials, onboarding animations and unrelated visual polish until A–D work.

## Acceptance test — 1 uninterrupted creator journey
Input: one rights-clear vertical talking-head clip, ideally 15–30 seconds with at least 2 noticeable pauses.
1. Open right-side video and left-side controls; prove no duplicate player in left FRAME UI.
2. Select segment at 00:03, Split, shorten next segment and Undo; observe accurate timeline changes.
3. Tap **Cut pauses**; show proposed removed intervals and apply; duration must shrink and rendered media must actually change.
4. Prompt **"Tighten the first three seconds"**; show the explicit proposed timeline change and confirm/revise it.
5. Play before/after in right-side viewer (or label browser fallback). Seek a cut from left timeline and prove correct position.
6. Download MP4; run FFmpeg full-decode. Record source/output SHA-256, duration, resolution, fps, audio track, and exact timeline JSON hash.
7. Reload and confirm saved edit plan, clip layout and exported video persist.
8. Dante independently watches with sound at 1x; grades **Publishable?** and **Would I edit another video this way?** Yes/No with one concrete reason each.

## Deliverables
- Implementation branch from verified active pilot; draft PR; no merge without review.
- `docs/tests/quick-edit-control-surface/TEST_NOTES.md`, `RUN_01.md`, sample project edit-plan JSON, actual input/output video links with hashes, and uninterrupted UI screen recording.
- Clear record of host synchronization proof, including blocked APIs; no synthetic demo presented as runtime proof.
- Independent review separate from implementation self-grading.

## Definition of done
**One clip, one quick cut, one real AI-assisted edit, one synchronized right-side preview, one exported MP4.** All without video displayed inside the FRAME left control panel. If host synchronization is blocked, the equivalent honest two-pane browser demo is the scoped fallback, not a passing ChatGPT integration.
