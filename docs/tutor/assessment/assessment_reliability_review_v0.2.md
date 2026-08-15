# Assessment reliability review v0.2

Date: 7 August 2026

## Scope

This review covers the reported A1 under-placement, the later HTTP 503 failure,
the original project decisions, the Phase 1-3 conversation report, the
pronunciation research report, release 0.1.3, and the supplied learner-session
screenshots.

The original normal tutor is not the source of these regressions. The attached
`voice_agent.py`, recovered 0.1.1 file, and 0.1.3 file have the same SHA-256:

`f3ce3c205dac407ed891e43da9850b75ae08d5656faf1f8872943a3f3c004fd6`

All affected behavior belongs to the separate assessment agent and oral
assessment service.

## Finding 1: the A1 result was not adequately supported

The morning-routine learner supplied multiple familiar actions and then gave a
direct preference with reasons and connected explanation. That is clear A1
evidence and contains features beyond minimal A1 phrases. Those two answers do
not prove A2 or B1 by themselves, but they make an A1-only final placement
dependent on reliable evidence at the A2 boundary.

The later A2 appointment prompt was an unreliable boundary item in practice:

- the service type was unspecified;
- the learner had to infer the role-play frame;
- the voice agent did not act as the other participant;
- missing one requested detail could turn task achievement into a complete
  response failure;
- main and follow-up shared the same misunderstanding, so they were not truly
  independent observations.

Release 0.1.3 then used A2 as a recovery route after A1 failure. That was also
conceptually weak: a higher-level task should not replace a distinct check of
the lower-level boundary.

The Council of Europe describes A1 as simple interaction on familiar matters
with repetition/rephrasing and A2 as short, structured, predictable everyday
exchange with help when necessary. The old evaluator could require too much
from a single A1/A2 turn because every isolated response had to clear the same
interaction threshold. Relevant official descriptors are in the [CEFR
Companion Volume 2020](https://rm.coe.int/common-european-framework-of-reference-for-languages-learning-teaching/16809ea0d4),
especially Overall Oral Interaction on pages 71-72.

### Correction

- Main and follow-up are separately stored but adjudicated together.
- Any unclear stage receives a different same-level boundary task.
- The A1-to-A2 recovery exception is removed.
- Level-specific evaluator anchors prevent A1/A2 from being judged against
  connected-narrative expectations.
- One allowed clarification, one missing non-central detail, or a recoverable
  ASR substitution cannot independently force a fail.
- The appointment item now fixes the service, day, and changed time.

## Finding 2: `503` was evaluator unavailability, not lost session state

The service returned HTTP 503 whenever Gemini failed after its short retry
loop, but it hid the underlying category. The main defects were:

- the configured evaluator timeout was not passed to the Google Gen AI client;
- retries waited only fractions of a second instead of exponential backoff;
- the assessment HTTP client could time out before the evaluator's intended
  retry budget;
- all provider errors became the same generic spoken service failure;
- the learner's response was not retained by the voice adapter for a later
  retry;
- evaluator-failure counts were incremented in memory but not persisted before
  the exception returned.

Google's official troubleshooting guide identifies 429 and 503 as retryable
and recommends exponential backoff: [Gemini API troubleshooting](https://ai.google.dev/gemini-api/docs/troubleshooting#retry-strategy).
The current Google Gen AI SDK exposes request timeout and HTTP retry settings:
[Google Gen AI Python SDK](https://googleapis.github.io/python-genai/).

### Correction

- Gemini receives a real per-attempt timeout.
- The SDK retries 408, 429, 500, 502, 503, and 504 with exponential backoff and
  jitter.
- The assessment client's timeout exceeds the evaluator's full retry budget
  and respects `Retry-After`.
- Provider HTTP errors do not open the network circuit breaker.
- Stable error categories (`provider_overloaded`, `provider_rate_limited`,
  `invalid_structured_output`, and others) are returned and logged without
  exposing secrets or transcripts.
- The exact response and idempotency key remain in the adapter. If scoring is
  still unavailable, the learner says `continue`; the same answer is retried
  and can safely replay if the first request completed late.

## Finding 3: the score thresholds were engineering defaults, not validated cut scores

The 2.8 pass and 2.4 borderline thresholds are internally consistent with the
project's original decisions, but they are not official CEFR cut scores. The
same applies to word-count targets, pause thresholds, and the numeric
confidence index.

The 2026 ALTE manual emphasizes construct definition, validity evidence,
fairness, marking reliability, monitoring, and continuing revision. It also
states that automated scoring needs quality checks and that all test takers
need an equal opportunity to demonstrate ability. See the [ALTE Manual for
Language Test Development and Examining (2026)](https://www.alte.org/resources/Documents/ALTE_MLTDE_FINAL_30072026.pdf),
especially chapters 1, 2, 3, and Appendix I.

### Correction and limitation

- The thresholds remain provisional for the MVP.
- The confidence index is capped below 100 and explicitly described as
  evidence sufficiency, not probability.
- Backend results include validity warnings and an authenticated evidence
  endpoint for item-by-item review.
- Production claims must remain “CEFR-aligned conversational interaction
  placement estimate.”
- Before committee or product claims, the team still needs blinded human
  ratings, inter-rater agreement, confusion matrices at A1/A2/B1/B2 boundaries,
  item-level failure analysis, and threshold calibration on the target Arabic-
  speaking population.

## Finding 4: pronunciation must remain separate

The graduation-project pronunciation report focuses on phoneme-level diagnosis,
G2P, recognizer/alignment methods, GOP, and Arabic-speaker confusion patterns.
Those outputs are valuable but are not the same construct as conversational
interaction or fluency. Spontaneous speech can support intelligibility evidence;
detailed phoneme error analysis needs known reference speech in a separate
optional activity. No pronunciation percentage or ASR confidence is averaged
into the conversational placement.

## Verification added

Release 0.2.0 contains regressions for:

- the exact morning-routine evidence continuing beyond A1;
- the ambiguous appointment pair receiving a different A2 boundary task;
- service-level 503 preserving the current prompt;
- retrying the same response/idempotency key after evaluator recovery;
- voice-adapter retention of a deferred answer;
- fragmented multi-sentence answers;
- clarification and control turns;
- empty LiveKit word rows;
- stale-prompt recovery;
- deterministic branching and result contracts.

Passing unit tests demonstrate software behavior, not psychometric validity.
The remaining validation work is documented in
`validation_report_v0.1.md` and the pilot templates.
