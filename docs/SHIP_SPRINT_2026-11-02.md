# Local Quick Edit delivery evidence

November 2, 2026. Built and tested on Dante's Mac. Branch: `feat/local-ship-sprint-2026-11-02`; base: `9cbee86`. `git rev-parse HEAD` identifies the delivered checkpoint. No public deployment or push was performed.

## Real browser journey

A safe generated 14-second H.264/AAC MP4 contains a moving test pattern and 660 Hz tone with known pauses at 5–6.5 and 9–10.5 seconds. It was imported through the file picker into the actual Chrome editor at localhost:8876, in the agent-owned Chrome profile/window. This tests real encoded media, not a talking-head speech-quality judgment.

13 browser assertions passed: MP4 decoding, playhead split, delete, undo, redo, trim, reorder, restoring original, combined scenario edits, scenario undo, playback skipping a removed pause, export completion, and a usable 430px layout with no horizontal overflow.

Scenario: **“Remove the dead air, cut the first three seconds, and tighten the pacing.”** Executed with the explicit combined preset. The persisted retained source ranges are:

| Source start | Source end | Duration |
|---:|---:|---:|
| 3.000000 | 5.200000 | 2.200000 |
| 6.300000 | 9.166667 | 2.866667 |
| 10.333333 | 14.000000 | 3.666667 |

Total: **8.733333s**, versus original 14.000000s. Undo restored the full 14-second original; redo restored the edit. Playback at edited time 1.8s advanced across the first removed pause into source time ≥6.5s without rendering.

Export contains **262 H.264 frames**, AAC audio, and both streams start at **0.000000s** and last **8.733333s**. Decoded audio sample length equals the expected concatenated source sample length (0 ms difference); relative 10ms audio-envelope error is 0.003202. Sampled exported frames from each retained section match expected source moments (mean pixel difference below 0.425 on a 0–255 scale after resize). The exported MP4 advanced and played all the way to its end in this Mac's Chrome, with no media error.

## Independent review and regression

An independent agent required by the repository engineering loop reviewed the code and exercised backend operations. It found cumulative export padding in the original per-part renderer: 48 × 0.04s segments produced 3.2s from a 1.92s timeline. That failure was preserved as a finding and fixed by persisted frame alignment plus one encode. Independent retest of 48 cuts: **1.600000s timeline, 48 video frames, 1.600000s video/audio**, both starting at zero. Regression tests cover this failure and reordered video without audio.

Review also prompted fixes for hidden-tab audio, empty timelines displaying old frames, stale refreshes changing the selected project, export-directory failures, and cross-segment opening cuts. Final regression: **54 product tests and five gateway tests passed**, including 18 focused timeline/UI tests (two render actual FFmpeg media). Python/JavaScript syntax and whitespace checks pass. The original 3 quick-page contract tests remain green; the old page is preserved at `/quick/proposals`.

MCP tests: actual SDK Streamable HTTP initialization, discovery of 11 tools, authenticated `get_timeline`, and unauthenticated request denied with 401. Independent stdio discovery and live `list_projects` passed. MCP `split_clip` changed the live browser timeline from three to four clips; MCP `undo` restored three clips and the exact duration. A stale tool mutation was rejected. The saved timeline and completed export survived service restart. Direct ChatGPT account integration remains unverified.

## Evidence on this Mac

Not committed: local test media and browser evidence are excluded by `.gitignore`.

- `/Users/dantegarcia/frame-creative-agent/output/ship-sprint/safe-test.mp4`
- `output/ship-sprint/browser-results.json`, `scenario-timeline.json`, `scenario-export.mp4`
- `output/ship-sprint/av-results.json`, `export-playback.json`, `mcp-results.json`, `tool-ui-results.json`
- `output/ship-sprint/narrow-editor.png`

## Limits

- Browser fallback beside ChatGPT; no connected ChatGPT account or native ChatGPT viewer control.
- Source should be browser-decodable H.264/AAC MP4. Maximum import: five minutes / 700 MB; maximum timeline: 48 segments. Edits snap to 30 fps. Other codecs, HDR and very large footage were not validated.
- Browser preview seeks at cut boundaries and can briefly pause on a seek; export is the authoritative frame-aligned result.
- Pause detection uses low audio energy with padding, not semantic speech understanding. Audition cuts before using on speech.
- No physical speaker/listening verdict; synchronization checks are objective media/clock measurements.
- Existing AI proposal/generation workflows are retained, but not part of this manual-editor acceptance.
