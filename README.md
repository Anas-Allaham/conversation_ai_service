# Conversation AI Service

Realtime English-tutor infrastructure with two deployable processes:

- `src/agent.py`: a named LiveKit worker (`english-tutor`) that owns continuous
  Deepgram Flux STT, LiveKit Inference LLM, Deepgram streaming TTS, QUAIL-L
  enhancement, turn detection, and barge-in.
- `conversation_ai.api.main`: an authenticated FastAPI service that creates
  rooms, dispatches the agent, signs join tokens, and exposes persisted sessions.

Both processes use the same AI-owned PostgreSQL database. The Django core owns
users and PII; this service sees only opaque UUIDs. Raw audio is never recorded
or persisted.

## Architecture

```text
Browser/mobile -- WebRTC --> LiveKit Cloud <--> English tutor worker
                                 ^                    |
                                 | room/dispatch      | SQL
                                 |                    v
Django core -- HTTPS --> Conversation API ------> PostgreSQL
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

## Local setup

Install Python 3.11 and [uv](https://docs.astral.sh/uv/), then:

```powershell
cd C:\projects\conversation_ai_service
Copy-Item .env.example .env.local
uv sync --all-extras
uv run alembic upgrade head
uv run python -m livekit.agents download-files
```

Fill `.env.local` with valid LiveKit, Deepgram, PostgreSQL, and service API
credentials. Never commit the file.

Run a local voice session:

```powershell
uv run python src/agent.py console
```

Run the worker against LiveKit Cloud with hot reload:

```powershell
uv run python src/agent.py dev
```

Run the internal query API:

```powershell
uv run uvicorn conversation_ai.api.main:app --reload
```

The API is available at `http://127.0.0.1:8000/docs`. Public health endpoints
are `/health/live` and `/health/ready`; all `/api/v1` routes require
`Authorization: Bearer <SERVICE_API_KEY>`.

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
uv run ruff check .
uv run pytest
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
