# Codex prompt: independent end-to-end test of FRAME

Paste everything between the lines into Codex (CLI or desktop app) running on Dante's Mac, with
`~/frame-creative-agent` as the working folder.

---

You are an independent QA engineer and professional video editor. Evaluate FRAME, an AI-native video editor,
as a real user would, and prove whether it works end to end. Work on this Mac in `~/frame-creative-agent`
(branch `feat/style-swarm-2026-11-09`). FRAME runs locally at http://127.0.0.1:8890.

Read first, completely: `docs/AGENT_TESTING.md` (how to install, start and test everything, the rules, the
checklist F1–F16, the comparison tools and the report format). Context on what was built and why:
https://claude.ai/artifact/XBj839qjEe4zcDATjBXNwe (if you can't open it, `docs/AGENT_TESTING.md` is enough).

Hard rules:
- Document, do not fix. Do not edit, commit, stash, reset, checkout or push anything in the repo, and do not run
  `npm install` inside it. Put every file you make in `~/frame-test-runs/`.
- Never open, edit, render or send live-channel commands to project `8ba3cd4acef0484dbb2a2d9a6927abe4` (Dante's
  approved Fable edit). Never write inside `recipes/fable-52-higgsfield-mcp/`, `recipes/_styles/` or
  `recipes/chatgpt-mastery-9x16/`. Name any style you save `codex-…`.
- Use only copies: upload the files listed in §3 of the guide into NEW projects.

Do this, in order:
1. `python3 work/frame-product/tests/frame_test_guard.py snapshot`.
2. Record the environment (macOS, Python, FFmpeg, Node, `git rev-parse --short HEAD`).
3. Run the automated tests: `cd work/frame-product && .venv/bin/python -m unittest tests.test_v3 -v`. Record each result.
4. Make sure FRAME is running on port 8890 (start it as the guide says if not). Install Playwright in
   `~/frame-test-runs/tools` as the guide says and `export NODE_PATH=~/frame-test-runs/tools/node_modules`.
5. Drive the real editor in a browser with Playwright, as a user: create a test project by uploading a copy of the
   A-roll, transcribe it, import the five B-roll clips and the setup screen recording, open "First cut from a
   style…", apply "Higgsfield v3 Discovery" with the screen recording marked as the setup recording, and watch
   the agents build the edit live. Take screenshots during the build (`~/frame-test-runs/shots/`).
6. Work through every checklist item F1–F16 in the guide. In particular, test:
   - manual caption editing: select, drag, retype, lime words, size, delete, add
   - graphics movement: step labels, CTA panel, split labels, corner notes, the offer panel; resize and retext
   - B-roll replacement: swap a section's clip, change its start, add an imported clip at the playhead
   - timeline trimming: both edges of sections, captions, overlays and A-roll; moving clips; razor; undo/redo
   - external live-channel commands: `say`, `seek`, `build`, `render` against the TEST project
   - final MP4 rendering: render, download, verify with ffprobe and `qc.json`
   Reload the page and restart FRAME at least once to test persistence.
7. Preview vs render: render the test project, then run `tests/v3_preview_capture.cjs` and `tests/v3_compare.py`
   exactly as §6 of the guide says. Read every flagged side-by-side image and describe the difference. Make a few
   hand edits (move a caption, move the CTA, trim a split, swap a clip), render again, and compare again to prove
   the edits reach the file.
8. Apply the same style to a second, different talking-head clip if one is available on this Mac (ask Dante
   if not); judge how well the first cut generalizes.
9. `python3 work/frame-product/tests/frame_test_guard.py verify` and include its output.
10. Write `~/frame-test-runs/FRAME_TEST_REPORT.md` in the format of §7 of the guide: summary verdict, environment,
    pass/fail/blocked table for every automated test and F1–F16, every finding with severity (S1 blocker … S4
    suggestion), numbered reproduction steps, expected vs actual, evidence paths, and a recommended fix. Add a
    ranked list of what FRAME is missing to be a professional AI video editor. Be blunt and specific; a passing
    unit test is not evidence that the product works.

When done, print the report's summary and the path to the full report. Do not start fixing anything.

---
