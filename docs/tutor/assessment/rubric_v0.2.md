# Conversational rubric v0.2

The construct is a **CEFR-aligned Conversational Interaction Placement**, not a
global English level or official CEFR examination.

| Dimension | Weight | Evidence |
|---|---:|---|
| Task achievement and relevance | 25% | Central communicative goal and relevant content |
| Interactive communication | 20% | Understanding, appropriate reaction, follow-up handling, support needed |
| Fluency | 20% | Maintaining meaningful speech despite hesitation; disruptive pauses and abandoned turns |
| Coherence and discourse | 15% | Sequence, explanation, comparison, reasons, and qualification expected at the target level |
| Lexical adequacy | 10% | Enough vocabulary to express the target function |
| Intelligibility | 10% | Listener effort and repair, not accent removal |

Each dimension is scored from 0 to 4. A score of 3 means the supplied response
meets the current target-level task; 4 exceeds it; 2 is partial; 1 is far below;
0 supplies no usable evidence.

The per-response weighted score is:

`0.25T + 0.20I + 0.20F + 0.15C + 0.10L + 0.10P`

A response passes when its weighted score is at least 2.8, task achievement and
interaction are at least 3, intelligibility is at least 2, the central task is
achieved, meaning is recoverable, and audio is usable. A weighted score from
2.4 to 2.799, or a small critical-dimension miss, is borderline.

## Level anchors

- **A1:** simple familiar statements and direct answers can meet the level.
  Repetition, rephrasing, and support are compatible with A1. Connected
  narration is not required.
- **A2:** short, structured, predictable exchanges can meet the level with some
  help. Formulaic but appropriate requests, questions, choices, and
  confirmations are valid evidence; an elaborate monologue is not required.
- **B1:** the learner communicates with some confidence on familiar routine and
  non-routine matters, connects a sequence, and explains a reason, result, or
  advice with limited help.
- **B2:** the learner sustains a comparison or position, explains trade-offs,
  and responds spontaneously to a counterargument without significant strain.

## Safeguards against false low scores

- Required evidence is a blueprint, not a word-for-word script. Missing one
  non-central detail should normally produce partial/borderline task evidence,
  not a complete failure when the central communicative purpose was achieved.
- One permitted repetition or approved clarification is compatible with A1/A2.
- Obvious ASR substitutions and homophones are not learner errors when intended
  meaning is recoverable from context.
- Short answers are evidence insufficiency, not automatic failure.
- Interaction on a main response is judged from whether the learner understood
  and responded appropriately to that part of the exchange; the evaluator must
  not require evidence from the later follow-up.

## Stage adjudication

Main and follow-up remain separately scored and auditable, but the stage is
also judged from their combined evidence. A mixed pair may pass when the
average weighted and critical evidence clearly meets the target and both tasks
are relevant, achieved, and understandable. Otherwise the service administers
a different same-level boundary task before stopping.

Grammar is not an independent score. It affects task achievement or
intelligibility only when its communicative consequence blocks meaning or
prevents task completion. Words per minute, ASR confidence, and phoneme-error
rate are supporting or validity evidence only and can never assign a level.

The numeric `confidence_score` is an evidence-sufficiency index, not a
probability. It is capped below 100 until human pilot calibration and agreement
evidence justify a stronger interpretation.
