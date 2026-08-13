# Real-Time English Tutor 0.6.0

Release 0.6.0 has exactly two learner-selectable practice modes:

| Practice mode | Behavior | Agent | Result |
|---|---|---|---|
| `free` | The learner discusses any topic; the AI creates replies dynamically | `english-tutor` | Rolling fluency index and feedback; no CEFR |
| `guided` | The learner chooses a level-approved scenario and follows fixed displayed lines | `english-tutor` | Guided-speaking fluency, delivery, retries, confidence, and optional pronunciation; no CEFR |

Placement assessment is a separate onboarding/reassessment flow using
`english-level-assessor`. It is not a third practice mode. Only controlled
assessment may return a provisional CEFR-aligned fluency estimate.

The former 0.4.0 public value `scripted` has been removed. Sending it now returns
validation failure instead of silently selecting another behavior.

## Included

- Existing Phase 1-3 LiveKit tutor with Deepgram Flux, Aura-2, Silero VAD, and
  QUAIL-L audio enhancement.
- Separate adaptive A1-B2 oral placement agent and FastAPI service.
- Shared explainable `fluency-v0.1` feature extractor and scorer.
- A domain-first catalog. The Restaurant domain currently contains drink ordering,
  meal ordering, and wrong-order scenarios.
- Persistent on-screen conversation history, per-word STT confidence colors,
  pause/resume, replay/slow replay, retry/continue/stop, and full-conversation replay.
- Guided-specific evidence gates and a per-line result debugger showing exactly why
  a selected line was included or excluded.
- Secure `POST /v1/practice-sessions` contract for `free | guided`, short-lived
  LiveKit tokens, and explicit dispatch of `english-tutor` with trusted metadata.
- Ready-to-run guided browser demo under `examples/guided-demo`.
- 75 backend tests plus scenario, OpenAPI, lint, compilation, and frontend build checks.

## Windows setup

Requirements:

- Python 3.11.
- Node.js 20 or newer for the included browser demo.
- LiveKit CLI authenticated to the same LiveKit project as `.env`.
- LiveKit URL/key/secret and a Deepgram key.

From PowerShell:

```powershell
cd realtime-english-tutor-complete-0.6.0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\setup.ps1"
```

The setup creates `.env`, safe local service tokens, and a Fernet key. Add:

```env
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-livekit-key
LIVEKIT_API_SECRET=your-livekit-secret
DEEPGRAM_API_KEY=your-deepgram-key
```

For a guided-only local test, the placement evaluator is not used. You may make
the health check ready without a Gemini key by using the explicitly non-production
test evaluator:

```env
EVALUATOR_PROVIDER=heuristic
ALLOW_HEURISTIC_EVALUATOR=true
```

For a real placement assessment, restore:

```env
EVALUATOR_PROVIDER=gemini
ALLOW_HEURISTIC_EVALUATOR=false
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-2.5-flash-lite
GEMINI_API_VERSION=v1beta
```

## Run a guided conversation with your microphone

Open three PowerShell terminals in the project folder.

Terminal 1 — start the API and guided state engine:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_service.ps1"
```

Check:

```powershell
curl.exe http://127.0.0.1:8080/health/ready
```

Terminal 2 — register the shared tutor worker:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_tutor.ps1"
```

Wait until `english-tutor` is registered.

Terminal 3 — run the safe local browser gateway/demo:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_guided_demo.ps1"
```

Open `http://127.0.0.1:5173`, then:

1. Select the learner's placement level.
2. Select a domain, then an unlocked scenario inside it.
3. Click **Start guided conversation** and allow microphone access.
4. Listen to the fixed character line.
5. Say the exact learner line shown on screen.
6. Use Pause/Resume, Retry/Continue, Replay, or Play slowly as needed.
7. Finish the scenario, optionally replay the full visible conversation, and click
   **View result and debug details**.

After completion, the LiveKit room and the per-user agent session close. The
`run_tutor.ps1` terminal itself remains running because it is the shared worker
service that must accept the next learner; it must no longer hear audio or repeat an
"inactive" warning for the completed room.

The demo's local Vite server reads `ASSESSMENT_SERVICE_TOKEN` from the project
`.env` and proxies requests. The token is not compiled into browser JavaScript.
Production must use the team's authenticated backend instead of this development
proxy.

## Retrieve the guided result manually

Copy `practice_session_id` from the browser/network response or the service log.
It begins with `guided-`. Then run:

```powershell
$token = (Get-Content .env |
  Where-Object { $_ -like "ASSESSMENT_SERVICE_TOKEN=*" } |
  Select-Object -First 1).Split("=", 2)[1]

$sessionId = "guided-REPLACE-ME"

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8080/v1/practice-sessions/$sessionId/result?mode=guided" `
  -Headers @{ Authorization = "Bearer $token" }
```

Important guided-result fields:

- `result.guided_speaking_fluency.fluency_index`
- `result.guided_speaking_fluency.confidence`
- `result.guided_speaking_fluency.evidence_count`
- `result.guided_speaking_fluency.subscores`
- `result.guided_speaking_fluency.feedback`
- `result.delivery_stability`
- `result.pronunciation`
- `result.confidence_change`
- `result.result_debug.thresholds`
- `result.result_debug.lines`
- `result.replay_script`

If timing evidence is insufficient, `fluency_index` is `null` and status is
`insufficient_evidence`. `result_debug.lines` then exposes each selected line's
timed word count, duration, timing source, ASR confidence, eligibility decision,
and rejection reasons. Guided reports always return `cefr_fluency_estimate: null`
and never change the stored placement level.

## Unified session contract

The team's backend calls the same endpoint for both practice modes:

```http
POST /v1/practice-sessions
Authorization: Bearer <ASSESSMENT_SERVICE_TOKEN>
```

Free:

```json
{
  "user_id": "user-123",
  "mode": "free"
}
```

Guided:

```json
{
  "user_id": "user-123",
  "mode": "guided",
  "scenario_id": "restaurant.order_drink.a1",
  "placement_completed": true,
  "placement_level": "A1",
  "recording_consent": false
}
```

The response contains `server_url`, `participant_token`, `room_name`,
`practice_session_id`, and the initial `guided_session` when applicable. The
token is short lived and explicitly dispatches `english-tutor`. The dispatch
metadata contains exactly `conversation_mode: free` or `conversation_mode: guided`.

The browser connects directly to LiveKit for audio. It never receives LiveKit,
Deepgram, Gemini, TTS, pronunciation, or assessment-service secrets.

## Guided events and commands

The worker publishes learner-safe state on `guided.events` and receives reliable
commands on `guided.command`:

```json
{"command":"retry"}
```

Supported commands are `retry`, `continue`, `replay`, `replay_slow`, `pause`,
`resume`, and `stop`.
HTTP state remains authoritative; LiveKit data packets are UI notifications.

The catalog entrypoint is `GET /v1/guided-conversations/domains`; every returned
domain contains its level-gated scenario summaries. The older flat scenarios route
remains available for compatibility.

## Validation

```powershell
.\.venv\Scripts\python.exe tools\validate_item_bank.py
.\.venv\Scripts\python.exe tools\validate_scenarios.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app services tools
.\.venv\Scripts\python.exe -m compileall -q app services tools

cd examples\guided-demo
npm.cmd install
npm.cmd run build
```

Expected backend result: `75 passed`.

## Documentation

- `INSTALL_0.6.0.md`
- `docs/api/backend_integration.md`
- `docs/api/openapi.yaml`
- `docs/guided_conversations/guided_mode_v0_2.md`
- `docs/guided_conversations/debugging_results.md`
- `docs/fluency/fluency_v0_1.md`
- `docs/assessment/MILESTONE_COMPLETION.md`
- `CHANGELOG.md`
