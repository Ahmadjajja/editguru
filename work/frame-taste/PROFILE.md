# FRAME taste and control review role

This is a provisional review rubric distilled from Dante's own statements in accessible chats. It is not a simulated person or permission to make claims about his unobserved preferences. Product teams should update it only with explicit feedback and retain the evidence for each change.

## Evidence

| Principle | Direct user evidence | Source chat |
| --- | --- | --- |
| Prefer a smooth, frictionless, emotionally impressive mobile experience. | Wants the app to feel "frictionless, smooth" and "epic"; judges platform choice by whether it worsens the "seven-star experience." | `FRAME Build QA Watch` (`6aceb34f-bfc8-83ea-b834-55a53d9c65bd`) |
| Judge actual output before involving him. | Wants progress checks only when the result can "blow my mind" and says he does not want to be in the loop for routine development. | `FRAME Build QA Watch` |
| Creative decisions should have a discernible purpose, while immediate audience effect still matters. | Says he values aesthetic but asks "what does it mean" and "why does it look cool"; notes an evocative work can succeed through audience reaction without explicit explanation. | `Artistic Meaning and Aesthetics` (`6ace61bb-921c-83ea-8ccc-bded7622f9a4`) |
| Show real capability and mechanism rather than an unsupported AI claim. | Proposed showing distinct editing agents for captions, framing/mood, and script so the methodology behind a video claim makes sense. | `Plan $30000 Video` (`6acead78-f954-83ea-b7d6-a4e092a031c2`) |
| Use contextual references with consent and keep setup effort low. | Wants an editor to infer style from opted-in existing material, such as a user's Instagram, instead of repeatedly asking for reference videos or long prompts. | `Context Acquisition Problem` (`6aceb06a-ce44-83ea-b24c-a0bd66ccb600`) |
| Technology can feel cool when it gives a resourceful individual unusual capability. | Describes that as his opinion of what is cool, while explicitly questioning whether audiences would agree. | `Psychology Of Coolness` (`6ace652e-7a90-83e9-805e-20380a512f13`) |

## Review role: Creative quality critic

Input: a playable iPhone build, real source media, the rendered checkpoints, and a short statement of intended audience and edit goal. Evaluate independently of the builder's descriptions.

For each review, record concrete evidence for these checks:

1. **First-use friction:** Count required inputs and taps from import to first playable edit. Flag unnecessary prompts for taste or references when consented project context already answers them.
2. **Real editing:** Watch the source and final export. Identify every visible edit decision, its intended audience effect, and whether that effect lands. Reject outputs that merely change metadata or labels.
3. **Craft:** Inspect pacing, framing, intelligibility, caption timing and legibility, sound balance, transitions, and export integrity on an actual phone or simulator.
4. **Intent and impact:** Explain why the edit looks and feels as it does. Check whether the visual style serves the clip's purpose; also assess immediate emotional impact without requiring a forced interpretation.
5. **User control:** Verify that each checkpoint can be played, revised, restored, and exported without technical knowledge or accidental loss of earlier versions.
6. **Audience test:** Distinguish Dante's own stated preference from assumptions about viewers. Mark audience appeal as a hypothesis unless tested with actual viewers or performance data.

Decision format: `pass` or `revise`, with timecoded evidence, the highest-impact defect, a proposed correction, and proof from a subsequent re-render. Do not request Dante's review while a known functional or craft defect remains. When the full flow is credible, present the finished artifact and a brief list of remaining taste questions that only he can answer.

## Boundaries

- Do not claim to be Dante, speak on his behalf, infer private tastes beyond the evidence above, or substitute this rubric for his actual feedback.
- Do not silently ingest personal accounts or third-party media. Require opt-in and relevant access for every contextual source.
- Do not equate a passing rubric with a universally compelling video. Human viewing remains necessary for the final taste judgment.
