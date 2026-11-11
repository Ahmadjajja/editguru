# Frame editor checkpoint — November 3, 2026

This is a source checkpoint on `feat/pins-claude-mvp-2026-11-02`, not a stable release or a merge. It preserves the current local MCP App, reference and revision workflow plus the branch's earlier local-editor commits. The draft review targets the existing Quick Edit branch so earlier native/iPhone experiments are not presented as new work.

## Included implementation

- Shared embedded and local `/frame` editor, bounded app-only media transport, source-frame markup, atomic source-range sections and overlapping section rows.
- Persistent reference videos and captured reference frames with section/aspect notes; explicit current-chat project routing, host attachment import and content reuse.
- Per-video history, newest-first dropdown, read-only inspection, Restore as a new version, retained original/history and separate project library.
- Durable same-chat implementation handoffs with duplicate suppression, submitted/received distinctions and preserved ambiguous failure state. A validated completed result can be linked to the original saved note.
- Separate original-section exports, activity journaling and desktop FFmpeg startup discovery.
- Locked MCP Apps SDK 2.0.4, editable widget modules and paired built HTML required by the runtime. CI rebuilds the HTML and rejects drift.

The inclusion manifest is this document plus `.github/workflows/verify.yml`, `.gitignore`, current root/setup/connector documentation, changed product Python/legacy review code, all new production `quick_*` modules except `quick_widget_preview.py`, `widget/` source/lockfile, paired `frame_widget.html`/`frame_local.html`, and the associated regression tests. Exact staged paths and SHA-256 values are recorded by the release captain outside the product repository.

## Separate cloud checkpoint

Cloud source is maintained in a separate Sites-managed checkout and is not copied into this local source tree. Accepted owner-web manual checkpoint: version 24, source `40bc3b92ef6648adb8336af0c1583206da0683f1`, deployment `appgdep_6aea36b136cc81918f03788c950439f3`, environment revision 4. Further creative work may advance that checkout independently after this snapshot.

Actual owner-account Work browser checks covered launch/fresh setup, upload, playback, trim/split/undo/redo, marked frames, same-chat authorized position editing, full MP4 download, original-section download with the full preview retained, reference-video capture, real chat-attachment import, historic inspection/Restore/reopen and grouped timestamps. Downloaded synthetic full and section outputs matched their cloud checksums and fully decoded. The authorized edit preserved the first segment and moved the second by the requested 5%.

Local representative creative proof is V9: an actual embedded saved revision was received, implemented through editable creative assets, exported/downloaded, decoded and linked as applied to its original note. The output was 157.3 seconds, 1920×1080, 30 fps; SHA-256 `299e1b4f29f0fc96ea1fc5c3f73cac4e96058e401285ff2decb66d95027cc3c9`. The media and private project records are excluded. V10's eight newer design requests remain in progress outside this checkpoint.

## Limits and exclusions

Cloud manual editing acceptance does not establish full local creative-engine parity: advanced creative planning, custom visual rendering and audio workflows remain required and unported at the referenced cloud checkpoint. Work-chat requests can prefill a new chat, then require explicit host Work/Send steps; there is no verified automatic one-click new Work API. The local native extra-panel shortcut has an actual Codex host-routing failure and is not accepted merely because `open_in_codex` returns queued. Public listing, other-account installation and multi-owner capacity are unverified.

No secrets, `.env` contents, host/tunnel credentials, private account configuration, user videos, screenshots, raw project/journal records, browser profiles, generated render output, caches, environments or node_modules are added. The ad-hoc `quick_widget_preview.py` debug server is deliberately excluded; it contains a hardcoded fixture context and is not the supported runtime. Existing historical tracked fixtures are not newly added by this checkpoint.

## Reproducible verification

From `work/frame-product`: install Python Pillow, requests, numpy and msgpack and system FFmpeg/FFprobe; `npm ci`; `npm ci --prefix widget`; `npm run build --prefix widget`; `python -m unittest discover -s tests -p 'test_*.py' -v`; `npm test`. Linux motion verification additionally installs `fonts-dejavu-core`; the compositor keeps preferred desktop fonts and uses installed DejaVu fonts when those are absent. Run `python -m unittest -v test_server.py` for the invitation gateway and `python -m unittest discover -s work/frame-core -v` from the repository root for the media core. CI also retains the iOS simulator build gate for the inherited native source.

The release captain records final local results, remote commit SHA and GitHub CI outcomes in the delivery report. Test fixtures and mocked host delivery alone are not described as physical or production acceptance.

The isolated checkpoint passed 137 product Python tests, five real-media core tests, five invitation-gateway tests and all four JavaScript suites. Both built HTML files exactly reproduced the reviewed source bundles. Independent focused re-review passed 34 tests after fixing approved-render playback/download registration and legacy-render lookup. A strict existing frame-comment test also exposed and now verifies consistent empty activity state on first load and reload.

The first full Linux CI run exposed missing msgpack installation and the inherited compositor's macOS-only font directory. The normal follow-up installs those test resources and adds a preferred-font/free-font resolver with three regression cases. The resulting 140-test product suite passed locally; latest remote CI remains the delivery gate.

Dependency audit reports one low-severity esbuild advisory affecting its Windows development server. This project invokes the build API and does not start that server; the pinned build dependency is retained. This is disclosed rather than described as a clean audit. Public/production security acceptance and broad creative cloud parity are not implied.
