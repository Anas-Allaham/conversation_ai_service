# Changelog

## 0.6.0 - 2026-08-09

Guided-conversation UX, evidence debugging, and clean room lifecycle.

- Added a domain-first catalog and grouped both A1 ordering scenarios under the
  `Restaurant` domain; added `GET /v1/guided-conversations/domains`.
- Kept the complete tutor/learner history visible while separately displaying the next
  exact learner line.
- Added ephemeral per-word STT recognition-confidence feedback: below 25% red, 25% to
  below 75% orange, and 75% or above white. It is explicitly not a pronunciation score.
- Added persisted pause/resume controls that restore the exact prior guided state.
- Added browser-side full-conversation replay after completion without keeping the
  LiveKit session open.
- Added guided-specific short-line evidence gates while preserving free-conversation
  and assessment thresholds.
- Added `result_debug` thresholds and per-line eligibility diagnostics to every guided
  report, plus a deterministic replay script.
- Fixed the completed-session loop: the final line now closes the per-room agent session,
  disconnects it from LiveKit, and ignores late STT instead of repeatedly saying the
  conversation is inactive. The shared worker process remains ready for future rooms.
- Added domain, short-line, pause/resume, word-color, and terminal-state regressions. The
  backend suite now contains 75 passing tests.

## 0.5.0 - 2026-08-09

Two-practice-mode contract and runnable guided test flow.

- Reduced the public practice-mode enum to exactly `free | guided`; placement assessment remains
  a separate flow and the former `scripted` value is rejected.
- Renamed the 0.4.0 scripted scenario package, routes, types, topics, IDs, reports, content
  versions, examples, and documentation to guided conversation terminology.
- Routed `guided` exclusively to the deterministic fixed-scenario engine and `free` exclusively
  to the dynamic LLM tutor; removed the former open-ended guided behavior.
- Added `POST /v1/practice-sessions` to issue short-lived participant tokens and explicitly
  dispatch `english-tutor` with trusted LiveKit job metadata.
- Added a unified practice-result endpoint for guided and free output.
- Added a ready-to-run browser demo with level/scenario selection, microphone connection,
  fixed lines, LiveKit controls, and learner-safe report rendering.
- Added practice-mode rejection, routing, token-contract, free-result, and guided-result
  regressions. The backend suite now contains 71 passing tests.

## 0.4.0 - 2026-08-09

Deterministic, level-gated scripted conversation MVP (renamed to guided in 0.5.0).

- Added versioned Café A1, Restaurant A1, and Restaurant B1 scenarios with visible locks,
  server-enforced placement access, exact learner lines, fixed system lines, and no branching.
- Added a persisted scripted-session state machine with idempotent attempts, retry selection,
  continue/stop controls, normal and slow replay, confidence capture, and derived reporting.
- Reused `fluency-v0.1` in isolated `scripted` mode and labeled its result scripted-speaking/
  oral-reading fluency. Scripted reports cannot return CEFR and cannot change placement.
- Added optional low-completeness retry suggestions without using ASR equality as a gate or
  pronunciation judgment.
- Added consent-gated encrypted raw-audio capture plus non-blocking pronunciation job and
  callback contracts. A failed or pending pronunciation worker never blocks progression.
- Added a dedicated LiveKit scripted runtime under the existing `english-tutor` identity.
  Its local disabled adapter satisfies LiveKit scheduling but has no provider or network path.
- Added SQLite/PostgreSQL migrations, authenticated API routes, OpenAPI/frontend integration
  contracts, scenario validation, and ten access/state/idempotency/privacy/storage regressions.
- Restored the item-bank JSON and schemas omitted from the supplied 0.3.0 archive, making the
  full project independently runnable and preserving the revised A2 appointment task.

## 0.3.0 - 2026-08-08

Shared explainable fluency MVP.

- Generalized assessment `speech_metrics.py` into the reusable `services/fluency`
  package used by controlled assessment, guided conversation, and free conversation.
- Added versioned `fluency-v0.1` speed, breakdown, continuity, and repair features,
  deterministic weights, eligibility gates, evidence confidence, and feedback.
- Preserved real wall-clock gaps when Flux splits one assessment answer into several
  committed fragments; removed the artificial pause from production timing evidence.
- Added non-blocking Flux timestamp capture to the normal tutor and backend-selected
  guided/free mode routing through LiveKit room metadata.
- Added authenticated rolling fluency-session endpoints and persisted derived results
  without storing transcripts or audio in the fluency table.
- Made `fluency-v0.1` authoritative for the assessment fluency dimension when sufficient
  timestamp evidence exists. A clearly flagged evaluator fallback remains for missing
  timing evidence so other assessment dimensions are not discarded.
- Added learner-safe result fields: fluency index, confidence, evidence count, feedback,
  and scorer version. CEFR fluency labels appear only in controlled assessment results.
- Corrected the Gemini Developer API default from `v1` to `v1beta`.

## 0.2.1 - 2026-08-07

Provider-quota and repeated-prompt correction based on the supplied nearby-place session.

- Fixed the exact regression where a Gemini-side 404 was represented by the service as
  HTTP 503 with `retryable=false`, after which the voice adapter incorrectly recovered by
  speaking the same assessment prompt again.
- All evaluator-side 5xx responses now preserve the exact response and pause scoring;
  only a genuine assessment-state HTTP 409 can trigger state synchronization.
- Removed the assessment client's immediate duplicate POST when the service supplies a
  `Retry-After` value. One learner response no longer multiplies into several evaluator calls.
- Disabled the Google SDK's generic immediate retries and added bounded handling for Google's
  explicit `RetryInfo.retryDelay`, including a distinct daily-quota category.
- Added non-generation Gemini key/model validation to service readiness. This release
  forced `v1`; release 0.3.0 corrected the Developer API default to `v1beta`.
- Migrated the old default `gemini-2.5-flash` setting to the lower-cost
  `gemini-2.5-flash-lite` during a 0.2.0-to-0.2.1 local upgrade.
- Increased assessment-only Deepgram TTS timeout/retries without changing the original
  `voice_agent.py`.
- Added five provider/recovery regression tests. The suite now contains 48 passing tests.

## 0.2.0 - 2026-08-07

Reliability redesign after the A1 under-placement and evaluator HTTP 503 pilot failures.

- Verified by SHA-256 that the original Phase 3 `voice_agent.py` remains byte-for-byte
  identical to the attached source and recovered 0.1.1 release.
- Removed the 0.1.3 A1-to-A2 recovery exception. An unclear stage now receives one
  different task at the same level before the boundary is closed.
- Added stage-level adjudication across main and follow-up evidence, while retaining
  per-response scores and evidence for audit.
- Added explicit CEFR-aligned A1-A2-B1-B2 evaluator anchors. One allowed clarification,
  a recoverable ASR substitution, or one missing non-central role-play detail can no
  longer force an automatic fail.
- Rewrote the ambiguous A2 phone-appointment item with a fixed service, day, unavailable
  time, and clearer role instructions; published item bank 0.2.0.
- Applied Google Gen AI SDK request timeouts and exponential backoff for 408, 429, and
  retryable 5xx responses. The adapter request timeout now exceeds the evaluator's full
  retry budget.
- Preserved failed scoring submissions by response/idempotency key. The learner can say
  `continue` to retry the saved answer without speaking again or restarting LiveKit.
- Exposed stable evaluator error categories and `Retry-After`, persisted evaluator-failure
  counts, and added an authenticated evidence endpoint for backend audit.
- Capped the uncalibrated evidence-confidence index below 100 and added validity warnings.
- Added regressions from the supplied morning-routine and appointment sessions plus a
  complete 503-to-idempotent-recovery test. The suite now contains 43 passing tests.

## 0.1.3 - 2026-08-07

Learner-facing assessment and state-synchronization correction.

- Kept exact A1-A2-B1-B2 state and adaptive progress metadata in the API while
  removing all spoken section announcements from the assessment worker.
- Added an A2 adjacent-band verification after an unconfirmed A1 stage, so two
  weak or misrecognized A1 answers cannot immediately produce an overconfident
  Pre-A1 placement. An A2 pass can recover the initial false negative.
- Capped evidence confidence by the number of valid scored observations; a
  short lower-bound assessment can no longer report 100/100 confidence.
- Replaced the spoken full-report dump with a concise announcement containing
  only conversational level, confidence label, and fluency level. The API still
  returns the complete profile, percentages, boundary, and statistics.
- Removed the controlled read-aloud sentence from the level-assessment flow.
  Detailed phoneme diagnostics are deferred to a separate optional pronunciation
  experience; spontaneous answers continue to provide intelligibility evidence.
- Added a four-second response collector that merges multiple committed Flux
  fragments into one submission, including the reported three-part bus-station
  answer.
- Added backend-state recovery for stale-prompt HTTP 409 responses. The learner
  is returned to the current prompt instead of being told to restart the room.
- Added two service progression regressions and five voice-contract, fragment,
  and state-recovery regressions; the suite now contains 37 passing tests.

## 0.1.2 - 2026-08-06

Conversation-safety and integration update based on two real learner sessions.

- Treat repeat, clarification, and thinking-time requests as control turns rather
  than scoring them as answers.
- Added approved, versioned clarification text to item bank 0.1.1.
- Moved the controlled read-aloud sample before A1 and accumulated slow fragments
  until an explicit `done`, preventing premature completion and HTTP 409.
- Added optional preparation windows: five seconds for A1/A2, ten for B1,
  fifteen for B2, and three for follow-ups.
- Added adaptive progress metadata to create, state, and response contracts.
- Expanded final results with an evidence-confidence score, profile evidence
  percentages, next-level boundary, summary, and backend statistics.
- Added an immediate spoken acknowledgement while rubric evaluation runs.
- Added six regression tests for the observed clarification/read-aloud failures
  and the new integration contract.

## 0.1.1 - 2026-08-06

Assessment reliability patch based on the first complete learner voice test.

- Fixed HTTP 422 responses caused by LiveKit `TimedString` entries being read
  through the obsolete `.word`/`.start`/`.end` shape.
- Added a second API-boundary normalizer so blank provider word rows cannot
  abort a turn even if an adapter regresses.
- Increased assessment-only Flux and LiveKit endpointing patience to keep
  deliberate A1-B2 answers together across thinking pauses. The normal
  `english-tutor` agent remains unchanged.
- Split validation/state errors from true service-unavailable errors and added
  an invalid-audio recovery submission that repeats the same fixed prompt
  without proficiency penalty.
- Corrected Gemini structured-output configuration for the Google Gen AI SDK.
- Added automatic local token/Fernet-key generation and assessor preflight.
- Removed duplicate readiness messages for the same missing encryption key.
- Renamed the pytest-collected `test_settings` helper.
- Added seven regression tests for provider word shapes, endpointing,
  API-boundary normalization, and Gemini configuration.

## 0.1.0 - 2026-08-05

Initial A1-B2 adaptive oral-placement MVP.
