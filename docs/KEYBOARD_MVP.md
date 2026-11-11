# FRAME keyboard Quick Edit MVP

The shortest implementation path was to retain the existing local manual timeline, original-source browser preview, persistence, and single-encode FFmpeg export from `15e46a1`. This change adds keyboard navigation and editing in `timeline.html`; it does not change the engine. The current layout places all controls and shortcut instructions beneath the video. The workspace automatically uses a slim width for portrait footage and a wide width for landscape footage, based on the video metadata. Existing pacing presets are collapsed to keep the primary controls visible.

Open http://127.0.0.1:8876/quick. If stopped:

```sh
sh /Users/dantegarcia/frame-creative-agent/work/frame-product/restart-local.sh
```

| Shortcut | Action |
| --- | --- |
| Command O | Import footage |
| Space / L / K | Toggle playback / play / pause |
| Left / Right | Step one 30 fps timeline frame; Shift steps ten |
| J | Back one second |
| Home / End | Start / end (Fn Left / Right on compact Mac keyboards) |
| [ / ] | Previous / next clip |
| S | Split at playhead; automatically selects the clip there |
| I / O | Trim selected clip's in / out to playhead |
| Delete / Backspace | Delete selected clip |
| Option Left / Right | Move selected clip earlier / later |
| Command Z / Shift Command Z | Undo / redo |
| Command E | Export the saved timeline to MP4 |
| Enter / Escape in trim fields | Apply values / return to shortcuts |

Control substitutes for Command. Text fields keep their normal editing shortcuts. Import and initial page load focus the editor automatically. Held arrow keys keep stepping; destructive keys ignore auto-repeat. Trim-in preserves the source frame under the playhead. Exports save locally; the resulting download link is reachable with Tab.

## Acceptance on Dante's Mac, November 2, 2026

Actual footage: the existing recorded screen video `Desktop/frame-launch-video/V3/source-conversions/public-create.mp4` (25.266667 seconds, H.264, no audio). This is recorded application footage, not the earlier synthetic test pattern. A dedicated agent-owned Chrome session was allocated; the supervisor input guard ran before every keyboard action and navigation.

The automated browser journey opens the import picker with Command O, imports the footage, steps one and ten frames, splits at two seconds, trims the second clip to source three seconds, undoes and redoes that edit, selects and deletes the first clip, trims out at source eight seconds, previews with L/K, and exports with Command E. No pointer input is used. The resulting five-second export plays all the way to its end in Chrome without a media error. The test also asserts import focus and trim-in playhead preservation: **14 browser assertions**.

FFprobe confirms H.264, 1440 × 1000, 30 fps, exactly 150 frames and 5.000000 seconds. Full FFmpeg decode passes. Three sampled frames match source seconds 3, 4, and 7 with mean pixel error below 0.126 on a 0–255 scale. Export SHA-256: `2bc453cd433eb35de20a7af920a5c0b35921eca53ac46da4ea368a7fe6a91d5d`.

The 54 existing Python product tests pass, including real FFmpeg regressions for cumulative padding across many short cuts and reordered video without audio. JavaScript syntax and Git whitespace checks pass. The acceptance footage has no audio; prior audio/video coverage and limitations are recorded in `SHIP_SPRINT_2026-11-02.md`.

Repeat from the repository root inside Codex, providing a local Playwright module and recorded footage at least eight seconds long:

```sh
FRAME_FOOTAGE=/absolute/path/to/footage.mp4 \
PLAYWRIGHT_MODULE=/absolute/path/to/node_modules/playwright-core \
node work/frame-product/tests/keyboard_e2e.cjs > output/playwright/keyboard-results.json
```

The test allocates the current chat's owned session using `CODEX_THREAD_ID`. It never attaches to a human browser. Local media and screenshots remain excluded from Git. Results: `output/playwright/keyboard-results.json`; screenshot: `output/playwright/keyboard-editor.png`. Machine media measurements are in `output/playwright/media-verification.json`.

Use FRAME alongside ChatGPT or Atlas. Embedding and native ChatGPT integration are unverified. Browser preview still seeks original media at edit boundaries and may briefly pause; the encoded export is the authoritative result. Edits use the existing 30 fps timeline.
