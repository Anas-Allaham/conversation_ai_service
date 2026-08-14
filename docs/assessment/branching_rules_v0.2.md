# Branching rules v0.2

Every level begins with one fixed main item and its predefined follow-up. The
two responses are scored separately, then adjudicated together.

## Normal stage

1. Two clear response passes -> pass the stage.
2. Combined weighted and critical evidence meets the target, with both tasks
   relevant, achieved, and understandable -> pass the stage.
3. Any other usable but unclear combination -> ask the fixed boundary item for
   the same level.
4. A pair that is clearly irrelevant or meaning-blocked -> also ask the
   different same-level boundary item before stopping.

The same-level boundary item is deliberately from a different prompt family.
This prevents misunderstanding one role-play, topic, or ASR rendering from
becoming the only basis for a low placement.

## Boundary item

- Pass -> confirm that level and advance.
- Borderline or fail -> stop at the first unconfirmed level.
- Invalid audio -> repeat without penalty under the existing invalid-audio
  policy.

Only one boundary item is administered at each level. The earlier 0.1.3 rule
that sent an A1 failure directly to A2 has been removed. A higher-level task is
not a valid substitute for establishing the lower boundary.

The final placement is the highest level reliably passed. If no level is
confirmed, the result is Pre-A1 only when usable evidence genuinely fails A1;
unusable audio produces `Not determined`. A B2 pass reports the assessment
ceiling (`B2 or above within the tested range`).

The LLM returns six rubric scores, flags, and evidence. Application code owns
the per-response decision, stage adjudication, boundary selection, confidence,
and final level.
