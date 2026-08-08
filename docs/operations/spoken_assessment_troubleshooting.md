# Spoken assessment troubleshooting

## Correct start order

Open PowerShell in the project folder and run the following in two terminals.

Terminal 1:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\run_service.ps1
```

Verify:

```powershell
curl.exe http://127.0.0.1:8080/health/ready
```

The status must be `ready`. Then run terminal 2:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\run_assessor.ps1
```

The assessor script runs `tools\assessment_preflight.py` first. It only
registers `english-level-assessor` when the API, evaluator key/model,
encryption configuration, and voice credentials are usable.

## HTTP 422 with empty `words[*].word`

Version 0.1.0 read LiveKit words through `.word`, while LiveKit 1.6.x Deepgram
Flux exposes `TimedString.text`, `start_time`, and `end_time`. The API therefore
received rows such as `{"word": ""}` and correctly rejected them.

Version 0.1.1 fixes this in two places:

1. `app/realtime/assessment_agent.py` normalizes object, mapping, Pydantic, and
   legacy word shapes and removes blank entries before JSON serialization.
2. `services/oral_assessment/models.py` repeats that normalization at the API
   boundary.

If a future provider shape is still rejected, the agent submits an explicit
invalid-audio observation. The state machine repeats the same prompt once and
does not count the turn as a failed level response.

## The answer appears in several short fragments

Ordinary tutor dialogue values speed. A placement answer values complete
evidence. The assessor therefore has separate settings:

```env
ASSESSMENT_FLUX_EOT_THRESHOLD=0.90
ASSESSMENT_FLUX_EOT_TIMEOUT_MS=10000
ASSESSMENT_ENDPOINTING_MIN_DELAY_SECONDS=1.50
ASSESSMENT_ENDPOINTING_MAX_DELAY_SECONDS=4.00
```

The normal `app/realtime/voice_agent.py` is unchanged. Do not lower these
assessment values to improve latency unless a repeatable test shows that
answers remain complete.

## The transcript contains wrong words

First check the selected microphone in LiveKit Agent Console and use headphones
to reduce speaker echo. Then repeat one fixed sentence with the default:

```env
ASSESSMENT_AUDIO_ENHANCEMENT=quail_l
```

If the same microphone is transcribed worse, set:

```env
ASSESSMENT_AUDIO_ENHANCEMENT=none
```

Restart only `run_assessor.ps1` and repeat the identical sentence. Keep the
setting with fewer substitutions. QUAIL-L remains the default because it won
the controlled project recording, but that single recording is not proof that
it improves every microphone, voice, or room.

Never interpret ASR confidence or transcript spelling as a pronunciation
score. The placement service uses ASR confidence only as validity evidence.

## AUDIO_ENCRYPTION_KEY is missing or invalid

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\configure_local_secrets.ps1
```

It generates a 44-character URL-safe Fernet key only when the current key is
missing or malformed. A valid existing key is never rotated. Keep `.env`
private; changing the key makes older encrypted recordings unreadable.

## HTTP 503 while scoring

Gemini may return retryable 429 or 503 responses. Release 0.2.1 disables the
SDK's generic immediate retries and instead honors Google's reported
`RetryInfo.retryDelay`, with a bounded total wait. The assessment client does
not immediately duplicate a response POST when the service supplies
`Retry-After`.

If all retries are exhausted, the voice adapter says that the answer was saved.
It gives the provider's wait time when available. The learner should wait, then
say `continue`; the same response ID and idempotency key are retried. Do not
repeat the spoken answer and do not restart the LiveKit room.

The API response contains `error_code`, `provider_status`, and `retryable`.
Common values include `provider_overloaded`, `provider_rate_limited`,
`provider_daily_quota_exhausted`, `provider_configuration_error`, and
`invalid_structured_output`. The service terminal records the category without
printing the learner transcript or provider credentials.

An `AQ.` prefix is normal for the authorization-key format that Google AI Studio
introduced in 2026. Do not reject a key based on that prefix. Release 0.2.1 uses
the stable `v1` API and validates the configured key/model before readiness
becomes healthy. A 404 therefore blocks assessor startup instead of replaying a
learner prompt.

If a key ever appears in chat, a screenshot, a log attachment, or source
control, revoke it in Google AI Studio and create a replacement. Treat both
standard and authorization keys as secrets.

The free tier can be too small for repeated full assessments. The exact limit
is project/model-specific and is stated in the provider's 429 response. For
local development, `gemini-2.5-flash-lite` is the default. For dependable pilot
testing, enable Gemini paid billing and set a billing budget/alert.

## Rejected or stale responses

- HTTP 422 triggers invalid-audio recovery and prompt repetition.
- HTTP 409 triggers `GET /v1/assessments/{id}` state recovery. The adapter
  resumes at the backend prompt or returns the already completed result.
- Network failure keeps the same deferred payload and uses the same `continue`
  recovery path as retryable scoring failure.
- Evaluator HTTP 5xx always keeps the deferred payload. It never triggers a
  prompt replay, even when the underlying provider error is non-retryable.

The assessor log includes the fixed `prompt_id`, final transcript, and number of
valid timed words for each submitted response. It does not print credentials.
