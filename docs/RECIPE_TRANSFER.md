# Reusable recipe slice — November 10, 2026

Implemented on `feat/style-swarm-2026-11-09`, baseline `ad5a8cc`. No commit, push, merge, shared-server restart or live-store migration performed.

## What transfers

`recipes/chatgpt-mastery-9x16/transfer.json` explicitly separates creator identity from video content. Fixed identity: portrait containment and white English captions. Variable inputs: the new source and audio, script/timed transcript, duration and current cuts. Evidence points to recipe steps 08, 09 and 14 and the V8 compositor. Position, size and grouping are declared adaptation settings, not historical measurements. No original story assets or advertiser identity are copied.

`quick_recipe_apply.py` freezes the template, source SHA-256, words, cuts, compiler and base version into a reviewed digest. Starting requires that exact digest. Two sequential operations apply framing and captions. Every operation saves its cursor, receipt and changed video state in the same atomic timeline write. No in-memory job is needed to restore progress. Version checks reject concurrent changes; explicit pause/resume reconciles them. Pending caption/framing operations preserve fields changed since the plan. Captions remap to current source cuts. Undo uses the existing timeline snapshots; run receipts remain historical after undo rather than claiming an undone step is still visible.

Final exports preserve the existing renderer and audio, save a provenance sidecar and expose it through `/api/recipe-apply/<project>/exports/<export>`. The record binds the frozen plan, step receipts and exact video state to the exported MP4 checksum. Existing exports with no recipe run are unaffected.

The existing Swarmcut save path no longer fetches a newer version and retries stale full state after HTTP 409. It stops agents/autosave, retains local unsaved state and blocks export until the user reloads. Automatic merging/recovery of conflicting unsaved edits is outside this slice.

## Demo

An isolated demo runs at http://127.0.0.1:8892/recipe-apply?project=1234567890abcdef1234567890abcdef . Its store is under this chat's `outputs/Recipe-Demo/projects`, separate from both existing services at 8876 and 8890. The agent-owned Chrome session was allocated through agent-session; no human window was used.

The demo project is synthetic test footage with an audible test tone. Its genuinely new script is “Save the rain. Plant a small garden. Let tomorrow grow.” A one-second trim while paused yields a five-second portrait export. It is technical acceptance media, not a finished garden video or generated narration.

To repeat on new footage in a runtime loading this checkout:

1. Open `/swarm` to upload footage or choose a project, then copy its project ID from the URL.
2. Open `/recipe-apply?project=<id>` (also linked as “Apply to new footage” from recipe replay).
3. Paste a new script, or leave it empty to use the project's saved timed transcript. Pasted words are evenly distributed across the source and explicitly marked estimated.
4. Review plan → Apply recipe → Pause. Steps are spaced 1.8 seconds apart for interruption.
5. Use “Edit while paused”: trim the beginning of the first source clip and/or enter a caption override. Save my edit → Resume with my edits.
6. Reload anytime, Restore saved run, then Resume. Restoring an unfinished running run pauses it first.
7. Export MP4 → Download MP4 / Export provenance.

Use the dedicated apply screen for editing/export in this slice. Swarmcut does not yet roundtrip transferred captions or exact caption placement, so opening the source editor after assembly is not a supported caption-edit workflow.

## Validation

- 2 recipe tests: real HTTP handler and FFmpeg export, deterministic/revised digests, stale-start rejection, idempotent step requests, pause rejection, manual trim/grade preservation, disk reload, new-caption remapping, no old assets, export checksum/provenance, full decode, picture pixel checks, audio and undo; separate concurrent-edit/caption-override case.
- 8 existing style tests passed.
- 6 existing studio tests passed.
- 21 existing quick timeline tests passed.
- New JavaScript regression passed: a 409 sends exactly one save, stops agents, retains old version/local state, schedules no retry and blocks export flush.
- Browser: review, apply, pause, trim, save, reload, restore, resume, export and download-link visibility verified in isolated agent Chrome.
- JavaScript syntax and `git diff --check` passed. These are focused checks, not a claim that the entire repository suite passed.

## Boundaries

This is layout/caption transfer, not the full manga production. No typing intro, ChatGPT screenshot, scene animation, generated artwork, narration, music, SFX, exact font or original compositor transfers. Output uses the existing 720×1280 portrait renderer; new footage retains its own aspect ratio in the inset. At most five minutes of source, 600 pasted words, 150 caption cues and 20 saved runs per project. Long scripts can hit the existing cue limit. No new dependencies were installed.

A pasted script is not forced alignment or TTS. A saved transcript is frozen at review; changes require a new plan. No background work continues after the page closes. Existing style mode's batched passes and preview/export gaps remain unchanged. Disk free space was about 5.5 GiB initially and 5.3 GiB after testing; no user files were deleted to make room.
