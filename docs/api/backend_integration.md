# Backend integration guide

Base URL defaults to `http://127.0.0.1:8080`. Send `Authorization: Bearer <ASSESSMENT_SERVICE_TOKEN>` and an optional `X-Correlation-ID` on every `/v1` request. Never expose this service token to a public browser; the application backend calls the service.

## Flow

1. `POST /v1/assessments` returns the calibration prompt plus `progress`.
2. Speak/display `prompt` exactly. On a clarification request, use only the supplied `clarification_prompt`.
3. `POST /v1/assessments/{id}/responses` with a unique response ID and idempotency key.
4. Use `next_action.prompt` exactly when present and render the returned `progress` object.
5. Continue until `next_action.type=show_result`.
6. `GET /v1/assessments/{id}/result` returns the profile.

The client may safely retry the same response with the same idempotency key. A different prompt/item/kind than the current state returns HTTP 409. Evaluator downtime returns HTTP 503 with `Retry-After`, a stable `error_code`, and `retryable`; retry the same request rather than creating a second learner response. The official voice adapter retains that exact payload and lets the learner say `continue` to retry without repeating the answer. Requests such as “repeat,” “explain,” “give me a moment,” and deferred-scoring `continue` are controls and must not be submitted as new answers.

## Preparation and progress

Each prompt includes `preparation_seconds`. The recommended UI displays a quiet thinking indicator, but does not auto-submit or penalize the learner for using the full window. The default main-task windows are A1/A2 five seconds, B1 ten seconds, and B2 fifteen seconds; follow-ups use three seconds.

Every create, state, and response payload includes:

```json
{
  "progress": {
    "status": "in_progress",
    "current_section": "B1",
    "current_prompt_kind": "main",
    "questions_answered": 6,
    "confirmed_levels": ["A1", "A2"],
    "estimated_questions_remaining_min": 2,
    "estimated_questions_remaining_max": 6,
    "adaptive_length": true,
    "display_text": "6 responses completed; approximately 2 to 6 questions remain because the assessment is adaptive."
  }
}
```

`current_section` is internal orchestration metadata. It may be used by trusted
backend logic and analytics, but the voice agent must never announce it and the
learner UI should not expose level labels while the test is in progress. For a
neutral progress indicator, render `questions_answered`, the remaining-question
range, or `display_text`. Do not use a countdown for the whole assessment because
adaptive stopping makes one exact remaining time misleading.

## Final result contract

`GET /v1/assessments/{id}/result` returns the level, categorical and numeric evidence confidence, six dimension levels and evidence percentages, boundary result, and operational statistics. `confidence_score` is an evidence-sufficiency index from 0 to 100; it is not a calibrated probability that the level is correct. Likewise, `profile_scores_percent` normalizes administered-task rubric evidence and is not an official CEFR percentage.

Important fields for the application backend are:

```json
{
  "confirmed_level": "B1",
  "first_unconfirmed_level": "B2",
  "confidence": "medium",
  "confidence_score": 70,
  "profile": {
    "task_achievement": "B1",
    "interactive_communication": "B1",
    "fluency": "B2",
    "coherence": "B1",
    "lexical_adequacy": "B1",
    "intelligibility": "B2"
  },
  "profile_scores_percent": {
    "task_achievement": 75,
    "interactive_communication": 75,
    "fluency": 81,
    "coherence": 69,
    "lexical_adequacy": 75,
    "intelligibility": 81
  },
  "next_level_result": "B2 was not yet demonstrated",
  "statistics": {
    "duration_seconds": 417.2,
    "responses_submitted": 7,
    "scored_responses": 5,
    "invalid_audio_responses": 0,
    "prompt_repetitions": 1,
    "clarification_requests": 1,
    "tie_breakers_used": 0
  },
  "validity_warnings": []
}
```

Use `GET /v1/assessments/{id}/evidence` for trusted backend review. It returns
the fixed prompt, transcript, support counts, speech metrics, per-dimension
scores, evidence, decision reasons, evaluator provider/model, and timestamp for
each submitted response. It intentionally omits raw audio bytes and is protected
by the service credential. This endpoint is for audit, support, and pilot
calibration; do not expose raw transcripts or evaluator evidence publicly without
the learner-data policy required by your application.

## Mode routing

```text
mode=conversation          -> LiveKit agent english-tutor
mode=placement_assessment -> LiveKit agent english-level-assessor
```

Normal conversation never calls this service. Scoring logic never lives in `voice_agent.py` or the client.

## Audio and pronunciation

Upload the original, unenhanced microphone segment to `POST /v1/assessments/{id}/audio/{response_id}` as multipart field `audio`. Use the returned internal encrypted URI in the response submission. Enhanced audio may feed Flux, but only original audio should feed the phoneme service.

The level assessment does not contain a controlled read-aloud task. Conversational
answers supply placement evidence for intelligibility, interaction, and fluency.
Detailed phoneme alignment requires known reference speech and belongs in a
separate optional pronunciation activity after the placement test. The retained
pronunciation callback contract is independent and cannot change the conversational
level if a separate pronunciation worker is pending or fails.

## Voice-adapter response collection and recovery

Flux can commit one deliberate answer as several transcripts. The official adapter
buffers successive commits for `ASSESSMENT_RESPONSE_COLLECTION_DELAY_SECONDS`
(four seconds by default), combines their transcript and timing evidence, and sends
one response for the current prompt. An optional phrase such as `that's all` ends
the collection immediately; it is never required.

If a response receives HTTP 409, fetch `GET /v1/assessments/{id}`. If the assessment
is still active, resume from its returned `current_prompt`; if it is complete, fetch
the result. Do not tell the learner to restart a LiveKit room for a recoverable stale
prompt.

If scoring returns a retryable HTTP 503, keep the original response ID,
idempotency key, prompt identifiers, transcript, timing evidence, and audio URI.
Retry that exact payload after `Retry-After`. Never create a replacement response
ID for the same spoken answer. A late successful first request will then be
returned as an idempotent replay instead of being scored twice.

## Operational endpoints

- `GET /health/live`: process exists.
- `GET /health/ready`: database, evaluator secrets, item bank, and audio configuration are deployable.
- `GET /metrics`: Prometheus-format counters and sums; service authentication required.
- `POST /v1/admin/versions/activate`: select an installed bank version for restart; admin token required.
- `POST /v1/admin/retention/cleanup`: delete expired encrypted recordings; admin token required.

Full request/response schemas are exposed by FastAPI at `/docs` and summarized in `openapi.yaml`.
