# Independent QA record

The Replit inspection calls returned empty responses, so its implementation remains unverified.

Independent QA used an 8-second portrait speech clip. The local media core produced five distinct H.264/AAC MP4s that fully decode. It verified byte-identical export after restoring V3, and a V4 revision branch retained the prior version. The QA harness also correctly rejected five identical files as a negative control. Detailed evidence is in `work/frame-qa/QA_NOTES.md`.

The second independent pass used the HTTP API end to end: project creation, upload, five renders, byte-range playback, revision, restore, export, and list persistence passed. V1 now detects opening silence with a speech guard; V3 uses a secondary reframed shot from creator-owned footage. Five H.264/AAC outputs remained distinct and fully decodable. The 8-second source became approximately 7.6 seconds after the deliberate opening cut.

V4 text remains static rather than synchronized captions. Cloud persistence, iPhone runtime behavior, and creative publishability remain unverified. This is a local rendering prototype, not an accepted product milestone.

Later verification: a limited direction vocabulary now changes media in phases 1, 2, 3, and 5. Chunked upload survived an HTTP server restart and an invalid completed upload reset correctly for retry. Five local tests pass. GitHub Actions run 38495049597 passed both the Linux real-media test job and macOS iPhone simulator build. General creative direction, cloud hosting, device usability, and creative quality remain open.
