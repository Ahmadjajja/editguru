# Fable 5.2 × Higgsfield MCP reel: production plan (FRAME)

Status 2026-11-10: brief captured, requirements extracted, plan drafted. **No footage recorded, nothing downloaded, nothing generated.**

Inputs: `REQUIREMENTS.md` (what Higgsfield needs) and `CRAFT-LOGIC.md` (how ChatGPT Mastery was made). The style is new and yours. Nothing visual is taken from the references.

## 1. Gates (from the ChatGPT Mastery logic: each stage approved before the next spends anything)
| Gate | Passes when | Owner |
|---|---|---|
| G1 Brief | Open points in REQUIREMENTS §C answered (offer window, "new users" wording, UTM link) | Dante + Higgsfield contact |
| G2 Script | Section 2 lines locked; mandated lines word-for-word | Dante |
| G3 Style source | Higgsfield v3 style confirmed (§4); font substitute OK'd | Dante |
| G4 Footage | All shots in §3 recorded and run through intake (hash, probe, sheet) | Dante records; intake logs |
| G5 First cut | First assembly in FRAME reviewed with section pins | Dante |
| G6 Compliance | Every row A1–A14 checked against the export (§6) | checklist |
| G7 Post | Caption, UTM automation, visibility settings done | Dante |

## 2. Script draft (beat order fixed by the brief)
Mandated lines are word-for-word from the brief. Drafted lines are placeholders in your voice: change them freely, but keep the facts.

| Beat | Target | Voiceover | On screen (required content only) | Status |
|---|---|---|---|---|
| 1 Hook | 0–5 s | "Anthropic just released Fable 5.2 and Mythos 5.2, and you no longer need to pay for generating AI videos." | Your reaction: eyes on screen → wide-eyed → hands to mouth → line | **Mandated** (A2, A3) |
| 2 Showcase | 5–13 s | "You can now create commercials, cinematic videos, UGC-style content, anime, and more — all through Claude." | 4–5 media-kit clips, about 1.5 s each, each category's name on screen while its clip plays | Draft, built on the brief's example (A4). Only name categories the kit actually shows. |
| 3 Offer | 13–19 s | "Just connect Higgsfield MCP to Claude with Fable 5.2, you'll get 3 days of free, unlimited access to all video models available through Higgsfield MCP." | "All video models on Higgsfield MCP · Free & unlimited for 3 days ·" | **Mandated** (A5, A6) |
| 4 Setup | 19–30 s | "Open Claude, go to Settings, then Connectors, and add Higgsfield. Then just ask for a video, and open it right in your chat." | Your screen recording: connect → type a request → open the real result. Loading and waits cut. | Draft (A7). Wording is yours; the steps must match what's actually on screen. |
| 5 CTA | 30–34 s | "Comment 'FABLE' and I'll send you the setup link." plus a short offer reminder ("3 days, free and unlimited") | Keyword FABLE + 3-day free unlimited reminder | **Mandated** line (A8); reminder wording pending REQUIREMENTS §C.2 |

Estimated total: about 34 s, inside the 30–60 s window (A10). Measure real timing after recording; these targets are plans, not measurements.

## 3. What you need to record (your own footage)
1. **Hook reaction, 3–5 takes.** Look at your screen, react wide-eyed, hands to mouth, then the exact hook line to camera. Several takes, because the reaction has to read in under 2 s.
2. **Offer line** to camera (or as voiceover, your choice). Word-for-word.
3. **CTA line** to camera. Word-for-word.
4. **Showcase voiceover**, recorded clean so it can sit under the clips.
5. **Setup screen recording** of the real flow: Claude → Settings → Connectors → add Higgsfield (`https://mcp.higgsfield.ai/mcp`) → allow → new chat → type a video request → open the generated result. The result must be a **real** generation from that request. Phone or desktop is your call (REQUIREMENTS §C.3).

## 4. Style: your Higgsfield v3 Discovery edit
The style source is **your own accepted Higgsfield v3 edit** from the zenzap-ad chat. It's in `specifications/STYLE-HIGGSFIELD-V3.md`, and `specifications/style-higgsfield-v3.json` is the same style in FRAME's format (validated by FRAME's own `quick_style.validate()`).

FRAME applies the frame, pacing and caption parts. The layouts, cards, labels and sound come from the v3 compositor; the full split is in that doc.

(Correction 2026-11-10: this section first listed only FRAME's generic sources: starter, measure a reference, hand-tune. That's why FRAME asked which style to use.)

## 5. How it runs in FRAME
| Step | FRAME surface | Logged to |
|---|---|---|
| Import footage | `/swarm` *Upload footage*, or Frame MCP `import_local_video` | `inventory.json` via `tools/intake.py` (hash and probe first) |
| Words | *Transcribe* (local faster-whisper) or paste the script | `METHODOLOGY.md` timeline section |
| Tighten pacing | Swarmcut word-timing pauses or `tighten_pacing`. Measure first: thresholds from ChatGPT Mastery don't apply to your voice (CRAFT-LOGIC §3) | decision ledger, with the measured values |
| Showcase images/clips | *Add images*, triggered on the spoken category words | decision ledger (which clip, which word) |
| Assemble | *Assemble with style* (deterministic plan with a digest) | plan digest recorded |
| Review | Section pins at source time → revision set → checklist → new version | `history/` + per-version folder |
| Export | FFmpeg export; keep each version | verification log |

**Disk:** the Mac has about 5 GB free. Download only the media-kit clips you'll use (likely 4–5, roughly 100–250 MB), not the whole 830 MB kit.

## 6. Compliance check before posting (G6)
For every requirement A1–A14 in REQUIREMENTS.md, record pass/fail with a timestamp or screenshot from the export:
- **Mandated lines:** checked word-for-word against a re-transcription.
- **Category names:** each on screen while its clip plays.
- **Offer text:** visible.
- **FABLE keyword:** on screen.
- **Length:** 30–60 s.
- **Clips:** media-kit clips checked for third-party characters and logos.
