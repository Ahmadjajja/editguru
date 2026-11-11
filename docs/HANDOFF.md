> **Current product:** frame-only monochrome editor, one pin timeline, basic edits, saved revision sets and creative-file/project backup. Start with [FRAME_EDITOR.md](FRAME_EDITOR.md). Earlier sidebar layouts and scope statements below describe previous checkpoints.

> **Latest user correction:** use paired start/end pins and an interruptible playable canvas. See [CANVAS_RANGES.md](CANVAS_RANGES.md).

> **Current November 2 task:** pins + real Claude proposal/approval/render in one persistent revision. Start with [PINS_CLAUDE_MVP.md](PINS_CLAUDE_MVP.md). `/quick` now opens that MVP; the manual asset editor described below remains at `/quick/timeline`. Earlier scope restrictions below describe the previous sprint.

# FRAME local Quick Edit — November 2, 2026

The current authorized goal is a Mac browser editor beside ChatGPT: import MP4 → manual cuts → instant preview → correct MP4 export. No public deployment, paid models, effects, or generation work is required. Work is on `feat/local-ship-sprint-2026-11-02`, based on quick-edit branch `9cbee86`, in `/Users/dantegarcia/frame-creative-agent`. The separate `/Users/dantegarcia/code/frame-creative-agent` Git repository and its worktrees were preserved. PR #4 (`b0a3ae8`) provides the older browser pilot; the newer quick-edit branch already contains its later product/media infrastructure.

Run:

```sh
sh /Users/dantegarcia/frame-creative-agent/work/frame-product/restart-local.sh
```

Open **http://127.0.0.1:8876/quick**. This single loopback service serves both the frontend and media API. The restart wrapper runs it through macOS launchd (`com.dantegarcia.frame-quick-edit.local`) so it survives the launching terminal; logs are under `~/.local/state/frame-quick-edit`. Stop with `launchctl remove com.dantegarcia.frame-quick-edit.local`. It is not installed as a login item. `start-local.sh` is the foreground alternative (Ctrl+C stops that). If the sprint service is already listening, use that service; do not launch a second copy on the same port. A pre-existing service on port 8765 was left untouched.

The server needs FFmpeg/ffprobe and Python with Pillow, requests, and numpy. The launcher uses the existing `.venv` or creates a minimal one. Manual editing and pacing do not require Codex CLI, transcription, or a model account. Existing AI proposals remain at `/quick/proposals` and can require their original dependencies/authentication.

Keyboard-first refinement and fresh recorded-footage acceptance: [KEYBOARD_MVP.md](KEYBOARD_MVP.md).

Current canvas/asset UI, real movement and annotation capabilities: [ASSET_UI.md](ASSET_UI.md). Current MCP tool count: 16; earlier 11/13 counts below describe historical checkpoints.

## Implemented

- Original upload preserved; stable project and segment IDs.
- Scrollable timeline, playhead split, numeric source in/out trim, delete, move earlier/later, undo/redo.
- Persisted 30 fps edit decisions, monotonically increasing version; optimistic conflicts return HTTP 409.
- Browser previews seek original media through retained sections with audio/video together; hidden tabs pause. No encode is needed for preview.
- Cut first three seconds across splits; optional measured silence removal with padding. This is an explicit preset, not a natural-language model.
- Snapshot exports remain tied to their timeline version while edits continue. FFmpeg trims/concatenates before one encode to avoid cumulative AAC/frame padding.
- Controls below the preview at every width; slim portrait and wide landscape workspaces adapt automatically to video metadata; keyboard shortcuts.

Source: `work/frame-product/quick_timeline.py`, `timeline.html`, new `editor.render_timeline`, and small route hooks in `app.py`. Existing render/proposal/generative flows remain intact.

Conversation-first attachment import and compact-window behavior: [CHAT_FIRST_MCP.md](CHAT_FIRST_MCP.md). The current bridge exposes 13 tools; the 11-tool result below is historical verification before import tools were added.

## Tool bridge

Local API discovery: `GET /api/quick/tools`. Project/timeline: `GET /api/quick/projects/{project_id}` or `.../timeline`. Commands: `POST /api/quick/projects/{project_id}/commands` with `operation`, integer `expected_version`, and operation arguments. Times are original-source seconds; moves use zero-based positions. Read the timeline after a conflict. The browser polls for tool edits every 1.5 seconds and pauses before adopting them.

MCP stdio:

```sh
/Users/dantegarcia/frame-creative-agent/work/frame-product/.venv/bin/python \
  /Users/dantegarcia/frame-creative-agent/work/frame-product/quick_mcp.py
```

Authenticated Streamable HTTP:

```sh
sh /Users/dantegarcia/frame-creative-agent/work/frame-product/start-tools.sh
```

Endpoint **http://127.0.0.1:8877/mcp**. Token is generated with mode 0600 at `~/.local/share/frame/quick-mcp-token`; supply it privately as `Authorization: Bearer …`. Never put it in a URL or commit it. Both servers bind loopback only. The bridge exposes `list_projects`, `get_project`, `get_timeline`, `split_clip`, `trim_clip`, `delete_segment`, `move_segment`, `undo`, `redo`, `export_video`, and `tighten_pacing`. `FRAME_URL` can select another loopback editor port.

A real MCP SDK client passed initialization/discovery/read/authentication. ChatGPT itself was not connected or its native media viewer controlled. Official integration options require account/workspace setup and a secure tunnel or authenticated hosted endpoint. Nothing was published. Reference: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels and https://developers.openai.com/plugins/build/app-quickstart.

## Actual verification

See [SHIP_SPRINT_2026-11-02.md](SHIP_SPRINT_2026-11-02.md) for measurements, evidence and limitations. Regression command:

```sh
cd /Users/dantegarcia/frame-creative-agent
PYTHONPATH=work/frame-product work/frame-product/.venv/bin/python \
  -m unittest discover -s work/frame-product/tests -v
```

Do not claim native ChatGPT integration, subjective audio approval, arbitrary codec support, or creative-quality acceptance from these tests.
