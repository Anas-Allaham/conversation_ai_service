# Branching rules v0.1

| Main | Follow-up | Stage result |
|---|---|---|
| Pass | Pass | Pass stage |
| Pass | Borderline | Tie-breaker |
| Pass | Fail | Tie-breaker |
| Borderline | Pass | Tie-breaker |
| Borderline | Borderline | Tie-breaker |
| Borderline | Fail | Fail stage |
| Fail | Pass | Tie-breaker |
| Fail | Borderline | Fail stage |
| Fail | Fail | Fail stage |

The tie-breaker confirms the stage only with a pass. A borderline or failed tie-breaker stops the assessment. Invalid audio never enters this matrix; it is repeated first.

The highest passed stage is the confirmed level. The failed stage becomes the first
unconfirmed level. One early-boundary exception prevents premature Pre-A1 placement:
if A1 is not confirmed, A2 is administered as adjacent-band verification. If A2 is
demonstrated, A1 is treated as a false negative and A2 becomes confirmed; if A2 is
also unconfirmed, A1 remains the first unconfirmed level. B2 pass has no first
unconfirmed level and sets `ceiling_reached=true`. The LLM supplies six rubric numbers
and evidence only; application code calculates every response decision, stage decision,
confidence label, and final level.
