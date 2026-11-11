# Style source: Dante · Higgsfield v3 Discovery

This is the editing style of `higgsfield_content_factory_v3_DISCOVERY.mp4` (SHA-256 `9c3ae3c5…f288`), the Higgsfield reel made and accepted in the zenzap-ad chat on 2026-10-24.

**Where the original documentation lives:**
- `~/Downloads/zenzap-ad/codex-handoff/HANDOFF.md`, sections 3.2–3.4
- the exact code: `codex-handoff/reference_code/higgsfield_reel/hf_render_v3.py`, `hf_mix_v3.py`
- the measurements: `codex-handoff/evidence/results/C1–C5`

**Why FRAME asked anyway:** the style was documented as code and a handoff doc, but never saved as a FRAME style. Separately, `PLAN.md` §4 wrongly listed only FRAME's three generic style sources. Both are fixed: `style-higgsfield-v3.json` is that style in FRAME's `frame-style/1` format, and FRAME's own `quick_style.validate()` accepts it (checked 2026-11-10).

It's your own style, so it's allowed. The "don't replicate style" rule applies to Higgsfield's references, not to your edits.

## The style
| Area | v3 rule | Source |
|---|---|---|
| Dialogue | Cut on measured speech energy, not ASR times. Keep 50 ms before onset and 80 ms after the decay tail, 0–100 ms room-tone gaps; never time-stretch; takes level-matched within ±0.9 dB | hf_render_v3.py:13; C2, C4 |
| Captions | 66 px Heavy white, upper-case; about 1 emphasis word per chunk at 74 px Black in **#E2FD56**; 2 px stroke and soft shadow; 22 px slide-up over 0.12 s | hf_render_v3.py:38–66 |
| Caption placement | y 1220/1920 full-frame, 960 on a split seam, 1060 above a CTA card. Skipped when a card or result carries the line; never carried across a scene cut | hf_render_v3.py:36, 58, 62; C5 |
| Layouts | Split (media over speaker); full-screen card when a plan or list is spoken (all rows readable within 0.35 s); full-frame screen captures with slow camera moves and a lime highlight ring on the thing being tapped; full-frame result with provenance labels; speaker full-frame with a slow push-in (1.00→1.07) | hf_render_v3.py:83–137 |
| CTA | Card with "COMMENT" + keyword in lime + offer subline, landing on the spoken word; about 1.15 s end hold | hf_render_v2.py:135 (`cta_panel`); v3 EDL |
| Sound | Owned synthesized 120 bpm bed: kick and pumping bass from the start, hats from the proof, backbeat from the card, 16th arpeggio through the demo, drop and riser before the payoff, impact and resolving stab on it. SFX only on real events (card lands, taps, typing, reveal, CTA). 12 dB duck with fast attack | hf_mix_v3.py |
| Master | −14 LUFS, −1.5 dBTP; voice at least 12 dB over the bed on speech frames | C1, C4 |
| Process | Clause → visual map before choosing footage; provenance labels on anything not yours; numeric QC gate before delivery | HANDOFF.md §1 |

## What FRAME applies from it today vs what needs the compositor
| FRAME applies (`style-higgsfield-v3.json`) | Needs the v3 compositor, or tagged images in swarm |
|---|---|
| 9:16 cover frame | Split layout, full-screen cards, screen-capture pans with highlight rings |
| Pause and retake removal (approximation: FRAME pads ASR word times, so it won't match v3's energy-snapped cuts exactly) | Category labels on the showcase clips, offer text card, CTA card |
| Caption grouping, position, size, colors, case | Keyword emphasis and the slide-up animation (FRAME exports plain white/colored text; fonts and animated styles are preview-only) |
| — | Music bed, event SFX, ducking, −14 LUFS master |

**Font:** v3 used SF Pro Heavy/Black. FRAME only offers Inter, Space Grotesk, Bebas, Marker and Fraunces, so the JSON uses Inter Black as the nearest match. That's marked `user_set`, pending your OK.

## How it maps onto this brief's beats
| Beat | v3 treatment |
|---|---|
| Hook (mandated reaction) | Speaker full-frame, so the reaction reads; editorial captions |
| Showcase | Full-frame media-kit clips, each with its category name on screen as it's spoken (required by the brief), drawn in the v3 label style |
| Offer | Full-screen card with the mandated offer text, landing on the line, like the v3 workflow card |
| Setup | Full-frame screen recording, slow moves, lime ring on each tap, loading cut |
| CTA | v3 CTA card: "COMMENT FABLE" + "3 days free & unlimited" + short hold |
