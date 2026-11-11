# Frame MCP connector

The local bridge is `work/frame-product/quick_mcp.py`. It connects to a loopback Frame editor (`FRAME_URL`, default `http://127.0.0.1:8876`) and can start that editor when necessary. It adds standard FFmpeg installation directories to a desktop host's PATH without dropping existing entries.

Run `sh work/frame-product/start-local.sh` to start the local service. The current fallback UI is `/frame`; `/quick` is the older editor. Configure the host's stdio MCP command with the Python environment containing the editor dependencies and the absolute path to `quick_mcp.py`. No credentials belong in this repository.

## Host integration

`open_editor` returns an MCP App with project selection and bounded app-only video transport. Import tools return the editor for the exact imported project. Chat attachment import requires an actual host file handoff; the bridge cannot enumerate inaccessible attachments. `import_reference_video` always requires an explicit target from this conversation or its app context and preserves the main edit.

Save references and source-anchored notes, then use **Send implementation prompt to chat**. Submission, receipt and completed implementation are separate states. Ambiguous sends are not retried automatically. Older host registries can use the browser journal and definitive unsupported-method fallback; that path does not claim a server-recorded receipt. Standalone browser mode retains a manual copy path when no chat bridge exists.

A completed result is recorded only after a matching current full export has been validated. History and original footage are preserved. Saving a note or receiving a message never proves a video edit.

## Separate hosted implementation

The owner-tested cloud implementation opens beside ChatGPT Work and uses private cloud storage and an OpenAI-hosted render sandbox. It is a separate source/deployment, not the localhost connector and not a shell command that installs into ChatGPT web. Exact checkpoint versions and tested limits are recorded in [CHECKPOINT_2026-11-03.md](CHECKPOINT_2026-11-03.md).

Earlier local Secure MCP Tunnel experiments required a running Mac and a private per-user tunnel key. No tunnel key, host configuration, private project, user video or browser profile is included here. Public distribution, other-account onboarding and directory listing must not be inferred from owner-account tests.

## Verification

From `work/frame-product`, run `python -m unittest discover -s tests -p 'test_*.py' -v` and `npm ci && npm test`. Build the paired UI with `npm ci --prefix widget && npm run build --prefix widget`. FFmpeg/FFprobe and Python Pillow, requests, numpy and msgpack are required for the offline/real-media verification suites. Motion rendering retains preferred desktop fonts, with installed DejaVu fonts as the Linux fallback; Linux CI installs `fonts-dejavu-core`. `FRAME_FONT_DIR` can select the preferred font directory. Tests use temporary or synthetic projects; they do not authorize paid providers or private account access.

The extra native Codex panel action remains a known host-routing failure despite the request reaching `open_in_codex`. The current Control+Option+Shift+O binding is not an accepted panel-opening feature.
