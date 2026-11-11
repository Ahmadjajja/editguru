# Conversation-first FRAME

Attach footage to the conversation in a host where FRAME MCP is enabled. The assistant calls FRAME's import tool and opens the returned `editor_url`. The editor receives the original bytes through its existing upload pipeline. The user does not have to select the same file again in FRAME.

Implemented locally on November 2, 2026:

- `import_video` accepts the host attachment object: `download_url`, `file_id`, optional `mime_type` and `file_name`. Its descriptor uses `_meta["openai/fileParams"] = ["file"]`, following the [official file handoff contract](https://developers.openai.com/plugins/reference#file-apis).
- `import_local_video` accepts an absolute path supplied by a local conversation host. It supports hosts which expose attachments on the user's laptop instead of issuing download URLs.
- MCP initialization instructions and tool descriptions tell the assistant to import attached footage and open the editor link without asking for a duplicate upload.
- The result includes `project_id`, `editor_url`, and import status in both text and MCP `structuredContent`. Links include `compact=1` and open the exact imported project.
- Compact mode fits video and controls to the available pane height while preserving the source aspect ratio. Import UI is hidden in that mode; Command O remains available as a manual fallback. Instructions and pacing presets can expand below the video.
- **Fit window** requests a compact browser popup sized for the footage. Popup policy and outer window sizing remain controlled by the browser. The current browser's window is never forcibly resized.

## Local installation

The Codex MCP server named `frame` is registered and enabled on this laptop using:

```sh
codex mcp add frame -- \
  /Users/dantegarcia/frame-creative-agent/work/frame-product/.venv/bin/python \
  /Users/dantegarcia/frame-creative-agent/work/frame-product/quick_mcp.py
```

Start the editor with `sh work/frame-product/restart-local.sh` if needed. Newly started MCP clients discover 16 tools, including asset positioning and source-frame comments; see [ASSET_UI.md](ASSET_UI.md). Existing chats may need their MCP connection reloaded before new tools appear. Registration does not alter tools already loaded into this running chat.

Other clients supporting local stdio MCP can launch the same Python script. The authenticated loopback Streamable HTTP endpoint also serves the current tools at `http://127.0.0.1:8877/mcp`; retain the existing private bearer token. No tunnel, external server or public deployment was created.

## What is and is not verified

**Verified:** 66 Python checks, including schema completeness, public-address validation, pinned-IP TLS hostname verification, bounded streams, redirects, truncation, signed-URL error redaction, and existing render regressions. Live stdio discovery/real-file import/trim/split/undo/FFmpeg export pass. The attached-file tool was tested with real recorded video bytes delivered through a local fixture transport simulating a host-issued URL. The downloaded and imported originals are byte-identical. Real compact-browser preview and full exported MP4 playback pass. Authenticated HTTP discovery returns 13 tools; unauthenticated access returns 401.

At 360 × 800 and 900 × 800 viewports, portrait and landscape video keep their exact source ratios, all editing controls sit below the video, the compact controls fit vertically, and no horizontal overflow occurs. The popup-request URL/features are tested with `window.open` intercepted; actual native popup sizing was not tested.

**Not verified:** a live ChatGPT account handing off an uploaded MP4, automatic model tool choice on upload, ChatGPT widget embedding, or arbitrary host compatibility. An MCP server cannot subscribe itself to every conversation's attachment events. FRAME must be connected/enabled in each host; the host must supply attachments and invoke its tool. Initialization guidance makes the intended behavior explicit, but does not create a global upload event hook or prove autonomous tool selection. Ordinary loopback editor links must be opened on the laptop running FRAME.

## Repeat the local acceptance

Run the editor first. From the repository root, using recorded footage at least eight seconds long:

```sh
FRAME_FOOTAGE=/absolute/path/to/footage.mp4 \
work/frame-product/.venv/bin/python work/frame-product/tests/chat_import_e2e.py

PYTHONPATH=work/frame-product work/frame-product/.venv/bin/python \
  -m unittest discover -s work/frame-product/tests -v
```

The live test imports disposable projects into the running local editor and exports a five-second edit. It deliberately simulates the remote host transport; production HTTPS validation is not disabled. Evidence remains under ignored `output/playwright/`: `chat-first-mcp-results.json`, `compact-results.json`, `compact-portrait.png`, `compact-landscape.png`, `mcp-import-http.json`, and `mcp-import-tests.log`.
