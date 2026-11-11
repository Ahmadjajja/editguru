# FRAME canvas and simple timeline

The UI follows the canvas, small toolbar and contextual-comment pattern shown in [Anthropic's Claude Design reference](https://www.anthropic.com/news/claude-design-anthropic-labs), with FRAME's controls kept underneath the footage. The warm neutral canvas, restrained segmented controls and prompt composer replace the dense control panel. This is FRAME's local editor, not a Claude integration.

The user interaction is stated above the controls:

- **Mouse:** click a video asset to select it; drag it to move it. Select **Mark an area** to draw a box and describe a change to that area.
- **Keys:** Space watches/pauses; arrows find a moment; I/O set the selected clip's start/end; S splits; Delete removes; Command Z undoes; Command E exports.
- **Prompt:** commands like `move right 2%`, `move up 10px`, `center`, `split here`, `undo`, `redo` and `export` apply through existing timeline operations. Other requests are saved as frame comments for an assistant to inspect; they do not silently change the picture.

The timeline shows selectable video clips. Each has a few quick edits: move left/right/up/down by 1%, center, trim, split, remove, reorder and undo. Extra timestamp controls are under **More timeline controls**. The current imported movie is one flattened video asset, with per-clip positioning. Text, people and other objects baked into its pixels are not separate selectable layers. No arbitrary layered-project importer, object decomposition or generative pixel editor is claimed.

## Real asset movement

`position_clip` adds bounded X/Y positions to a clip (frame fractions, ±50%). The source remains immutable. Browser transforms preview the move inside a fixed source-ratio frame; the existing one-encode FFmpeg renderer applies the same move over a black canvas. Audio and time are unchanged. Undo/redo restores the position. Split and pacing operations preserve each clip's position.

The MCP bridge now exposes 16 tools. `position_clip` takes `project_id`, `clip_id`, `x`, `y`, `expected_version`. Existing chat import tools remain available. `get_frame_comments` lists saved visual requests; `get_frame_comment` returns the request plus its annotated source-frame PNG as MCP image content. A marked request includes the source time, timeline version, selected clip, asset position and normalized rectangle.

Frame requests are separate from applied video edits. The UI says **Request saved. Video unchanged.** Copy the request into the connected chat to ask its assistant to inspect it. Automatic notification of the original conversation is not implemented. The assistant can apply supported timeline/position tools, but arbitrary changes to an object inside flattened footage remain unsupported.

## Verification, November 2, 2026

- **72 Python tests pass**, including actual audio/video exports with opposing per-clip offsets, unchanged stream starts/durations, position persistence through split/pacing/undo/redo, invalid transforms, stale comment anchors and annotation storage that leaves the timeline unchanged.
- **14 actual Chrome asset checks pass** using recorded `public-create.mp4`: trim source 3–8 seconds, prompt-move right 10%, nudge up, drag to a new position, undo the drag, restore Y, mark an area, save a visual request without claiming a pixel edit, then export five seconds and play the moved MP4 completely in Chrome. Original bytes stay untouched.
- Full FFmpeg decode passes for the moved export. Three exported samples match the original video shifted right 10%: mean pixel errors 0.287, 0.287, 0.285 on a 0–255 scale; the left margin is black. The source range remains 3–8 seconds.
- Live MCP returns the saved comment image at 960 × 667 and explicitly reports `video_changed: false`.
- **14 keyboard browser checks pass** after the UI changes, including import, frame stepping, trim/split/delete, undo/redo, export and full exported MP4 playback.
- Portrait/landscape compact layouts retain exact source ratios, controls below the footage, and no horizontal overflow. Controls fit an 800px-high viewport. Enlarged help or a saved request can require scrolling.

Evidence: ignored `output/playwright/assets-results.json`, `assets-verification.json`, `frame-design-editor.png`, `frame-design-comment.png`, `compact-results.json`, `keyboard-results.json`, `asset-tests.log`.

Repeat the asset acceptance with the running local editor and an agent-owned browser:

```sh
FRAME_FOOTAGE=/absolute/path/to/recorded-footage.mp4 \
PLAYWRIGHT_MODULE=/absolute/path/to/node_modules/playwright-core \
node work/frame-product/tests/asset_ui_e2e.cjs
```

No paid API calls, public deployment or live ChatGPT/Claude embedding were used to produce this result.
