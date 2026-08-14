# Install and test release 0.6.0 on Windows

Release 0.6.0 exposes exactly two practice modes: `free` and `guided`.
Placement assessment remains separate.

## 1. Extract and enter the project

```powershell
Expand-Archive `
  ".\realtime-english-tutor-complete-0.6.0.zip" `
  ".\realtime-english-tutor-complete-0.6.0"

cd ".\realtime-english-tutor-complete-0.6.0"
```

## 2. Install and configure

```powershell
conda activate nemo_g2p
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\setup.ps1"
```

Add the following to `.env`:

```env
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-key
LIVEKIT_API_SECRET=your-secret
DEEPGRAM_API_KEY=your-key
```

For guided-mode testing without running placement scoring:

```env
EVALUATOR_PROVIDER=heuristic
ALLOW_HEURISTIC_EVALUATOR=true
```

Keep these release values:

```env
ASSESSMENT_VERSION=0.6.0
ITEM_BANK_VERSION=0.2.0
RUBRIC_VERSION=0.3.0
SCORER_VERSION=0.3.0
FLUENCY_SCORER_VERSION=fluency-v0.1
CONVERSATION_MODE=free
```

`CONVERSATION_MODE` is only a fallback when trusted LiveKit dispatch metadata is
absent. `POST /v1/practice-sessions` supplies the authoritative mode.

## 3. Validate

```powershell
python -m pytest -q
python -m ruff check src app services tools tests
python -m compileall -q src app services tools
```

Expected backend result:

```text
Aya's 75 assessment/practice tests plus the main conversation-service suite pass.
```

## 4. Start guided mode

Terminal 1:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_service.ps1"
```

Terminal 2:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_tutor.ps1"
```

Terminal 3:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_guided_demo.ps1"
```

Open `http://127.0.0.1:5173`, choose a domain and an unlocked scenario, allow
microphone access, and follow all displayed learner lines. Previous tutor and
learner messages remain visible. Use Pause/Resume as needed, then select **Replay
full conversation** or **View result and debug details** at the end.

The guided room and its agent session close after the final spoken line. The tutor
terminal remains running as the shared worker for later sessions; this is expected.

Do not start `run_assessor.ps1` for guided practice. Guided and free both use
`english-tutor`; assessment alone uses `english-level-assessor`.

## 5. Result endpoint

```http
GET /v1/practice-sessions/{practice_session_id}/result?mode=guided
Authorization: Bearer <ASSESSMENT_SERVICE_TOKEN>
```

The guided report contains the fluency index/status, evidence count, four
subscores, feedback, delivery stability, retries, confidence change, optional
pronunciation, and `result_debug.lines`. The debug rows show which lines were
excluded and whether the cause was missing timings, too few timed words, or too
little timed duration. It never returns or changes CEFR placement.

## 6. API and frontend references

- Swagger: `http://127.0.0.1:8080/docs`
- OpenAPI: `docs/api/openapi.yaml`
- Team integration: `docs/api/backend_integration.md`
- Guided behavior: `docs/guided_conversations/guided_mode_v0_2.md`
- Browser adapter: `examples/frontend/guided-conversation.ts`
- Runnable demo: `examples/guided-demo`
