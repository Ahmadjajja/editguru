> **Current checkpoint (November 3):** local Frame MCP App with timeline editing, persistent video references, source-frame markup, revision history, same-chat implementation handoffs and verified exports. See [the checkpoint and limits](docs/CHECKPOINT_2026-11-03.md) and [connector setup](docs/MCP_CONNECTOR.md). The current branch is `feat/pins-claude-mvp-2026-11-02`; the sections below retain earlier implementation history.

> **Current canvas + start/end pins:** [interaction and launch instructions](docs/CANVAS_RANGES.md). Refresh the editor to load the updated canvas.

> **Pins + Claude MVP:** launch `sh work/frame-product/restart-local.sh` and open http://127.0.0.1:8876/quick. See [the MVP instructions and verification contract](docs/PINS_CLAUDE_MVP.md). Active branch: `feat/pins-claude-mvp-2026-11-02`.

> **November 2 local editing sprint:** working manual browser editor on `feat/local-ship-sprint-2026-11-02`. Start with [docs/HANDOFF.md](docs/HANDOFF.md). Run `sh work/frame-product/restart-local.sh`, then open http://127.0.0.1:8876/quick. This is a standalone local editor; ChatGPT connector setup remains separate. Older native/generative notes below are historical scope.

# FRAME engineering workspace

> **Historical baseline:** draft PR #1 and the native iPhone architecture below predate the current local Frame editor. Do not switch a shared checkout based on this historical section. Inspect the current branch, checkpoint document and CI before continuing work.

FRAME is a native iPhone creative editing application backed by a tool-using media service. This workspace contains the independent implementation and verification work while the existing Replit prototype is inspected and improved.

## Current work

- `work/frame-core`: media service and real FFmpeg checkpoint rendering.
- `work/frame-ios`: native SwiftUI client.
- `work/frame-qa`: independent real-video validation.
- `docs`: product contract, architecture decisions, task ledger, and QA evidence.
- `work/frame-taste`: evidence-backed creative review rubric drawn from the founder's stated preferences.

The continuing build and review procedure is in `docs/ENGINEERING_LOOP.md`.

No milestone is considered complete until the media output is playable and independently checked.
