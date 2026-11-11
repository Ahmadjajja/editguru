# Testing FRAME as a user: guide for ChatGPT / Codex

Updated 2026-11-10 · branch `feat/style-swarm-2026-11-09` · repo `~/frame-creative-agent` on Dante's Mac.

Goal: prove FRAME works end to end as a professional AI video editor, and document every bug, usability problem
and missing feature. **Document, do not fix.** No source edits, no commits, no pushes during testing.

---

## 0. Ground rules (protect the approved work)

| Never | Why |
| --- | --- |
| Open, edit, render or send live-channel commands to project `8ba3cd4acef0484dbb2a2d9a6927abe4` | It is Dante's approved Fable edit |
| Write inside `recipes/fable-52-higgsfield-mcp/`, `recipes/_styles/`, `recipes/chatgpt-mastery-9x16/` | Production kit, saved styles, recipe record |
| Save a style named "Higgsfield v3 Discovery" | Use names starting `codex-` (FRAME refuses to overwrite an existing style anyway) |
| Edit, commit, stash, reset or checkout anything in the repo; `npm install` inside the repo | Dante has unrelated uncommitted work in this tree |
| Run `git clean`, delete `jobs/*` folders you did not create | Other projects live there |

Everything you create goes in **new projects** (you upload copies) and in `~/frame-test-runs/` (outside the repo).
Tell Dante to close any FRAME tab showing the Fable project while you test.

Guard: snapshot before, verify after. A FAIL at the end is itself a finding to report.

```sh
cd ~/frame-creative-agent
python3 work/frame-product/tests/frame_test_guard.py snapshot
# … all testing …
python3 work/frame-product/tests/frame_test_guard.py verify
```

---

## 1. Install and start

Prerequisites on the Mac (already present on Dante's machine): Python 3.9+, FFmpeg + ffprobe, Node 18+.

```sh
cd ~/frame-creative-agent/work/frame-product
# FRAME's own environment (start-local.sh creates it on first run if missing)
ls .venv/bin/python || python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt          # Pillow, numpy, faster-whisper, …
.venv/bin/python -m pip install opencv-python-headless scipy   # the v3 renderer (FRAME also installs these on first render)
```

Start (or restart) the app on port 8890:

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8890/api/v3/kits   # 200 = already running
PORT=8890 sh ~/frame-creative-agent/work/frame-product/restart-local.sh       # macOS (launchd); log: ~/.local/state/frame-quick-edit/editor.log
# any OS / foreground:  cd work/frame-product && PORT=8890 .venv/bin/python app.py
```

Browser automation tools, installed OUTSIDE the repo:

```sh
mkdir -p ~/frame-test-runs/tools && cd ~/frame-test-runs/tools
npm init -y >/dev/null && npm i playwright@1.48.2 && npx playwright install chromium
export NODE_PATH=~/frame-test-runs/tools/node_modules
```

---

## 2. Automated tests (engine, no footage needed)

```sh
cd ~/frame-creative-agent/work/frame-product
.venv/bin/python -m unittest tests.test_v3 -v
```

Nine tests: plan anchoring and determinism, A-roll gap refusal, overlapping sections, kit comments kept out of
the renderer, overlay validation, screen-recording time map, live channel, style → first cut, render smoke
(1080×1920, exact frame count). They use synthetic footage, so passing them proves the engine, not the product.

---

## 3. Test data (all read-only sources; uploading makes copies)

| Use | File |
| --- | --- |
| Talking-head A-roll (41.6 s, HEVC 1080×1920) | `work/frame-product/jobs/8ba3cd4acef0484dbb2a2d9a6927abe4/input.mp4` |
| Corrected transcript of that A-roll (fallback if Whisper fails) | `…/8ba3cd4acef0484dbb2a2d9a6927abe4/transcript.json` |
| B-roll clips | `recipes/fable-52-higgsfield-mcp/media-kit/{commercial-velorix-watch,cinematic-desert-run,hypermotion-05-headphones,ugc-mug,commercial-track-bike}.mp4` |
| Setup screen recording (9:16) | `recipes/fable-52-higgsfield-mcp/media-kit/claude-setup-mobile-fable.mp4` |
| Approved render to compare against | `…/8ba3cd4acef0484dbb2a2d9a6927abe4/versions/272c3c7406c14d759a5ee5d56b8ce284/edited.mp4` |
| Saved style | "Higgsfield v3 Discovery" (`recipes/_styles/higgsfield-v3-discovery.json`) |

Also try your own footage (any talking-head clip with a "here's how", a "free…" and a "comment X" line) to see how
the style generalizes.

---

## 4. The user journey (do it in the browser like Dante would; API equivalents for setup and checks)

Editor: `http://127.0.0.1:8890/swarm?project=<id>#pro` (Pro view shows the timeline). `window.frameEditor` is the
editor instance for inspection (`.p.clips`, `.v3Timeline()`, `.v3SegOut(clip)`, `._v3boxes`, `.frame`).

| Step | In the UI | API / check |
| --- | --- | --- |
| Create a test project | Open `http://127.0.0.1:8890/swarm`, Upload footage | `curl -s -X POST --data-binary @input.mp4 -H 'X-Filename: codex-test.mp4' http://127.0.0.1:8890/upload` → `id` |
| Transcribe | Transcribe button (if shown) | `POST /api/style/projects/<id>/transcribe`, poll `GET /api/style/projects/<id>/words` until `words` is non-empty. Fallback: `POST /api/style/projects/<id>/words` with `{"words":[{"w":"Claude","s":1.02,"e":1.35},…]}` built from the corrected transcript |
| Import B-roll + screen recording | "Import B-roll clips" under the preview (multi-select) | `POST /api/quick/projects/<id>/assets` (`X-Filename` header) |
| Apply the saved style | **First cut from a style…** → style "Higgsfield v3 Discovery" → mark the screen recording "Setup screen recording" → **Make first cut live** | `POST /api/v3/projects/<id>/first-cut` `{"style":"higgsfield-v3-discovery","assets":[{"asset_id":"…","role":"split"\|"screen","label":"","cue":""}]}` |
| Watch the agents | Agent cursors cut the take, place sections, captions (TEXT lane) and overlays (GRAPHICS lane); the preview shows each as it lands | `frameEditor.swarm` is null when done; activity log says "Build finished" |
| Edit by hand | see §5 | every edit is in `frameEditor.p.clips` and autosaves (status "Saved · vN") |
| Render | **Render** (top right) or **Render v3** | `POST /api/v3/projects/<id>/render` `{"kit":…,"overrides":…,"timeline":frameEditor.v3Timeline()}` → poll `GET …/render/<key>`; QC in `qc` |
| Download | **Download v3 cut** | file at `jobs/<id>/versions/<export id>/edited.mp4` + `qc.json` + `v3-plan.json` |
| Reuse | **Save as style** with a `codex-` name; make another project and apply it | `GET /api/v3/styles` |

Also test the older built-in path once (Build v3 with the Fable kit selected instead of a style) and compare.

---

## 5. Feature checklist (each is a pass/fail row in your report)

| ID | Feature | How to test | Pass when |
| --- | --- | --- | --- |
| F1 | Project from upload | Upload a copy of the A-roll | Editor opens it, duration correct, waveform/preview plays |
| F2 | Transcription | Transcribe | Words appear; note accuracy (proper nouns like "Claude Fable 5.2", "Higgsfield") |
| F3 | B-roll import | Import 6 clips | All listed, saved to project (survive reload), playable in preview |
| F4 | Style first cut | First cut from "Higgsfield v3 Discovery" | Sections land on sensible words; screen recording on "here's how"; offer on "free/unlimited"; CTA keyword from "comment X"; caption height and overlay positions match the style |
| F5 | Live agent build | Watch the build at Speed: watch | Every cut, section, caption, overlay appears in the preview as placed; Pause/Resume/Stop work; you can edit during the build |
| F6 | Caption editing | Click a caption in the preview; drag it; retype it; toggle a lime word; size slider; Reset position; "Use this height for all"; Delete; Add caption at playhead | Each change shows immediately, survives reload, and appears in the render |
| F7 | Overlay (GRAPHICS) editing | Move a step label, the CTA panel, a split label; resize; edit CTA keyword and offer lines (use " / " between lines); delete a corner note; Add text overlay | Same as F6 |
| F8 | B-roll replacement | Select a split section → swap its clip; change "Clip starts at"; Add an imported clip at the playhead | Preview plays the new clip from the new start; render matches |
| F9 | Timeline trimming | Drag both edges of a split, a screen section, a caption, an overlay, an A-roll piece; move clips; razor split; undo/redo | Trims behave as an editor expects (A-roll trims ripple later clips); render matches; no desync |
| F10 | Live channel | Append to `jobs/<test id>/live.jsonl` while the test project is open: `python3 work/frame-product/quick_v3.py --live work/frame-product/jobs/<test id> '{"type":"say","text":"hello from Codex"}'`, then `{"type":"seek","t":12,"play":true}`, `{"type":"build"}`, `{"type":"render"}` (or `POST /api/v3/projects/<test id>/live`) | Each appears in the open editor within ~2 s with the expected effect |
| F11 | Final MP4 | Render and download | 1080×1920, 30 fps, AAC audio, duration = timeline + 1.15 s hold, about −14 LUFS (`qc.json`), voice clearly over music |
| F12 | Preview = render | §6 | No visual or timing mismatches beyond the stated tolerance |
| F13 | Persistence | Reload the browser and restart FRAME mid-edit | Nothing lost; version counter increases |
| F14 | Save and reuse a style | Save as style `codex-…`; apply to a second project | Second first cut reflects the saved choices |
| F15 | Error handling | Render with a gap on the A-roll (Ripple off, delete a piece); upload a non-video; first cut with no clips | Clear message, no crash, nothing corrupted |
| F16 | Professional-editor gaps | Keyboard shortcuts, zoom, snapping, audio levels, waveform, safe areas, aspect ratios, export settings, multi-select, copy/paste, J/K/L, markers | List what a professional editor would expect and is missing or awkward |

---

## 6. Preview vs render comparison

After rendering the test project:

```sh
export NODE_PATH=~/frame-test-runs/tools/node_modules
cd ~/frame-creative-agent
node work/frame-product/tests/v3_preview_capture.cjs --project <test id> --out ~/frame-test-runs/compare-1
work/frame-product/.venv/bin/python work/frame-product/tests/v3_compare.py --capture ~/frame-test-runs/compare-1 \
  --render work/frame-product/jobs/<test id>/versions/<export id>/edited.mp4
```

The capture script opens the editor read-only (autosave disabled), seeks to the middle of every section and
overlay and every 5th caption, waits for the videos to settle and saves the preview canvas plus what is on
screen. The compare script finds the best-matching render frame within ±0.3 s and writes `compare.md`,
`compare.json` and `side_<t>.png` (preview | render | difference ×4). It flags a visual mismatch above a mean
difference of 18 and a timing mismatch when the best frame is more than one frame away. Inspect every flagged
side-by-side image and describe what differs (position, size, text, colour, timing). Re-run after edits from §5
to confirm that edits reach the render.

It refuses the approved project unless `--allow-approved` is passed (read-only, but do not).

---

## 7. Report

Write `~/frame-test-runs/FRAME_TEST_REPORT.md`:

1. Summary: does FRAME work end to end? one paragraph, then counts of pass / fail / blocked.
2. Environment: macOS version, Python, FFmpeg, browser, FRAME commit (`git rev-parse --short HEAD`).
3. Results table: one row per checklist ID (F1–F16) and per automated test: Pass / Fail / Blocked, evidence (file, screenshot).
4. Findings, one block each:
   - ID, title, area (engine / editor UI / render / style / docs)
   - Severity: **S1 blocker** (cannot finish an edit or wrong output), **S2 major** (wrong or lost work, a workaround exists),
     **S3 minor** (annoying, cosmetic, inconsistent), **S4 suggestion** (missing feature, polish)
   - Steps to reproduce (numbered, from a fresh test project), expected, actual, evidence
   - Recommended fix (what and where), without implementing it
5. Preview-vs-render results: the compare table + your reading of each flagged row.
6. Missing features for a professional AI video editor, ranked.
7. Guard result (`frame_test_guard.py verify` output). Confirm nothing in the approved project or production
   assets changed and nothing was committed or pushed.

---

## 8. Reference: HTTP API

| Purpose | Call |
| --- | --- |
| Projects list | `GET /api/projects` |
| Upload footage → project | `POST /upload` (raw body, `X-Filename`) |
| Project document | `GET /api/quick/projects/<id>` |
| Words / transcribe / store words | `GET` · `POST …/transcribe` · `POST …/words` under `/api/style/projects/<id>/` |
| Add an asset | `POST /api/quick/projects/<id>/assets` (raw body, `X-Filename`) → `uploaded_asset_id` |
| Kits for a project | `GET /api/v3/kits?project=<id>` |
| Plan (no side effects) | `POST /api/v3/projects/<id>/plan` `{"kit","overrides"}` |
| Styles | `GET /api/v3/styles` · `POST /api/v3/styles` `{"project","name"}` (refuses an existing name) |
| First cut | `POST /api/v3/projects/<id>/first-cut` `{"style","assets":[{asset_id,role,label,cue}]}` |
| Render | `POST /api/v3/projects/<id>/render` `{"kit","overrides","timeline"}` → `GET …/render/<key>` |
| Live channel | `POST /api/v3/projects/<id>/live` · `GET …/live?after=N` · types `say`, `build`, `patch`, `seek`, `render` |
| Media | `/media/<id>/input.mp4`, `/media/<id>/versions/<export>/edited.mp4`, `/api/v3/kits/<kit>/media?media=…` |

`timeline` = `{lines:[{src_in,src_out,out}], segments:[…], captions:[{t0,t1,tokens,y?,x?,k?}], caption_y,
graphics_mode, graphics:[{type,t0,t1,x?,y?,k?,…}]}` — exactly `frameEditor.v3Timeline()`.

## 9. Where things are

`quick_v3.py` (engine + API) · `swarm/frame-bridge.js` (editor features) · `swarm/index.html` (editor shell) ·
`tests/test_v3.py`, `tests/frame_test_guard.py`, `tests/v3_preview_capture.cjs`, `tests/v3_compare.py` ·
build log for context: https://claude.ai/artifact/XBj839qjEe4zcDATjBXNwe
