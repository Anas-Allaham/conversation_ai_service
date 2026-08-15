# Conversation AI Service + Integrated English Tutor

This repository is the team backend with the complete real-time English Tutor
merged into it. It intentionally keeps the existing backend contracts and adds
placement, free practice, and deterministic guided practice without running a
second FastAPI service or a second database.

## Final architecture

```text
Frontend / Django core
        |
        | HTTPS (one FastAPI application on port 8000)
        v
Conversation AI API
  |-- /api/v1/*  existing team session API (unchanged)
  |-- /v1/*      placement, fluency, free/guided practice
  |
  +---------------------------> one PostgreSQL database
  |
  +---- LiveKit dispatch -----> english-tutor worker
  |                              |-- free: Flux + Gemini + Aura
  |                              `-- guided: Flux + deterministic scenarios + Piper
  |
  `---- LiveKit dispatch -----> english-level-assessor worker
                                 `-- adaptive oral placement
```

LiveKit transports real-time audio, data events, participant tokens, and agent
dispatches. PostgreSQL stores durable sessions, transcripts, events, placement
evidence, fluency observations, and guided progress. Neither replaces the
other.

## Preserved and added contracts

The original team endpoints and response envelopes remain available:

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

The integrated tutor adds these API groups to the same application:

```text
/v1/assessments/*                 adaptive CEFR placement
/v1/assessment-sessions           secure placement room/token/dispatch
/v1/practice-sessions/*           secure Free/Guided session creation
/v1/fluency/*                     shared fluency evidence
/v1/guided-conversations/*        Restaurant and Airport guided scenarios
/v1/admin/*                       protected diagnostic and release operations
```

All `/api/v1/*` and learner-facing `/v1/*` routes accept
`Authorization: Bearer <SERVICE_API_KEY>`. Admin tutor routes use
`ASSESSMENT_ADMIN_TOKEN`. `ASSESSMENT_SERVICE_TOKEN` may be set separately; if
empty, it safely reuses `SERVICE_API_KEY`.

## Windows setup

Requirements: Python 3.11 or 3.12, `uv`, and a LiveKit project. Local development
uses SQLite by default; PostgreSQL is required for the team/production deployment.

```powershell
Copy-Item .env.example .env.local
```

Fill in `.env.local`, especially:

- `SERVICE_API_KEY` and `ASSESSMENT_ADMIN_TOKEN`
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`
- `DEEPGRAM_API_KEY`
- `GEMINI_API_KEY` when `EVALUATOR_PROVIDER=gemini`

Then run:

```powershell
.\scripts\setup.ps1
```

The setup installs every dependency, applies the single Alembic migration
chain, downloads LiveKit model assets, and installs the Piper voice once. Piper
guided speech then runs locally without an online TTS provider. It also stops
immediately with a clear error if a command fails or `DATABASE_URL` still
contains example credentials.

## Run the complete backend

Open three terminals in this repository:

```powershell
.\scripts\run_api.ps1
```

```powershell
.\scripts\run_tutor.ps1
```

```powershell
.\scripts\run_assessor.ps1
```

The unified Swagger document is at `http://127.0.0.1:8000/docs`. Health probes
are `/health/live` and `/health/ready`.

The tutor worker named `english-tutor` accepts both job contracts:

- Existing team metadata (`schema_version`, UUID `session_id`, UUID
  `subject_id`) starts the unchanged free conversation.
- `/v1/practice-sessions` metadata chooses exactly `free` or `guided`. The
  worker normalizes it into a stable backend UUID, so the same conversation is
  queryable through the team persistence endpoints.

The separate worker named `english-level-assessor` remains isolated so an
assessment cannot accidentally use the conversational tutor prompt or change a
level locally.

## Database ownership

`DATABASE_URL` is authoritative. The included SQLite value works locally without
installing a database server. In production, replace it with the team's real
PostgreSQL URL. The team SQLAlchemy layer uses its async driver, while the
assessment repository uses a compatible synchronous driver against the same
physical database. `ASSESSMENT_DATABASE_URL` is only an optional override; leave
it empty in the normal integrated configuration.

Run migrations before every deployment containing schema changes:

```powershell
uv run alembic upgrade head
```

Migration `0003_tutor_modules` adds the placement, fluency, guided-session,
replay, audio-reference, audit, and runtime-setting tables. Existing
conversation tables are not renamed or repurposed.

## Guided browser demo

After the API and `english-tutor` worker are running:

```powershell
.\scripts\run_guided_demo.ps1
```

The demo is only a temporary integration client. The production frontend can
later use the same `/v1/practice-sessions` response, LiveKit participant token,
`guided.events` topic, and `guided.command` topic.

## Verification

```powershell
uv run pytest -q
uv run ruff check .
uv run python tools\validate_item_bank.py
uv run python tools\validate_scenarios.py
```

The automated suite covers the original backend contracts, metadata and
persistence, adaptive placement, Free/Guided routing, fluency scoring, Piper
adapters, deterministic scenarios, and the shared FastAPI integration.

## Deployment

The Docker image defaults to `WORKER_ROLE=tutor`, preserving the original
`english-tutor` deployment. Deploy the same image a second time with
`WORKER_ROLE=assessment` for `english-level-assessor`. LiveKit Cloud supplies
its URL/key/secret to each worker. The API may be deployed with `modal_app.py`
or the team's existing platform after running Alembic.

Never commit `.env.local`, database dumps, recorded audio, or downloaded Piper
model files.

See [INTEGRATION_GUIDE_AR.md](INTEGRATION_GUIDE_AR.md) for the Arabic handoff
and the exact frontend/backend sequence.
