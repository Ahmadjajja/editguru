# FRAME hackathon demo — style-driven live assembly

## Start

```sh
sh ~/frame-creative-agent/work/frame-product/restart-local.sh
```

Open **http://127.0.0.1:8876/swarm**. (Restart is required once so the server loads the new code.)

## Demo flow (verified end to end against the real server, 2026-11-10)

1. **Upload footage**: press *Upload footage* (or pick a recent project). The editor opens at `/swarm?project=<id>`.
2. **Words**: press *Transcribe* (local faster-whisper). Fallback if the model isn't installed: paste the script into *What you say*, or import an .srt/.vtt/Whisper .json. Words are saved to the project.
3. **Optional images**: *Add images*, then type the words that should trigger each one ("Show it when I say").
4. **Style**: *Styles…* → *Save this edit as a style*, or *Measure a reference video* (frame, color, pause tightness) → save. FRAME never invents a style.
5. **Assemble with style**: the server compiles the style into a fixed plan (same inputs → same plan digest, shown in the log). The agent cursors perform each step live. *Speed: watch / slow-mo* slows them for an audience.
6. **Interrupt**: *Pause*, change anything (caption style chip, cut a word in Pro transcript, drag a clip, add an image), *Resume*. Agents keep the change you made ("kept your style" in the log). *Stop* keeps what's done; one undo reverts the pass.
7. **Export MP4**: FFmpeg render of the saved edit → *Download vN*.

Every edit autosaves to FRAME as a timeline version; reload restores the editor exactly.

## Known limits

- Exported grade = brightness/contrast/saturation only (wheels, temp/tint and looks are preview-only).
- Caption fonts and the animated caption styles are preview-only; the export uses clean white/colored text.
- SFX and the built-in beat are preview-only. Imported music and images do export.
- Additional videos can't be added to a project from this editor yet.

## Apply a production recipe to new content

See [RECIPE_TRANSFER.md](RECIPE_TRANSFER.md). Use `/recipe-apply` for the dedicated two-step layout/caption flow; it has its own paused edit controls and saved run recovery. This is separate from the existing style-driven swarm demo above.
