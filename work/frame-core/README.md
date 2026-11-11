# FRAME local media core

Run `python3 -m unittest discover -s work/frame-core -v` from the workspace root. CI prerequisites: Python 3.9+, FFmpeg with libx264 and AAC encoders, ffprobe, and Pillow. Install Python dependency with `python3 -m pip install -r work/frame-core/requirements.txt`. The HTTP test uses `work/frame-qa/portrait_speech.mp4`; keep that fixture available in CI.

Start the local HTTP service with `python3 work/frame-core/frame_api.py --host 127.0.0.1 --port 8765`. Set `FRAME_DATA_DIR` to relocate persistent project data. The API matches `work/frame-ios/FRAME/FrameAPI.swift`, including raw MP4 uploads and byte-range playback.

CLI:

```sh
python3 work/frame-core/frame_core.py create input.mp4 work/my-project --brief 'Cinematic opening'
python3 work/frame-core/frame_core.py render work/my-project 1
python3 work/frame-core/frame_core.py render work/my-project 2
python3 work/frame-core/frame_core.py render work/my-project 3
python3 work/frame-core/frame_core.py render work/my-project 4 --caption 'A NEW STORY'
python3 work/frame-core/frame_core.py render work/my-project 5
python3 work/frame-core/frame_core.py export work/my-project final.mp4
```

`project.json` stores immutable checkpoint records and the active checkpoint. To revise, render a phase again with `--parent CHECKPOINT_ID`; to restore, use `restore PROJECT CHECKPOINT_ID`.

Current limits: phase 1 detects initial silence and trims it with a 120 ms guard, but does not analyze story structure or silence within speech. Phase 3 uses a close reframing from the creator's own footage as a secondary shot; it does not fetch external assets. Phase 5 normalizes audio but does not select licensed music. Direction parsing currently supports a small explicit vocabulary: keep opening/tight, warm/cool/vibrant/muted/brighter/darker, left/right/closer, and louder/quieter. Other natural-language directions are recorded but do not yet drive a change. The local HTTP service has no authentication or deployment configuration and must not be exposed publicly.

For resumable upload, GET `/api/projects/{id}/media/upload` returns `{offset,total,complete}`. PUT a raw chunk to that path with `X-Upload-Offset` and `X-Upload-Total` headers. The server appends and fsyncs each chunk, persists the total, and promotes the completed validated MP4 to `source.mp4`. After a network interruption or server restart, GET the offset and send the remaining bytes. The original one-shot POST `/api/projects/{id}/media` remains supported.
