# Test blueprint v0.2

| Stage | Function | Main response | Follow-up | Support |
|---|---|---:|---:|---|
| Calibration | Verify microphone, audibility, and usable transcript | 30 s | Repeat once only if unusable | Not scored |
| A1 | Familiar personal information/routine | 15-45 s | 8-30 s direct question | 5 s preparation; one repeat or clarification |
| A2 | Predictable transaction with one changed condition | 25-60 s | 12-45 s adaptation | 5 s preparation; one repeat or clarification |
| B1 | Connected experience/problem/solution | 40-100 s | 20-60 s reflection or future action | 10 s preparation; one repeat or clarification |
| B2 | Compare, justify, and answer a counterargument | 55-120 s | 30-75 s qualification | 15 s preparation; one repeat or clarification |

Every learner starts with calibration and A1. The production LLM cannot create
or rewrite questions. Approved clarification text comes from item bank 0.2.0,
and support use is stored with the eventual response.

Each level normally uses the main and follow-up from one fixed item. If their
combined evidence does not establish the boundary, the learner receives the
fixed same-level boundary item from another domain. Passing it advances; a
borderline or failed boundary item stops the adaptive test. This adds at most
one task at an uncertain level.

The A2 appointment item was revised after pilot ambiguity. It now fixes the
service (haircut), day (Monday), and unavailable time (four o'clock), so failure
to guess the intended scenario cannot masquerade as low English ability.

Invalid audio is repeated without penalty. Two unusable attempts stop with
`Not determined` if nothing was confirmed, or preserve earlier confirmed
evidence with low confidence.

There is no pronunciation read-aloud task inside this placement. Spontaneous
speech supplies conversational intelligibility evidence. Detailed phoneme
alignment belongs in an optional, separate known-reference pronunciation
activity and cannot mathematically change the conversational placement.
