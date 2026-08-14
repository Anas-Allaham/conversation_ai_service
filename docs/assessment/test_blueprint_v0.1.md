# Test blueprint v0.1

| Stage | Function | Main response | Follow-up | Support |
|---|---|---:|---:|---|
| Calibration | Verify microphone, audibility, and usable transcript | 30 s | Repeat once only if unusable | No proficiency score |
| A1 | Familiar personal information/routine | 15-45 s | 8-30 s direct question | 5 s preparation; one repeat or approved clarification |
| A2 | Predictable transaction with one changed condition | 25-60 s | 12-45 s adaptation | 5 s preparation; one repeat or approved clarification |
| B1 | Connected experience/problem/solution | 40-100 s | 20-60 s reflection or future action | 10 s preparation; one repeat or approved clarification |
| B2 | Compare, justify, and respond to counterargument | 55-120 s | 30-75 s qualification | 15 s preparation; one repeat or approved clarification |

Every learner starts with calibration and A1. Every scored level requires a main
response plus its predefined follow-up. The production model cannot change question
text. If the learner asks for help, the adapter may use only the approved clarification
stored with that item and records the support count. A conflicting pair requests the
fixed tie-breaker. A failed stage normally stops the conversational placement. The
one early-boundary safeguard is that an unconfirmed A1 stage is followed by A2 as
adjacent-band verification before a Pre-A1 result is allowed. An A2 pass recovers the
initial false negative and advances to B1. Passing B2 reports “B2 or above - ceiling
reached,” because C1 is not assessed.

Invalid audio is repeated without penalty. Two unusable attempts stop the assessment with “Not determined” if no earlier stage was confirmed, or preserve the earlier confirmed level with low confidence.

There is no pronunciation read-aloud branch inside the level test. Spontaneous
responses provide conversational intelligibility evidence. Detailed phoneme feedback
is an optional separate activity with its own known-reference speech and cannot change
the conversational placement mathematically.
