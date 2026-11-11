# FRAME iPhone client

Native SwiftUI prototype for the five-phase editing workflow. Open `project.yml` with XcodeGen (`xcodegen generate`), then open `FRAME.xcodeproj` in Xcode. Requires Xcode 16 or newer and iOS 17 or newer.

The app has project creation, resumable file upload, phase progress, AVKit playback, natural-language direction, revision, checkpoint restoration, and export sharing. Configure the cloud URL in Settings. The default `http://localhost:8765/` is for a development server in the iOS Simulator; on a physical iPhone use a reachable HTTPS backend address.

## Provisional API contract

- `GET /api/projects` → `{ "projects": [Project] }`
- `POST /api/projects` with `{ "title", "brief" }` → `Project`
- `GET /api/projects/{id}/media/upload` → `{ "offset", "total", "complete" }`
- `PUT /api/projects/{id}/media/upload` with up to 4 MB of MP4 data, `X-Upload-Offset`, and `X-Upload-Total` → updated upload status. The client retries from the server offset after interruption.
- `GET /api/projects/{id}` → `Project`
- `POST /api/projects/{id}/directives` with `{ "phase", "instruction" }` → `Project`
- `POST /api/projects/{id}/revisions` with `{ "checkpoint_id", "instruction" }` → `Project`
- `POST /api/projects/{id}/restore` with `{ "checkpoint_id" }` → `Project`
- `GET /api/projects/{id}/export` → `{ "url": "https://…/master.mp4" }`

`Project`: `id`, `title`, `brief`, `status`, `current_phase`, `progress_message?`, `checkpoints`. `Checkpoint`: `id`, `phase` (1–5), `version`, `video_url`, `created_at` (ISO 8601), `rationale?`.

The current implementation is an integration shell. It does not imply that the backend, rendering, auth, background upload recovery, or export is complete. Those require end-to-end validation on a device and real video.
