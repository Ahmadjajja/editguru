# Architecture decisions

## ADR 001: Native client and media service

Use SwiftUI and AVFoundation for iPhone interaction and playback. Keep the editable timeline, agent decisions, FFmpeg rendering, and persistent checkpoints in a service that can run without the founder's laptop. A local implementation proves the API and rendering pipeline before selecting paid cloud infrastructure.

## ADR 002: Real checkpoints

Each phase produces a new media artifact and records its source, decisions, rationale, and lineage. A phase is not marked complete from a status string alone. Revisions branch from a selected checkpoint; restoration changes the active checkpoint without deleting history.

## ADR 003: Continuous work

A Codex heartbeat resumes engineering every 30 minutes in this thread. Its prompt requires inspection, implementation, real-video testing, independent QA, and quiet operation until a substantial verified milestone or genuine blocker. It is a continuation mechanism, not a guarantee of uninterrupted compute; render jobs eventually need a durable cloud queue.
