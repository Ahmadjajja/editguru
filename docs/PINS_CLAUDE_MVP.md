# November 2 local pins + Claude MVP

Branch: `feat/pins-claude-mvp-2026-11-02`, built on `feat/local-ship-sprint-2026-11-02` / `39a6d9d`. The priority quick-edit branch (`9cbee86`) is its ancestor; the product-pilot branch (`75f78b5`) supplied the older media/proposal infrastructure. Reused the existing upload, loopback media byte-range server, project folders, timeline store, operation validation, render semaphore and single-encode FFmpeg renderer. No main merge, deployment or engine replacement.

## Launch

```sh
sh /Users/dantegarcia/frame-creative-agent/work/frame-product/restart-local.sh
```

Open http://127.0.0.1:8876/quick. Foreground alternative: `sh /Users/dantegarcia/frame-creative-agent/work/frame-product/start-local.sh`. Requires FFmpeg/ffprobe, the existing Python environment, and Claude Code signed in (`claude auth status`). Claude uses that account's model access; no API key is required by this implementation.

Import MP4 → play/seek → Add pin here → write instruction → Ask Claude → inspect the explicit JSON operation → Approve & render → Play rendered result → Save revision → Download final MP4. Each pin and saved instruction is automatically persisted. The Save revision button forces another atomic disk save; no additional project/revision is created. The original manual timeline remains at `/quick/timeline`; the old Codex proposal interface remains at `/quick/proposals`.

## Durable revision contract

`work/frame-product/jobs/{project_id}/timeline.json` is authoritative: stable `project_id`, stable `revision_id`, `source_reference`, source duration/audio, clips, pins with original-source times/clip IDs/instructions, proposals, accepted operations and their approval timestamps, current rendered MP4 reference and corresponding clip snapshot, incrementing version, and `saved_at`. No new project or revision is created by pin edits, proposals, approvals, or saves. Existing timelines migrate by adding fields without replacing clips or historical exports.

Every save uses a flushed/fsynced temporary JSON file, atomic rename, and directory fsync under the existing process lock. Approval first renders to a unique artifact folder using `editor.render_timeline`, completely decodes the MP4, fsyncs it, then commits clips, accepted operation and rendered reference together in a single JSON replace. Render, decode, stale-version or restart failures preserve the previous accepted clips/output. Interrupted proposals/renders recover as failed, with an explicit retry explanation. Pin edits during a render cause its commit to fail rather than overwrite newer changes. A failed candidate artifact can remain on disk but is never promoted as the current render.

## Claude boundary and current limits

Claude Code runs with no executable tools, no MCP servers, no project settings, no user hooks, no repository discovery via its temporary working directory, and no saved Claude conversation. A JSON schema limits the response to a supported operation. The server independently validates the operation and numeric arguments before approval and again before rendering. No generated code is loaded, evaluated or executed.

Supported: `trim_clip` using exact source start/end within the pinned clip; `position_clip` moving the whole clip with normalized x/y offsets bounded to 50% of the canvas. Trim uses existing 30 fps quantization. Unsupported or ambiguous requests produce a clear error and do not change accepted edits or output. There is no semantic speech analysis, object manipulation, caption generation or automatic code installation in this flow.

Pins are anchored to original source seconds. Original playback shows the entire original file; rendered playback shows the actual saved output and maps pins onto retained intervals. Pins cut out of a render remain editable in the source view. Position moves affect the whole selected clip, with black exposed canvas; a pin does not define an effect duration. Browser reload returns to source view, with the rendered result available through its button. Native ChatGPT/Atlas integration and arbitrary codec support are outside this milestone. One backend process must own this local storage; the lock is not multiprocess.

## Reproduce verification

```sh
cd /Users/dantegarcia/frame-creative-agent
PYTHONPATH=work/frame-product work/frame-product/.venv/bin/python \
  -m unittest discover -s work/frame-product/tests -v
PLAYWRIGHT_MODULE=/absolute/path/to/playwright-core \
FRAME_FOOTAGE=/absolute/path/to/real-footage.mp4 \
  node work/frame-product/tests/revision_e2e.cjs
```

The browser harness requires the Codex session ID and uses only the agent-owned Chrome session, checking the supervisor input lease immediately before input. It makes real Claude requests, renders with actual FFmpeg, restarts the local backend and downloads/fully decodes the final MP4. It writes incremental evidence, screenshots, a downloaded MP4 and ffprobe data under `output/playwright/revision-mvp/`. It fails closed on browser ownership or guard errors. Provider-free backend tests separately cover rollback, conflicts, approval, pin mutation, legacy migration and interrupted recovery. Browser evidence is not a claim of subjective creative or audio quality.

## Demonstrated result — November 2

Implementation `9a78194b87d3752d6cbee44128722615f55bee3d`: all 83 Python tests and all 18 real-browser checks passed. Actual recorded H.264 source: 25.266667 seconds, without audio. Claude proposed keeping original source seconds 1–8; explicit approval produced a 7-second H.264 MP4. Chrome played the complete output. Browser reload and a launchd backend restart preserved the same project/revision, three pins, saved instruction, accepted operation and rendered output. The final MP4 was downloaded by clicking the UI link, inspected by ffprobe and fully decoded by FFmpeg with exit 0. A second real Claude request for an unsupported object/generative effect returned a visible error while preserving the accepted output. Pin editing/deletion and a 390px view without horizontal overflow also passed.

Exact IDs, stream metadata, output SHA-256 and the passed checks are in [PINS_CLAUDE_MVP_EVIDENCE.json](PINS_CLAUDE_MVP_EVIDENCE.json). Raw incremental evidence, screenshots and final.mp4 remain in the local output directory named there. Browser acceptance does not certify subjective audio quality; the separate real FFmpeg tests exercise A/V synchronization. Injected backend encoder/decode failures and stale edits test rollback without provider calls.

During testing, a supervisor guard timeout correctly blocked input; a valid lease was acquired before retrying. The first browser pass exposed a restart clock display lag; the immediate clock update was fixed and the complete acceptance sequence rerun successfully twice.
