# Conversation AI Service

Realtime English-tutor infrastructure with four local entrypoints:

- `src/agent.py`: a named LiveKit worker (`english-tutor`) that owns continuous
  Deepgram Flux STT, LiveKit Inference LLM, Deepgram streaming TTS, QUAIL-L
  enhancement, turn detection, and barge-in.
- `conversation_ai.api.main`: an authenticated FastAPI service that creates
  rooms, dispatches the agent, signs join tokens, and exposes persisted sessions.
- `app/realtime/assessment_agent.py`: the separate `english-level-assessor`
  LiveKit worker for controlled A1-B2 oral placement.
- `services.oral_assessment.main`: the assessment, free/guided practice,
  fluency, pronunciation, retention, and administration API.

The main conversation service and the assessment service keep separate domain
schemas and can use separate database URLs. The Django core owns users and PII;
the main service sees opaque UUIDs. Raw audio is disabled by default and is
stored only when the assessment/practice consent and storage policies permit it.

## Architecture

```text
Browser/mobile -- WebRTC --> LiveKit Cloud <--> english-tutor
                                 |              (free or guided)
                                 +-----------> english-level-assessor
                                 ^                    |
                                 | room/dispatch      | HTTPS
                                 |                    v
Django core -- HTTPS --> Conversation API     Assessment/practice API
                                 |                    |
                                 v                    v
                         conversation DB        assessment DB
```

The core starts conversations through the authenticated REST API. This service
holds the LiveKit credentials and owns deterministic room creation, exactly-once
explicit dispatch, and participant-token signing.

## Job metadata contract

The start API creates strict LiveKit dispatch metadata:

```json
{
  "schema_version": 1,
  "session_id": "89f3b7f5-8c67-46b2-80a8-3937491b47db",
  "subject_id": "43a4c3a9-758f-4760-a80d-7c5451344fa9",
  "lesson_id": "optional-core-lesson-id",
  "locale": "en"
}
```

Unknown fields and unsupported schema versions are rejected by the worker.
Console mode can run without metadata and generates anonymous temporary UUIDs.
Practice sessions use a second validated contract containing `conversation_mode`,
`practice_session_id`, `user_id`, and `guided_session_id` for guided sessions.
Only `free` and `guided` are accepted; the former `scripted` value is rejected.

## Local setup

Activate the required Python 3.10 Conda environment, then install the merged
project without replacing the existing NeMo stack:

```powershell
cd C:\projects\conversation_ai_service
conda activate nemo_g2p
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
python -m alembic upgrade head
python -m livekit.agents download-files
```

Fill `.env.local` with valid LiveKit, Deepgram, PostgreSQL, and service API
credentials. Never commit the file.

Run a local voice session:

```powershell
python src/agent.py console
```

Run the worker against LiveKit Cloud with hot reload:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_tutor.ps1
```

Run the internal query API:

```powershell
python -m uvicorn conversation_ai.api.main:app --reload
```

The API is available at `http://127.0.0.1:8000/docs`. Public health endpoints
are `/health/live` and `/health/ready`; all `/api/v1` routes require
`Authorization: Bearer <SERVICE_API_KEY>`.

Run the assessment/practice API and assessor in separate terminals:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_service.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_assessor.ps1
```

The assessment API is available at `http://127.0.0.1:8080/docs`. Its public
contracts include `/v1/assessments`, `/v1/practice-sessions`,
`/v1/guided-conversations`, `/v1/fluency`, pronunciation callbacks, health,
metrics, retention, and version administration. Guided practice publishes state
on `guided.events` and accepts reliable commands on `guided.command`.

## Internal API

```text
GET    /api/v1/capabilities
POST   /api/v1/sessions/start
GET    /api/v1/sessions/{session_id}
GET    /api/v1/sessions/{session_id}/turns
GET    /api/v1/sessions/{session_id}/events
GET    /api/v1/subjects/{subject_id}/sessions
DELETE /api/v1/sessions/{session_id}
DELETE /api/v1/subjects/{subject_id}
```

Start requests use a caller-generated UUID as the idempotency key. The core
must reuse that UUID when retrying:

```json
{
  "session_id": "89f3b7f5-8c67-46b2-80a8-3937491b47db",
  "subject_id": "43a4c3a9-758f-4760-a80d-7c5451344fa9",
  "lesson_id": "optional-core-lesson-id",
  "locale": "en"
}
```

List endpoints use opaque cursor pagination with `cursor` and `limit` (default
20, maximum 100). Success responses use `{"data": ..., "meta": ...}`; errors
use `{"error": ..., "meta": ...}`. `X-Request-ID` is returned on every response.

## Test

```powershell
python -m ruff check .
python -m pytest
python tools\validate_item_bank.py
python tools\validate_scenarios.py
```

Tests use temporary SQLite databases for fast contract coverage. CI additionally
applies the Alembic migration to PostgreSQL before running the suite.

## Deploy the orchestration/query API to Modal

Create one managed PostgreSQL database reachable from both Modal and LiveKit
Cloud, then configure the Modal secret:

```powershell
modal secret create conversation-ai-service-secrets `
  APP_ENV=production `
  DATABASE_URL="postgresql://..." `
  SERVICE_API_KEY="replace-with-a-long-random-value" `
  LIVEKIT_URL="wss://your-project.livekit.cloud" `
  LIVEKIT_API_KEY="..." `
  LIVEKIT_API_SECRET="..."

modal run modal_app.py::migrate
modal deploy modal_app.py
```

Run `modal run modal_app.py::migrate` before deploying a version containing a
new database migration.

## Deploy the worker to LiveKit Cloud

Install the current LiveKit CLI, authenticate, and link the intended project:

```powershell
lk cloud auth
lk project list
lk project set-default "your-project"
```

Create the deployment the first time:

```powershell
lk agent create --region eu-central `
  --secrets APP_ENV=production `
  --secrets DEEPGRAM_API_KEY="..." `
  --secrets DATABASE_URL="postgresql://..." `
  .
```

LiveKit Cloud injects `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and
`LIVEKIT_API_SECRET`; do not upload them as agent secrets. Later releases use:

```powershell
lk agent deploy .
lk agent status
lk agent logs
```

The Docker image runs as a non-root user and starts with
`python src/agent.py start`. It exposes only LiveKit's health port; it does not
expose the internal FastAPI service.

## Secret rotation

- Rotate `SERVICE_API_KEY` with `modal secret create ... --force` (or update the
  secret in the Modal dashboard), redeploy the API, then update the future core.
- Rotate `DEEPGRAM_API_KEY` with `lk agent update-secrets`; LiveKit performs a
  rolling restart.
- Rotate database credentials at the provider, update both Modal and LiveKit
  secrets, then verify `/health/ready` and a test dispatch.
- Never place credentials in Docker build arguments, `livekit.toml`, source, or
  Git history.
