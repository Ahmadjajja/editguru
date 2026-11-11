# FRAME autonomous engineering loop

## Source and adaptation

The Pragmatic Engineer's March 2026 interview, [Building Claude Code with Boris Cherny](https://newsletter.pragmaticengineer.com/p/building-claude-code-with-boris-cherny), describes planning before implementation, agents working in isolated checkouts, reviewing generated code, and turning recurring review comments into automated rules. FRAME uses those practices where they improve delivery; this document does not assume its team or tooling is identical to Claude Code's.

## Each cycle

1. Read the product contract, task ledger, prior QA, and latest CI result. Identify one user-visible deficiency with an observable acceptance test.
2. Write a brief execution plan in the ledger: intended behavior, owner, independent reviewer, media fixture, and expected evidence. Prefer working prototypes over speculative design.
3. Give independent tasks isolated Git worktrees or branches. The builder must not mark their own output accepted. Integrate sequentially to avoid competing edits.
4. Build the smallest real behavior that advances the five phase iPhone flow. Preserve immutable checkpoints and project history.
5. Run automated tests and the cloud iPhone build. For media changes, inspect actual source and rendered MP4s, stream metadata, timing, and playback. For UI changes, inspect the simulator or device flow when available.
6. Have an independent reviewer apply the technical gates in `work/frame-qa/QA_NOTES.md` and the creative rubric in `work/frame-taste/PROFILE.md`. Record timecoded defects and verify a rerender after fixes.
7. If the same review problem recurs across several cycles, encode it as a test, lint rule, or release gate. Do not accumulate repetitive prose warnings.
8. Commit and push only a working checkpoint, update the task ledger with evidence, then choose the next deficiency.

## Release gate before founder review

Founder feedback is requested only after a complete, playable iPhone to cloud workflow has been demonstrated with real footage, all five phases produce meaningful output, an independent technical and creative review has passed, and the result is worth showing. The review package should include the app build, source and exported videos, the five checkpoint clips, a short account of creative choices, and material remaining limitations. The founder should be asked about taste or strategic choices, not engineering details.

## Durable execution

GitHub is canonical version control; push CI runs Linux real-media tests and a macOS iPhone simulator build. A 30-minute Codex heartbeat resumes the engineering loop and stays quiet until a substantial verified milestone or genuine blocker. This heartbeat runs on the local host and cannot guarantee execution while the Mac is offline. Cloud deployment, durable render jobs, object storage, and remote monitoring are still needed for the product and for fully independent operation.

## Taste and control role

The creative critic uses only evidence-backed preferences in `work/frame-taste/PROFILE.md`. It records whether an edit serves the creator's intent and likely audience effect, while labeling untested audience appeal as a hypothesis. It never claims to be Dante or silently imports his accounts or media. The founder remains the final authority on subjective taste when a substantial reviewed result is ready.
