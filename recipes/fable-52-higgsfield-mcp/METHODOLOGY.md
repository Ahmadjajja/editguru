# Methodology log: Fable 5.2 × Higgsfield MCP reel

This is the forward version of `../chatgpt-mastery-9x16/CLAUDE-VIDEO-OUTLINE-TEMPLATE.md`. ChatGPT Mastery had to be *recovered* a day after it was made, and still had gaps. This video is documented **while** it's made, so its recipe can be compiled at the end without a recovery.

**Rules (from the template):**
- Every exact value points to a source, a measurement, or an explicitly labeled new choice.
- Source and output time are kept separate.
- Your decisions are kept apart from mine.
- A successful render is never treated as approval.

**Evidence statuses:** copied from source · derived from source · measured · inferred · newly chosen · unknown.

## Phase status
| Phase | Status | Artifact |
|---|---|---|
| P0 Request | done 2026-11-10 | `history/user-requests.json` |
| P1 Brief captured | done 2026-11-10 | `sources/brief-captured-2026-11-10.md` |
| P2 Requirements extracted | done 2026-11-10 | `REQUIREMENTS.md` |
| P3 Craft logic studied | done 2026-11-10 | `CRAFT-LOGIC.md` |
| P4 Plan + script draft | drafted 2026-11-10; awaiting G1/G2 | `PLAN.md` |
| P5 Style source | set 2026-11-10: your Higgsfield v3 edit (font substitute pending) | `specifications/STYLE-HIGGSFIELD-V3.md`, `style-higgsfield-v3.json` |
| P6 Footage + intake | open (G4) | `inventory.json`, `analysis/` |
| P7 First assembly in FRAME | not started | — |
| P8 Review rounds | not started | `history/`, `versions/vN/` |
| P9 Compliance check | not started | `verification.json` |
| P10 Post | not started | — |
| P11 Compile recipe | not started | `recipe.json` (only at the end) |

## Decision ledger
| ID | Date | Decision | Source | Status | Reusable? |
|---|---|---|---|---|---|
| D1 | 11-10 | Make it in FRAME | Your answer to "Which tool…" | copied from source (your decision) | per video |
| D2 | 11-10 | Entirely new visual style; reuse ChatGPT Mastery's *crafting logic* only | Your answer: "we're doing an entirely different style for this one. but the logic behind how the video was crafted should be studied." | copied from source | the logic is reusable (CRAFT-LOGIC §2) |
| D3 | 11-10 | The body is your own footage | Your answer | copied from source | per video |
| D4 | 11-10 | Take only what's needed to satisfy Higgsfield; replicate nothing stylistic | Your message with the Drive reference | copied from source | candidate preference for every sponsored brief |
| D5 | 11-10 | Brief wording overrides the supplied example's wording (hook, offer, CTA) | Brief: "this exact voiceover" | derived from source | yes |
| D6 | 11-10 | Beat order follows the brief (offer before setup), not the Drive example (setup first) | Brief intro + CONTENT FORMAT order | derived from source | yes |
| D7 | 11-10 | Footage is referenced by path + SHA-256, not copied | about 5 GB free disk (`df`, 2026-11-10) | newly chosen (Claude, operational) | yes while disk is tight |
| D8 | 11-10 | This folder has no `recipe.json` until the end, so FRAME's recipe hub doesn't list an incomplete recipe | `quick_recipe.list_recipes` only lists folders containing `recipe.json`; checked `/api/recipes` on :8890 | newly chosen (Claude) | yes |
| D10 | 11-10 | Style source = your accepted Higgsfield v3 Discovery edit. D2's "entirely different style" meant different from ChatGPT Mastery, not from our Higgsfield edit | Your message: "did we not document the editing style for the higgsfield video we created in this chat?" | copied from source (your correction) | yes: your house style for Higgsfield work |
| D11 | 11-10 | v3 saved as a `frame-style/1` file; FRAME's validator accepts it. Font Inter Black stands in for SF Pro | `quick_style.validate()` run; FRAME's `CAPTION_FONTS` | newly chosen (Claude); font needs your OK | — |
| D9 | 11-10 | Media kit listed, not downloaded | Download needs your OK; 830 MB vs 5 GB free | newly chosen (Claude) | — |

## Footage intake 2026-11-10 (A-roll)
- File: `D439ECEF-E0F5-405C-911F-2B01CB97AFF7.MP4`, 41.633 s, 1080×1920 HEVC 30 fps + AAC, sha256 `a9710a29…` (first 16 hex `a9710a293d411814`). Supplied in chat; copied byte-identical into FRAME project `8ba3cd4acef0484dbb2a2d9a6927abe4` (`work/frame-product/jobs/`), hash verified after copy.
- Transcript: faster-whisper `small.en`, word timestamps (ASR estimates), saved as the project's `transcript.json`.

| Source time (s) | Spoken (ASR) | Beat |
|---|---|---|
| 1.02–6.26 | "Claude Fable 5.2 just dropped and you can now generate entire commercials with a single prompt." | Hook |
| 8.02–14.12 | "I'm talking cinematic product videos, crazy visuals, and full AI generated ads just from an idea." | Showcase |
| 15.86–20.16 | "Here's how it works. Open Claude, go to Connectors, and connect Higgs Field." | Setup |
| 22.10–27.98 | "Then just upload your product image, tell Claude what you want to create, and watch it turn that image into a commercial." | Setup |
| 30.06–36.16 | "And the craziest part, Higgs Field is offering unlimited MCP use for new users during the promotion." | Offer |
| 38.00–40.84 | "Follow me and comment Fable and I'll send you the full setup." | CTA |

**Compliance finding (vs REQUIREMENTS.md, measured on the ASR):** A2 hook, A5 offer and A8 CTA are not word-for-word; offer comes after setup (A1 order is offer → setup); no on-camera reaction (A3); no "3 days" or "free" spoken. A first cut can be built from this take, but it will not pass G6 without re-recorded mandated lines or written approval from the Higgsfield contact.

**Transcript corrections (Claude, 2026-11-10):** ASR sub-word tokens merged (`5` + `.2` → `5.2`); `ClaudeFable` split into `Claude` + `Fable` (boundary at character ratio, estimate); `Higgs Field` → `Higgsfield` (2×). Raw ASR kept in this log above; corrected words are the project's `transcript.json`.

**First-cut plan (dry run, not yet applied):** style `Dante · Higgsfield v3 Discovery` rev 1 on project `8ba3cd4acef0484dbb2a2d9a6927abe4`, 94 words → 11 ops, plan digest `2a5d958d3248…`: 9 pause cuts totalling 10.49 s (41.63 s → about 31.14 s, inside A10's 30–60 s), frame 9:16 cover, captions 3 words/line upper-case white at y 0.635, size 0.034, #E2FD56 emphasis (preview only). Font Inter Black pending Dante's OK.

**v3 Discovery look as FRAME templates (Claude, 2026-11-10):** `work/frame-product/quick_v3.py` ports Dante's accepted v3 compositor and mix (codex-handoff `hf_render_v3.py`, `hf_render_v2.py`, `hf_mix_v3.py`) into parameterised templates: split screen, numbered card, offer card, CTA card + end hold, lime-emphasis slide-up captions, 120 BPM bed with event SFX and voice ducking, −14 LUFS master. Placement comes from `visual-map.json` (spoken anchor → visual), resolved on measured speech (10 ms energy envelope, onset −50 ms / tail +80 ms, v3 rule 1). Media-kit clips chosen by Dante: commercial (watch, track bike), cinematic (desert run), hypermotion 05 (headphones), ugc (mug).
- Plan on project `8ba3cd4a…`: 6 measured lines, 41.63 s → 32.48 s; visuals: face 0–3.46 · COMMERCIALS 3.46 · CINEMATIC 5.93 · HYPERMOTION 7.71 · UGC ADS 8.75 · card "HERE'S HOW IT WORKS" 11.74 (rows on open / connectors / connect / upload / tell) · IMAGE → COMMERCIAL 19.70 · offer card (A6 text) 22.08 · CTA "COMMENT FABLE" 28.07, lands on "Fable".
- Test render (Claude sandbox, Inter fallback font): 974 frames, A/V 32.47/32.45 s, −14.8 LUFS, voice 17.4 dB over the music bed, 0 captions crossing cuts. On the Mac it uses SF Pro (system font), like v3.
- Open: A14 vetting of the chosen clips (the watch clip shows the fictional brand "VELORIX"); mandated-line compliance still pending (see intake finding).

## Open decisions
- **O1–O5:** REQUIREMENTS.md §C (offer window, "new users" wording, setup platform, clip vetting, UTM link).
- **O6:** ~~Style source~~ closed by D10. Remaining: your OK on the Inter Black font substitute.
- **O7:** Which 4–5 media-kit clips and categories to show.

## Timeline domains (fill in once footage exists)
- **Source time:** seconds from the start of each footage file, identified by its `sha256` in `inventory.json`.
- **Output time:** seconds in the reel, 30 fps. The canvas is assumed to be 1080×1920 for an Instagram Reel; confirm it at export.
- **Every record keeps both times.** That applies to cuts, captions, overlays, the category names on the showcase clips, the offer text, the FABLE keyword, music and SFX. It also says whether a spoken-word anchor is measured or an ASR estimate.

## Version log
_(empty: one row per FRAME version: version id, what changed, the request it answers, export path + hash)_

## Verification log
| Date | Check | Result |
|---|---|---|
| 11-10 | `tools/intake.py` on the Drive reference | Its SHA-256 matched a separate `shasum` run (`525dccbe…a78a`); a re-run dedupes; contact sheet written to `analysis/` |
| 11-10 | FRAME recipe hub unaffected | `GET :8890/api/recipes` still lists only `chatgpt-mastery-9x16` |
| 11-10 | v3 style JSON | `quick_style.validate()` accepted `specifications/style-higgsfield-v3.json` (fields: captions, frame, pacing) |
| 11-10 | Drive reference beat budget | Whisper `small.en` transcript in `analysis/drive-reference_transcript.json` (ASR estimates, not verified boundaries) |

## Compiling the recipe at the end (P11)
Each phase above becomes one `recipe.json` step in FRAME's `frame-recipe/1` format: `phase`, `title`, `request` (quoted from `history/user-requests.json`), `did`, `show` (the real artifact), and `place` (the real assets at final output times). Nothing is reconstructed after the fact.
