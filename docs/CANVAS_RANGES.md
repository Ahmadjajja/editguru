# Playable canvas with start/end pins

Current refinement of the November 2 local editor. Same launch command and persistent revision as the MVP:

```sh
sh /Users/dantegarcia/frame-creative-agent/work/frame-product/restart-local.sh
```

Open http://127.0.0.1:8876/quick and refresh any already-open editor page.

The main surface is a real canvas drawing decoded video frames, with audio supplied by its underlying media element. Native video controls are replaced by editor transport controls. Click the canvas at any point to pause on that frame. Space plays/pauses while the canvas has focus; arrow keys step frames, Shift+arrow steps ten. Scrubbing and focusing instruction or range fields also interrupt playback.

1. Seek to the beginning of a section and choose **Set start pin**.
2. Seek forward and choose **Set end pin**. Each range has two clickable boundary markers and one instruction. Numeric Start/End fields can adjust the boundaries.
3. Ask Claude for an edit between those pins, or drag the picture in the canvas to propose a position change.
4. Review **Edit proposal**, then **Approve & render**. The drag display is a labeled draft; the saved result is the actual FFmpeg-rendered MP4.

Positions apply only between the pins. The renderer splits the existing clip decisions around the interval and preserves the footage outside it. Source lineage keeps ranges associated with the footage after splits. Removing a range uses the existing clip-selection/rendering engine; trimming a range retains a smaller portion inside it while preserving footage outside the selection. Times snap to 30 fps. Each range must lie inside a fully retained section of one source lineage. Earlier single timestamp pins are retained as incomplete ranges; select one and set its end before asking Claude.

Canvas dragging never executes generated code or bypasses approval. It produces a validated `position_clip` proposal with exact range bounds. Both Claude and canvas proposals use the same render-before-commit transaction and stable revision. A request to edit a removed interval fails clearly until its bounds are adjusted. The source view shows original pixels; the rendered view shows the accepted edits. The canvas moves the video picture as a whole during the selected range; it does not turn objects baked into footage into separate layers.

The earlier [MVP report](PINS_CLAUDE_MVP.md) and its evidence describe the timestamp-pin checkpoint. This document supersedes its singleton-pin and whole-clip-only interaction descriptions. Current tests: `tests/test_quick_revision.py` and the updated `tests/revision_e2e.cjs`.

## Verified November 2

88 backend tests and 23 real browser checks passed, including actual canvas pixels, click-to-interrupt playback, three start/end ranges, a real Claude 2–4 second position proposal, full rendered playback, reload/restart persistence, unsupported-request protection, and a mouse drag followed by approval and a second actual MP4 render. Both accepted operations remain in the same revision after another backend restart. The canvas-edited MP4 was downloaded through the UI and fully decoded. Actual decoded frames at source seconds 1, 3 and 5 match the expected unchanged / 15% right / unchanged layout within compression error (mean absolute RGB error below 1). Compact 390px browser geometry has no horizontal overflow. Exact checks, IDs, output hash and frame measurements: [CANVAS_RANGES_EVIDENCE.json](CANVAS_RANGES_EVIDENCE.json).

A final paused-preview check exposed Chromium's black first-frame behavior with a `display:none` decoder video. The media element now stays in the layout at one unobtrusive pixel while the canvas provides the editing surface. Media load/seek/pause events also paint immediately. Four additional browser checks passed after that fix: paused source first frame after reload, paused rendered first frame without playback, live rendered click-to-pause, and frame-step pixel updates. Evidence: [CANVAS_PAUSED_FRAME_EVIDENCE.json](CANVAS_PAUSED_FRAME_EVIDENCE.json); screenshot `output/playwright/revision-mvp/canvas-paused.png`.
