# How ChatGPT Mastery was crafted: the logic to reuse

Study date: 2026-11-10. Source: the recovered production in `../chatgpt-mastery-9x16/`. Every claim points to a file there. Where I'm interpreting rather than quoting a record, it says **interpretation**.

**Scope for the next video:** an entirely different visual style, your own footage, made in FRAME (decided 2026-11-10). So this document keeps the *process logic* and explicitly drops the *look* (§3).

---

## 1. The process, as it actually ran

| # | Phase | What happened | Evidence |
|---|---|---|---|
| 1 | Brief | You named every story beat up front: the hook ("what happens if you master chatgpt"), story, twist (prompt → click → generate), payoff, cliffhanger, plus music, narrator, character and format. | `history/user-requests.json` #0–#1 |
| 2 | Plan + hold | The beats became a timed table (0–4 / 4–15 / 15–25 / 25–35 / 35–40 s). Open decisions were listed, and nothing was generated until you said so. | `project/PLAN.md` ("Hold point") |
| 3 | Script before visuals | A 9-line script in the narrator's voice, approved before any storyboard. Each line later became exactly one visual unit (A01–A08). | `project/SCRIPT-V1.txt`; `recipe.json` step-05 placements |
| 4 | Reference study | You supplied a reference for "transitions and pacing … premium and fast paced". It was sampled into contact sheets (including a 12 fps transition detail) before storyboarding. | user-requests #3; `project/reference-analysis/` |
| 5 | Storyboard, three passes | Schematic, then illustrated, then a revision. The constraints came from you: every scene visually distinct; simpler animation; one main setting; "add less to certain frames because … we will have other stuff going on". | user-requests #3–#5; `project/STORYBOARD-V1.md`, `Storyboard-V2/`, `Storyboard-V3/` |
| 6 | Produce, then open in FRAME | A first full draft (V1), opened in FRAME for review. | user-requests #5; `project/V1/START-HERE.md` |
| 7 | Review loop in FRAME | You pinned sections at **source-time anchors** with plain-language notes. Each saved revision set became a checklist mapping every pin to its output time, was implemented, and produced a new version. | user-requests #12; `project/V6/saved-request-snapshot.json`, `project/V6/CHECKLIST.md` |
| 8 | Package last, separately | The intro was built as its own short piece and "taped onto the existing footage" (V5). It was replaced twice (V8, V9) while the body and mix stayed locked. | user-requests #9, #13; `project/V9/design.json` (`body_source`, `audio_source` reused from V8) |
| 9 | Targeted pacing fixes | Dead space was removed as specific measured intervals (two 4-frame holds in V7) with no spoken words cut. | `RECOVERY-AND-DECISION-REPORT.md` ("Remove specific dead space") |
| 10 | Format pivot by containment | Going 16:9 → 9:16 late, you were asked how the edit should fit and chose "keep the complete edit visible as a 16:9 inset". It was not re-cut. | user-requests #14–#15; `specifications/framing.json` |
| 11 | Realism check | You rejected the playing video looking like an *input*; it had to look like *output*, with the UI dimmed behind it. | user-requests #16; `project/V9/QC.json` (`input_attachment: false`) |
| 12 | Measured QC per version | Every version kept its own START-HERE, checklist, previews and QC. V9 measured the output region before/after send, inset differences at six times, and a full decode. | `project/V*/`; `project/V9/QC.json` |
| 13 | Recipe afterwards | The whole production was recovered into an evidence-backed recipe a day later. | `RECOVERY-AND-DECISION-REPORT.md` |

## 2. The rules underneath (what transfers)
1. **Beats before words, words before pictures.** Brief beats → script → storyboard → media, and each stage is approved before the next starts. Spending (credits, renders) only begins after the storyboard is approved (§1 rows 1–5).
2. **One spoken line = one visual unit.** The script is the edit's skeleton. Visual changes land on line or word boundaries (row 3; V6 checklist aligns word entrances to narrator word times).
3. **Study a reference before designing, and name the feeling in words.** "Premium and fast paced" plus a real clip beats an abstract style description (row 4).
4. **Constrain the frame, then fill it.** Distinct look per scene, simpler motion, deliberate empty space for overlays (row 5). **Interpretation:** this kept the frame readable once captions and cards were layered on.
5. **Gate every expensive step on an explicit go.** The plan carried a hold point, and each "no generations yet" was honored (row 2, user-requests #3–#4).
6. **Review in FRAME with pins at source time.** Notes anchored to source time survive later cuts. Every note becomes a checklist row with its output anchor before anything is edited (row 7).
7. **Lock the body, iterate the packaging.** Intro and format changes were done on top of a frozen body and mix, so each revision was cheap and couldn't break the story (rows 8, 10).
8. **Cut time, not words.** Pacing fixes remove measured silent intervals, and the spoken script stays intact (row 9).
9. **Ask before reinterpreting a format change.** For 9:16 you were asked one question (inset vs crop) instead of a guess (row 10).
10. **Honesty of the demo is a creative requirement.** What's shown as AI output must read as output, and composited demos are labeled in the records (row 11).
11. **Every version is a folder you can reopen.** START-HERE + checklist + QC per version, nothing overwritten (row 12).
12. **Capture the recipe while producing, not after.** The recovery took a separate day and still had to mark gaps (missing temp screenshot, unpinned dependency versions). For the next video, the log in `METHODOLOGY.md` is written as we go (row 13).

## 3. What does *not* transfer (the old style and content)
Manga artwork and the two animated shots; the Fish Audio "Master Oogway" narrator and the ×1.263 tempo compaction; the ChatGPT-style typing intro, purple glow and 22% UI plate; the 16:9-inset-in-9:16 layout; white/black stat cards and DIN counters; Arial Bold 46 px captions; the 144 BPM bed and ninja SFX. Sources: `specifications/*.json`, `transfer.json` (`excluded`).

**Specific warning:** the narration-trimming thresholds (RMS > 0.004 in 20 ms windows, 500 ms quiet runs, `prepare_audio.py`) were tuned on synthetic Fish audio. The recovery report says to re-evaluate them per speaker (`RECOVERY-AND-DECISION-REPORT.md`). Your own voice needs its own measurement.

## 4. What changes because the body is your own footage
- **The script may not be the timing source.** With narration we controlled timing; with your takes, the *recording* defines it. Plan for take selection (best take per line) and retakes.
- **Cut on measured speech, not transcript times.** In the zenzap-ad Higgsfield runs, Whisper's first-word times were 0.08–0.88 s early against measured speech (`~/Downloads/zenzap-ad/codex-handoff/evidence/results/C2_dialogue_boundaries.md`). That's a different project, so treat it as a caution, not a rule. FRAME's Swarmcut has word-timing pause detection with protected words and retake detection (`docs/STYLE_SCHEMA.md`, "Swarmcut keeps"), and `tighten_pacing` exposes silence settings.
- **Lip sync and continuity matter.** Picture and sound must come from the same source time on every on-camera cut.
- **The new style has to come from a source.** FRAME's rule is reference-first: a style is saved from your own edit, measured from a reference video (frame, color, pause tightness), or started from the FRAME starter (`docs/STYLE_SCHEMA.md` rule 1, `docs/HACKATHON_DEMO.md` step 4). We need your style reference.
