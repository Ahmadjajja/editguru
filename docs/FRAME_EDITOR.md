# FRAME — frame-only video editor

Current local implementation on `feat/pins-claude-mvp-2026-11-02`. Incorporates the newest upstream implementation contract from `origin/main` commit `51e1104` (`SECTION_REVIEW_MVP.md`) and the user's subsequent corrections: monochrome, one timeline layer, pin-focused, no sidebar.

## Open and use

```sh
sh /Users/dantegarcia/frame-creative-agent/work/frame-product/restart-local.sh
```

Open http://127.0.0.1:8876/quick. Refresh an existing tab to load the latest UI. The default view is the playable frame and one timeline strip. Hover or focus the frame to reveal its small toolbar; mobile keeps it visible. There is no permanent editing sidebar.

- Space: play/pause. Click the canvas to interrupt playback. Arrows: one frame; Shift+arrow: ten frames.
- I/O, or Start/End: mark section boundaries. `[ ]` opens exact source-time controls.
- S / Split: split at the actual playhead. Cut removes the marked section; Keep keeps only that section. Command/Ctrl Z undoes; Shift+Command/Ctrl Z redoes.
- N / + Note: pause and leave a source-anchored explanation/revision. Without a selected range, a retained clip supplies the default section. Pins opens the ordered revision list in a temporary popover.
- Play section reviews only the marked section. Notes can be adjusted, removed and kept without losing their source anchors or history.
- Apply revisions freezes all included queued notes; Claude proposes supported operations and explains unsupported notes. Approve & render makes one real saved checkpoint. Conflicting notes fail visibly without silently overwriting one another.
- ↓ / Command/Ctrl E renders the saved manual timeline. The actual output replaces the canvas after success. The project menu `⋯` contains MP4 download, original/latest comparison, saved version restore, projects and file import.

Manual decisions persist immediately; raw source playback is labeled as original until an actual edited output is rendered. FFmpeg uses the existing single-encode engine and 30 fps rendering. Source section/note anchors retain millisecond precision; render boundaries snap to the output frame grid.

## Data storage and project backups

Every project has a stable directory at `work/frame-product/jobs/{project_id}`. Original `input.mp4` is never overwritten. `timeline.json` atomically stores stable revision ID, pins, source-time notes, operation history, frozen revision sets, checkpoints, asset references, current render, and save time. MP4 derivatives stay in `versions/{id}/edited.mp4`. Images, audio and other uploaded creative files remain byte-for-byte in `assets/{asset_id}/{original_filename}` with size and SHA-256 recorded in the project. They are preserved references; they are not secretly inserted as new timeline layers.

In `⋯`, use Add creative files to preserve images/audio/other files, Download for MP4s/assets, and Save .frameproj for a complete ZIP-format project backup. The bundle includes its `project.frameproj.json` manifest, source MP4, timeline, original project metadata, saved versions, notes and creative files. It is a custom FRAME backup, not an Adobe project format. Archive import UI is not implemented. Local saved projects reopen through the project menu and survive server restart. User uploads are not deleted by application restart or rollback.

## Connection to this chat

The enabled FRAME MCP connection's `get_project` returns source-anchored notes, pins, proposals, accepted edits, checkpoints, uploads and current render. Actual end-to-end readback was demonstrated: a note created in the frame at 3.500 seconds appeared through `mcp__frame__get_project` in this chat.

Automatic unsolicited chat messages are **not active in a plain local browser tab**. The frontend uses the real, feature-detected `window.openai.sendFollowUpMessage` API only when a host actually supplies it, and never reports a successful send when the bridge is absent. That adapter is not claimed live-tested. Local status instead says the saved edit is available through FRAME. Official host API reference: https://developers.openai.com/plugins/reference . No human-owned browser window was controlled, and no fake host bridge was used for acceptance.

## Evidence

102 backend tests passed. Real browser checks cover section playback with measured nonzero audio, ordered note anchors and editing, frozen supported/unsupported Claude plans, one approved render/checkpoint, source preservation, reload/restart, compare/restore, a single timeline, and narrow-screen layout. Subsequent checks verify the frame-only view, actual MCP readback, image/audio/file uploads, .frameproj download, and the traditional Split → Undo → Redo → Cut → Undo → Keep → Pin → Render → Play → Restart → Download flow.

The final manual output is a fully decoded four-second H.264/AAC MP4. The archive's CRCs, original source SHA, all uploaded asset SHAs and all three archived MP4 decodes pass. Decoded frames before/inside/after the earlier approved range edit match expected unchanged/right-shifted/unchanged pixels (mean RGB error < 1); source/output audio correlation is 0.99999. The fixture is real recorded application footage plus a generated 440Hz test tone, not a subjective speech-quality test.

Exact results and limitations: `FRAME_EDITOR_FINAL_EVIDENCE.json`. Local screenshots, MP4s, archive and raw incremental JSON: `output/playwright/section-review/`. An early restore-preview null reference, a detached toolbar lookup, a temporary-directory symlink check, and an export-status test synchronization issue were corrected and the affected flows verified again. Prior failure history remains in project memory.
