# Frame video editor

Frame edits existing footage: import a video, mark sections, save revision notes, preview cuts, and export an MP4. Projects and exports are saved locally. This directory also contains a separate, older invite-only generation gateway; its setup is in [PILOT_GATEWAY.md](PILOT_GATEWAY.md).

## Start the editor from this checkout

Requirements: **Python 3.9 or newer**, **FFmpeg**, and **ffprobe**. On macOS, install FFmpeg with `brew install ffmpeg`; on Ubuntu, use `sudo apt install ffmpeg`. Run these commands from this directory:

```sh
sh start-local.sh
```

The launcher creates a local `.venv` and installs the manual editor dependencies on first run. Setup needs an internet connection. If installation is interrupted, run the same command again. Once setup finishes, open **http://127.0.0.1:8876/frame** in your browser. Keep the terminal running; Ctrl+C stops this foreground server. Saved projects remain in `jobs/`.

To choose another port, run `PORT=8877 sh start-local.sh` and open `http://127.0.0.1:8877/frame`. Use a free port; do not run two copies on the same port.

On macOS, [QUICK_MAC_SETUP.md](QUICK_MAC_SETUP.md) describes the optional background launcher. An installed Frame connector has its own managed runtime and project store: use that installation's launcher and address rather than starting this source checkout against it.

## Make a first edit

1. Import an H.264/AAC MP4, up to five minutes and 700 MB. Keep the original until you have checked the export.
2. Seek to a section's start and press **I**. Seek to its end and press **O** to save the section. Shortcuts work when focus is outside a text field; the start/end controls also work with the mouse.
3. Add the requested change to the section's notes. Use **Preview** to check the saved range and **Adjust** to correct its boundaries.
4. Export the cut and download the completed MP4. Review the result before using it; you can continue editing while an export runs.

Manual editing, preview, export, and audio-energy pause detection need no model login. Pause detection measures audio energy, so review its proposed cuts to protect quiet speech. Chat-directed implementation and host attachment import require a connected host; opening the standalone page does not connect it to a conversation automatically.

## If something does not work

- **Setup was interrupted:** rerun `sh start-local.sh`; missing dependencies are retried without deleting saved projects.
- **The server starts but the page does not open:** enter the `/frame` address yourself. The launcher does not open or control a browser.
- **The chosen port belongs to another service:** select a different `PORT`. Do not stop an unknown service to free it.
- **A video cannot be inspected:** export a fresh H.264/AAC MP4 and import that copy. Keep the original; failed uploads can be retried.
- **Playback fails:** use the editor's playback retry/refresh controls and wait for loading to finish before seeking again.
- **Chat can no longer call Frame after an update:** refresh the connector registration when its tool set or protocol has changed. A browser refresh alone cannot update the chat's registered tools.

The editor binds to loopback. The optional pilot gateway is a separate deployment path with separate access controls, not a way to expose this editor publicly.

## Connected editing workflows

### Chat video references

In References, choose **Add video from chat**, or tell the chat “add this video as a reference.” Frame publishes the active project ID and tab to this conversation. `import_reference_video` requires that target project ID and exactly one actual host attachment `file`, host `source_path`, or saved `reference_project_id`. It imports and links in one action, keeps the edit project selected, and opens References. Matching reference bytes are reused. No global most-recent-project routing or attachment enumeration is used. If a host does not supply access to its attachment, the assistant must report the missing handoff. Newly added tools require a refreshed MCP registration; the installed bundled command interface can invoke the tool immediately.

### Open the current project beside chat

With focus in Frame, press **⌃⌥⇧O** (Control+Option+Shift+O on Mac) or **Ctrl+Alt+Shift+O** (Windows/Linux). Frame sends the exact saved project URL to the current chat so the assistant can open an additional right-hand browser panel with `open_in_codex`. The host must support sending messages and opening browser panels; standalone browser mode cannot open a Codex panel. A sent request is not confirmation that the panel opened. The shortcut ignores text fields and held-key repeats and never edits the project.

The original ⌘⇧O binding was removed after a real user test opened a blank Codex session: the native host intercepted that combination before Frame received it.

Actual native-host testing still found the extra panel missing: `open_in_codex` queued the request and logs associated an earlier browser with a temporary draft conversation. This shortcut is implemented but its intended panel-opening behavior is not accepted. Do not treat a queued host request as an opened panel. See the [checkpoint](../../docs/CHECKPOINT_2026-11-03.md) for accepted workflows and remaining limits.


## Continue editing a completed revision

`record_revision_result` validates each applied request against a completed full-video export. Once all included requests are applied, Frame imports that exact verified export as the next editable source and returns `next_revision`. The editor follows this scoped lineage automatically, loads source mode, and publishes the new active project to the chat. This avoids returning to an older rendered preview or requiring another upload.

Completion retries reuse the same imported source without replacing subsequent notes or edits. Pending requests, a newer manual edit, an inspected historical revision, or unsaved input prevent a stale switch. The revised copy links back through **Previous project**; original footage, references, timestamps and revision history remain in the parent. Source anchors for the next round belong to the newly imported video, so old coordinates are not silently copied across a trimmed or reordered render.

Regression coverage: `python3 -m unittest discover -s tests -p test_revision_result.py` and `npm test`. The continuation UI test covers automatic media adoption, a subsequent edit on the new project, unsaved-range protection, and deliberate parent inspection.

The **Compare versions** button splits the preview into Current version and a previous-version dropdown. Play, pause and seek are shared, with audio from the current version. Previous exports and the original upload are available; timeline-only checkpoints need an export before their edits can be played. Revised-copy projects also offer their previous project. Close comparison to return to a single preview.

General revisions: the compact prompt bar above saved sections stacks whole-version requests without timestamps or section selection. Requests persist with the project and are included in the implementation handoff; Remove/Include keeps their history. Each verified next editable copy starts a fresh revision round.


## Working projects and saved video versions

The single top dropdown contains versions of the current project, including saved versions from earlier editing rounds. **All projects** opens the persistent library for project switching. Detailed edit checkpoints are tucked into **Edit history** below the workspace.

**Video versions** counts saved videos and prompt snapshots, excluding split/trim checkpoints. An export and the prompt snapshot referencing that same export count once. Every **Send implementation prompt to chat** first exports an unsaved timeline, then durably freezes the exact prompt, notes, sections, additional frame comments, source/export ID and video SHA-256 before sending. Failed saving blocks delivery; delivery failures retain the snapshot. Retrying the same prompt reuses its version. Timeline counters remain explicitly labeled as timeline versions.

**Edit history** retains intermediate timeline checkpoints for restoration. Historical views use recorded notes/sections, never current annotations substituted into old history. Older checkpoints without captured review data say so. Earlier-round snapshots are read-only; restoring one creates a branch while later projects remain in All projects. This is local editor behavior; cloud publication is separate.
