# Debugging Guided Results

The result card reports **evidence eligibility**, not whether the learner sounded
clear to a person. A clear line can still be excluded when the speech-to-text
provider did not return enough timed words or enough first-to-last-word duration.

## Read the summary correctly

- `Eligible lines 2/6` means that six learner lines were evaluated and only two
  passed the evidence gates.
- `Learner speech 5.5 s` is the duration accumulated from eligible timed lines.
  It is not necessarily every second the learner spoke.
- `Evidence confidence Low` follows from the small eligible evidence set; it is
  not a pronunciation judgment.
- `Not Enough Evidence` intentionally suppresses the fluency index instead of
  presenting an unstable score.

Release 0.6.0 uses guided-specific gates:

- a line needs at least 2 timed words and 0.8 seconds of timed evidence;
- a session needs at least 3 eligible lines; and
- it then needs either 5 eligible lines or 8 seconds of eligible learner speech.

Free conversation and placement-assessment thresholds are unchanged.

## Inspect every line in the browser

At the end of a guided scenario, click **View result and debug details**. The
debug table shows:

- whether the line was eligible;
- timed word count;
- first-to-last-word duration;
- timing source;
- mean ASR recognition confidence; and
- exact rejection reasons.

The transcript colors use speech-to-text recognition confidence: below 25% is
red, 25% to below 75% is orange, and 75% or above is white. These colors help
debug recognition. They are not pronunciation-accuracy scores.

## Inspect the same data from PowerShell

Copy the `practice_session_id`, which starts with `guided-`, then run:

```powershell
$token = (Get-Content .env |
  Where-Object { $_ -like "ASSESSMENT_SERVICE_TOKEN=*" } |
  Select-Object -First 1).Split("=", 2)[1]

$sessionId = "guided-REPLACE-ME"
$response = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8080/v1/practice-sessions/$sessionId/result?mode=guided" `
  -Headers @{ Authorization = "Bearer $token" }

$response.result.result_debug.summary
$response.result.result_debug.thresholds
$response.result.result_debug.lines |
  Select-Object line_number, eligible, timed_word_count,
    response_duration_seconds, timing_source, asr_confidence_percent,
    insufficiency_reasons |
  Format-Table -Wrap
```

Interpret the common rejection reasons as follows:

| Reason | Meaning | What to check |
| --- | --- | --- |
| Word-level timestamps were unavailable | The STT result had text but no usable word timing | Confirm the guided worker is using Deepgram Flux and inspect provider events |
| Fewer than 2 timed words | Too few returned words could be timed | Check whether the microphone clipped the start/end or STT dropped words |
| Less than 0.8 seconds | The measured first-to-last-word span was too short | Check the returned word start/end values; do not use wall-clock turn time |
| Explicit audio issue | The turn was deliberately marked unusable | Inspect the accompanying audio issue reason |

For one failed line, compare `timed_word_count`,
`response_duration_seconds`, `timing_source`, and
`asr_confidence_percent` together. That distinguishes missing timing from poor
recognition and from a genuinely short utterance.

## Verify completion shutdown

After the closing line, the browser should receive `guided.session_closed`, turn
off its microphone, and disconnect from the LiveKit room. The per-room agent
session stops accepting speech. The `run_tutor.ps1` terminal remains running
because it is the shared worker service for future learners; that is expected.

If a completed room still accepts speech, filter the worker log for the room name
and verify this event order:

1. `guided.completed`
2. final assistant speech finishes
3. `guided.session_closed`
4. room disconnect / job shutdown

The worker must not speak a fallback warning after a session reaches `completed`
or `stopped`.
