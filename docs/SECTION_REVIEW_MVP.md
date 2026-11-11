# FRAME quick-edit MVP — section playback and stacked revisions

Status: implementation contract; NOT evidence of a working feature.
Priority: P0 for November 2, 2026 demo. Keep scope to a single working desktop/browser editing flow.
Product line: **"Play the section. Leave revisions as you go."**

## Core interaction

1. Open a project with a real uploaded video and a playable preview in the side display; the chat/control surface stays compact.
2. Choose a section (start/end source-media timecodes) and click **Play section**. Only that section plays, with pause/replay/seek.
3. While reviewing, pause at any frame and enter a natural-language change. **Add revision** creates a pin on the current playhead and immediately shows it in the section list; playback need not restart and no render is required to capture a note.
4. Continue playback and stack multiple notes. Each note persists with project ID, stable source-video time anchor, section ID, text, creation order, status and revision-set ID.
5. Select **Apply revisions** once to hand the complete ordered set to Katana/the existing edit pipeline. Generate one new saved version/checkpoint, while preserving the input version and every note. Show progress, errors and the playable result, not a fake success state.
6. Each note supports **keep / adjust / remove** before application. After application, comparison/revert must not destroy the previous playable version. Notes and pins remain editable and visible across refresh.

## Technical decisions and guardrails

- Anchor pins to **original/source timeline timestamps**, not only output time, so cuts do not shift later notes. Also store the version ID and mapping to output time when available.
- Section boundaries use source media milliseconds; start inclusive, end exclusive; validate 0 <= start < end <= duration.
- Playback is real video (HTML video element or existing project playback); pin creation reads the actual player currentTime. No mock player or hardcoded timestamp.
- Apply is an explicit transaction from a frozen revision-set snapshot. Prevent duplicate submission; atomic status transition; idempotency token preferred. Preserve failed instructions for retry.
- Group instructions by section and timing and let the editor resolve contradictions with a visible explanation or explicit conflict, rather than silently dropping notes.
- Reuse the repository's existing import, revision, render, checkpoint and MP4 export infrastructure where possible; do not build a new editing engine or unrelated UI.
- ChatGPT-compatible layout goal: control/revision UI on the left; actual video on the side. If embedded ChatGPT integration is unavailable, demo the same workflow in FRAME's browser pilot without pretending native ChatGPT integration exists.

## Minimal data example

```json
{
  "project_id": "project-123",
  "base_version_id": "v1",
  "section": {"id": "s2", "source_start_ms": 5000, "source_end_ms": 12000},
  "revision_set_id": "rs1",
  "notes": [
    {"id": "n1", "source_time_ms": 6000, "instruction": "Tighten pause before reveal", "status": "queued"},
    {"id": "n2", "source_time_ms": 8000, "instruction": "Enlarge captions above subject", "status": "queued"}
  ]
}
```

## Demo acceptance test (must be observed, not merely asserted)

1. Import real footage, play a bounded section and confirm its endpoints and audio.
2. Pause at two distinct times; add two different notes; observe distinct accurate pins and ordered cards.
3. Replay the section; edit one note; remove and re-add another; refresh and confirm persistence.
4. Apply both remaining notes together; observe a single new version with lineage and a playable preview.
5. Confirm at least one requested edit materially changed the real exported MP4, and another note reports honestly if unsupported. Check sound and visual framing.
6. Refresh/reopen project and verify notes, pins and version history; restore the prior version.
7. Record demo URL, source and exported MP4 paths, test logs, screenshots, and unresolved limitations. Do not mark complete without real-video QA.

## Explicitly excluded from tonight

Autonomous full-film edits, multi-user collaboration, elaborate motion-graphics systems, new 3D effects, broad tool integrations, and a separate media engine. The milestone is **a user can play one real section, leave several revisions as they go, apply once and review a saved, playable edit**.
