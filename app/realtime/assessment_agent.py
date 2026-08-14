from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import AsyncIterable
from typing import Any

from livekit import agents, rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    APIConnectOptions,
    TurnHandlingOptions,
    inference,
    room_io,
)
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins import deepgram

from app.realtime.assessment_payload import (
    extract_words,
    optional_confidence,
    read_value,
    valid_submission_words,
)
from app.realtime.assessment_turns import (
    PendingResponse,
    assessment_endpointing_options,
    control_intent,
    learner_result_announcement,
    scoring_deferred_message,
    spoken_prompt,
    strip_optional_completion_marker,
)
from app.services.assessment_client import (
    AssessmentClient,
    AssessmentClientError,
    AssessmentHTTPError,
    AssessmentPayloadRejected,
    AssessmentServiceUnavailable,
)
from app.services.raw_audio import RawAudioSegmentRecorder
from conversation_ai.agent.pipeline import build_audio_input_options, build_tts, build_vad
from conversation_ai.config import env_float, env_int, get_settings

logger = logging.getLogger("english-level-assessor")


ASSESSMENT_AGENT_INSTRUCTIONS = """You are a transport adapter for a fixed oral placement assessment.
Never invent, rewrite, or explain an assessment prompt. Every assessment prompt must come from the oral-assessment service.
Do not score a learner and do not choose a level locally.
Never announce the internal A1, A2, B1, or B2 assessment section. Progress metadata is for the application UI only.
"""

SERVICE_UNAVAILABLE_MESSAGE = (
    "The level assessment service is temporarily unavailable. "
    "Please end this assessment session and try again in a few minutes."
)

ASSESSMENT_COMPLETE_MESSAGE = (
    "This assessment is already complete. Your result remains available in the application."
)


def _user_turn_from_chat_context(chat_ctx: Any) -> tuple[str, str]:
    items = list(getattr(chat_ctx, "items", []))
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if getattr(item, "role", None) == "user":
            content = getattr(item, "text_content", "")
            if callable(content):
                content = content()
            text = str(content or "").strip()
            identity = (
                getattr(item, "id", None)
                or getattr(item, "item_id", None)
                or f"chat-{len(items)}-{index}-{text}"
            )
            return text, str(identity)
    return "", "empty-user-turn"


def build_assessment_stt() -> deepgram.STTv2:
    """Use conservative Flux endpointing for deliberate learner answers."""
    eot_threshold = env_float("ASSESSMENT_FLUX_EOT_THRESHOLD", 0.90)
    eot_timeout_ms = env_int("ASSESSMENT_FLUX_EOT_TIMEOUT_MS", 10_000)
    if not 0.5 <= eot_threshold <= 0.9:
        raise RuntimeError("ASSESSMENT_FLUX_EOT_THRESHOLD must be between 0.5 and 0.9")
    if eot_timeout_ms < 1_000:
        raise RuntimeError("ASSESSMENT_FLUX_EOT_TIMEOUT_MS must be at least 1000")
    logger.info(
        "[ASSESSMENT STT] model=flux-general-en | eot-threshold=%.2f | timeout=%dms",
        eot_threshold,
        eot_timeout_ms,
    )
    return deepgram.STTv2(
        model="flux-general-en",
        eot_threshold=eot_threshold,
        eot_timeout_ms=eot_timeout_ms,
    )


def build_assessment_audio_input_options() -> room_io.AudioInputOptions:
    """Keep the tested QUAIL-L default but allow assessment-only A/B diagnosis."""
    runtime_settings = get_settings()
    mode = os.getenv(
        "ASSESSMENT_AUDIO_ENHANCEMENT",
        runtime_settings.audio_enhancement,
    ).strip().lower()
    if mode in {"", "none", "off", "false", "disabled"}:
        mode = "none"
    if mode != "quail_l":
        if mode != "none":
            raise RuntimeError("ASSESSMENT_AUDIO_ENHANCEMENT must be 'quail_l' or 'none'")

    level_text = os.getenv("ASSESSMENT_AUDIO_ENHANCEMENT_LEVEL", "").strip()
    level: float | None = None
    if level_text:
        level = env_float("ASSESSMENT_AUDIO_ENHANCEMENT_LEVEL", 0.80)
        if not 0.0 <= level <= 1.0:
            raise RuntimeError(
                "ASSESSMENT_AUDIO_ENHANCEMENT_LEVEL must be between 0.0 and 1.0"
            )
    assessment_settings = runtime_settings.model_copy(
        update={"audio_enhancement": mode, "audio_enhancement_level": level}
    )
    return build_audio_input_options(assessment_settings)


class LevelAssessmentAgent(Agent):
    def __init__(
        self,
        client: AssessmentClient,
        recorder: RawAudioSegmentRecorder,
        assessment_id: str,
        current_prompt: dict[str, Any],
        *,
        service_available: bool = True,
    ) -> None:
        super().__init__(instructions=ASSESSMENT_AGENT_INSTRUCTIONS)
        self.client = client
        self.recorder = recorder
        self.assessment_id = assessment_id
        self.current_prompt = current_prompt
        self.service_available = service_available
        self._words: list[dict[str, Any]] = []
        self._asr_confidence: float | None = None
        self._turn_started_ms: int | None = None
        self._response_started_ms: int | None = None
        self._prompt_repetitions = 0
        self._clarification_requests = 0
        self._pending_response = PendingResponse()
        self._preserve_recording = False
        self._assessment_completed = False
        self._deferred_payload: dict[str, Any] | None = None
        self._deferred_retry_after_seconds: float | None = None
        self._deferred_retryable = True
        self._session: AgentSession | None = None
        self._collection_delay = env_float(
            "ASSESSMENT_RESPONSE_COLLECTION_DELAY_SECONDS", 4.0
        )
        if not 0.5 <= self._collection_delay <= 8.0:
            raise RuntimeError(
                "ASSESSMENT_RESPONSE_COLLECTION_DELAY_SECONDS must be between 0.5 and 8.0"
            )

    def bind_session(self, session: AgentSession) -> None:
        self._session = session

    def mark_user_speaking(self) -> None:
        if self._turn_started_ms is None:
            self._turn_started_ms = int(time.time() * 1000)
            if self._response_started_ms is None:
                self._response_started_ms = self._turn_started_ms
            asyncio.create_task(
                self.recorder.start_segment(reset=not self._preserve_recording)
            )

    async def stt_node(self, audio, model_settings):
        async for event in Agent.default.stt_node(self, audio, model_settings):
            alternatives = read_value(event, "alternatives", default=[]) or []
            if alternatives:
                alternative = alternatives[0]
                captured = extract_words(read_value(alternative, "words", default=[]))
                if captured:
                    self._words = captured
                confidence = optional_confidence(read_value(alternative, "confidence"))
                if confidence is not None:
                    self._asr_confidence = confidence
            yield event

    def _payload(
        self,
        *,
        prompt: dict[str, Any],
        response_id: str,
        transcript: str,
        audio_uri: str | None,
        ended_ms: int,
    ) -> dict[str, Any]:
        return {
            "response_id": response_id,
            "idempotency_key": f"livekit-{response_id}",
            "prompt_id": prompt["prompt_id"],
            "item_id": prompt["item_id"],
            "prompt_kind": prompt["prompt_kind"],
            "transcript": transcript,
            "words": valid_submission_words(self._words),
            "response_started_at_ms": self._response_started_ms,
            "response_ended_at_ms": ended_ms,
            "audio_uri": audio_uri,
            "prompt_repetitions": self._prompt_repetitions,
            "clarification_requests": self._clarification_requests,
            "asr_confidence": self._asr_confidence,
            "explicit_audio_issue": False,
            "audio_issue_reason": None,
            "session_interrupted": False,
        }

    @staticmethod
    def _invalid_audio_recovery_payload(payload: dict[str, Any]) -> dict[str, Any]:
        recovered = dict(payload)
        recovered.update(
            transcript="",
            words=[],
            asr_confidence=None,
            explicit_audio_issue=True,
            audio_issue_reason=(
                "The voice adapter could not normalize the provider transcript payload."
            ),
        )
        return recovered

    def _reset_turn(self, *, keep_response_start: bool = False) -> None:
        self._words = []
        self._asr_confidence = None
        self._turn_started_ms = None
        if not keep_response_start:
            self._response_started_ms = None

    def _reset_prompt_state(self) -> None:
        self._reset_turn()
        self._prompt_repetitions = 0
        self._clarification_requests = 0
        self._pending_response.reset()
        self._preserve_recording = False
        self._deferred_payload = None
        self._deferred_retry_after_seconds = None
        self._deferred_retryable = True

    def _defer_submission(
        self,
        payload: dict[str, Any],
        *,
        error: AssessmentHTTPError | None = None,
    ) -> None:
        self._deferred_payload = dict(payload)
        self._remember_deferred_error(error)
        self._pending_response.reset()
        self._preserve_recording = False
        self._reset_turn()

    def _remember_deferred_error(self, error: AssessmentHTTPError | None) -> None:
        if error is None:
            self._deferred_retry_after_seconds = None
            self._deferred_retryable = True
            return
        self._deferred_retry_after_seconds = error.retry_after_seconds
        self._deferred_retryable = error.retryable

    def _deferred_message(self) -> str:
        return scoring_deferred_message(
            retry_after_seconds=self._deferred_retry_after_seconds,
            retryable=self._deferred_retryable,
        )

    async def _pause_control_audio(self) -> None:
        preserve = self._pending_response.has_content
        await self.recorder.pause_segment(preserve=preserve)
        if preserve:
            self._pending_response.postpone_submission()
        self._reset_turn(keep_response_start=preserve)

    def _set_input_enabled(self, enabled: bool) -> None:
        if self._session is None:
            return
        try:
            self._session.input.set_audio_enabled(enabled)
        except Exception:
            logger.exception("Could not change assessment audio-input state")

    def _disable_input(self) -> None:
        self._set_input_enabled(False)

    async def _submit_with_schema_recovery(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.client.submit_response_async(self.assessment_id, payload)
        except AssessmentPayloadRejected:
            # A validation rejection is not a service outage and must not turn
            # into a proficiency failure. Submit a deterministic invalid-audio
            # observation so the service repeats the same fixed prompt once.
            logger.exception(
                "Assessment payload was rejected; recording an invalid-audio retry"
            )
            return await self.client.submit_response_async(
                self.assessment_id,
                self._invalid_audio_recovery_payload(payload),
            )

    async def _next_spoken_text(self, result: dict[str, Any]) -> str:
        action = result["next_action"]
        next_prompt = action.get("prompt")
        if next_prompt:
            self.current_prompt = next_prompt
            self._reset_prompt_state()
            return spoken_prompt(next_prompt)

        final = await self.client.get_result_async(self.assessment_id)
        self._assessment_completed = True
        self._disable_input()
        return learner_result_announcement(final)

    async def _recover_session_state(self) -> str:
        """Recover from a stale prompt without forcing the learner to restart."""
        state = await self.client.get_assessment_state_async(self.assessment_id)
        status = str(state.get("record", {}).get("status") or "")
        if status == "completed":
            return await self._next_spoken_text({"next_action": {"prompt": None}})
        prompt = state.get("current_prompt")
        if not prompt:
            raise AssessmentClientError("Assessment state did not include a current prompt")
        self.current_prompt = prompt
        self._reset_prompt_state()
        logger.warning(
            "Recovered assessment state at prompt=%s",
            prompt.get("prompt_id"),
        )
        return "Let's continue. " + spoken_prompt(prompt)

    async def _retry_deferred_submission(self) -> str:
        if self._deferred_payload is None:
            return "There is no saved answer waiting to be scored. Please answer the current question."
        payload = dict(self._deferred_payload)
        result = await self._submit_with_schema_recovery(payload)
        self._deferred_payload = None
        self._deferred_retry_after_seconds = None
        self._deferred_retryable = True
        return await self._next_spoken_text(result)

    async def llm_node(self, chat_ctx, tools, model_settings) -> AsyncIterable[str]:
        if not self.service_available:
            yield SERVICE_UNAVAILABLE_MESSAGE
            return

        if self._assessment_completed:
            yield ASSESSMENT_COMPLETE_MESSAGE
            return

        transcript, turn_id = _user_turn_from_chat_context(chat_ctx)
        intent = control_intent(transcript)
        prompt = dict(self.current_prompt)

        if self._deferred_payload is not None:
            await self.recorder.pause_segment(preserve=False)
            self._reset_turn()
            if intent != "resume":
                yield (
                    "Your previous answer is already saved. Please say continue when you want me "
                    "to retry scoring it."
                )
                return
            self._set_input_enabled(False)
            try:
                yield "Thank you. I am retrying your saved answer now. "
                yield await self._retry_deferred_submission()
            except (AssessmentServiceUnavailable, AssessmentHTTPError) as exc:
                if isinstance(exc, AssessmentHTTPError):
                    self._remember_deferred_error(exc)
                else:
                    self._remember_deferred_error(None)
                logger.warning(
                    "Deferred assessment scoring is still unavailable: %s",
                    getattr(exc, "error_code", type(exc).__name__),
                )
                yield self._deferred_message()
            except AssessmentClientError:
                logger.exception("Deferred assessment scoring retry failed")
                self._remember_deferred_error(None)
                yield self._deferred_message()
            finally:
                if not self._assessment_completed:
                    self._set_input_enabled(True)
            return

        if intent in {"repeat", "clarify", "thinking"}:
            await self._pause_control_audio()
            if intent == "repeat":
                self._prompt_repetitions += 1
                yield "Of course. " + spoken_prompt(prompt)
            elif intent == "clarify":
                self._clarification_requests += 1
                explanation = str(prompt.get("clarification_prompt") or prompt["prompt"])
                yield "Of course. " + explanation + " Start when you are ready."
            else:
                yield "Of course. Take your time. Start when you are ready."
            return

        fragment, inline_done = strip_optional_completion_marker(transcript)
        explicit_done = intent == "done" or inline_done
        if explicit_done and not fragment and not self._pending_response.has_content:
            await self._pause_control_audio()
            yield "Please answer the question first."
            return

        generation = self._pending_response.add(
            prompt_id=str(prompt["prompt_id"]),
            turn_id=turn_id,
            transcript=fragment,
            words=valid_submission_words(self._words),
            confidence=self._asr_confidence,
            response_started_at_ms=self._response_started_ms,
            fragment_started_at_ms=self._turn_started_ms,
        )
        await self.recorder.pause_segment(preserve=True)
        self._preserve_recording = True
        self._reset_turn(keep_response_start=True)

        if not explicit_done:
            # If LiveKit cancels this generation because more speech arrives,
            # the accumulator remains intact for the next committed fragment.
            await asyncio.sleep(self._collection_delay)
        if not self._pending_response.claim(generation):
            return

        transcript = self._pending_response.transcript
        self._words = list(self._pending_response.words)
        self._asr_confidence = self._pending_response.confidence
        self._response_started_ms = self._pending_response.response_started_at_ms
        self._set_input_enabled(False)

        response_id = f"response-{uuid.uuid4()}"
        ended_ms = int(time.time() * 1000)
        store_all_audio = os.getenv("STORE_ALL_ASSESSMENT_AUDIO", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        audio_uri = await self.recorder.stop_and_upload(
            self.assessment_id,
            response_id,
            upload=store_all_audio,
        )
        payload = self._payload(
            prompt=prompt,
            response_id=response_id,
            transcript=transcript,
            audio_uri=audio_uri,
            ended_ms=ended_ms,
        )
        logger.info(
            "[ASSESSMENT RESPONSE] prompt=%s | transcript=%r | timed-words=%d",
            prompt["prompt_id"],
            transcript,
            len(payload["words"]),
        )
        self._reset_turn()

        try:
            if prompt["prompt_kind"] != "calibration":
                yield "Thank you. "
            result = await self._submit_with_schema_recovery(payload)
            yield await self._next_spoken_text(result)
        except AssessmentServiceUnavailable:
            logger.exception("Assessment service is unavailable")
            self._defer_submission(payload)
            yield self._deferred_message()
        except AssessmentHTTPError as exc:
            if exc.status_code == 409 and "completed" in exc.detail.lower():
                logger.warning("Late transcript arrived after assessment completion; returning result")
                yield await self._next_spoken_text({"next_action": {"prompt": None}})
                return
            if exc.status_code == 409:
                logger.warning("Stale prompt detected; resynchronizing assessment state")
                try:
                    yield await self._recover_session_state()
                except AssessmentClientError:
                    logger.exception("Assessment state recovery failed")
                    yield SERVICE_UNAVAILABLE_MESSAGE
                return
            if exc.status_code >= 500:
                logger.warning(
                    "Assessment scoring deferred: status=%s code=%s retry_after=%s",
                    exc.status_code,
                    exc.error_code,
                    exc.retry_after_seconds,
                )
                self._defer_submission(payload, error=exc)
                yield self._deferred_message()
                return
            logger.exception("Assessment service rejected the current response")
            try:
                yield await self._recover_session_state()
            except AssessmentClientError:
                logger.exception("Assessment recovery after HTTP failure failed")
                self._defer_submission(payload)
                yield self._deferred_message()
        except AssessmentClientError:
            logger.exception("Unexpected assessment client failure")
            self._defer_submission(payload)
            yield self._deferred_message()
        finally:
            if not self._assessment_completed:
                self._set_input_enabled(True)


server = AgentServer()


@server.rtc_session(agent_name="english-level-assessor")
async def assessment_session(ctx: agents.JobContext) -> None:
    if os.getenv("ASSESSMENT_SERVICE_ENABLED", "true").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise RuntimeError("Assessment service integration is disabled")
    runtime_settings = get_settings()
    runtime_settings.require_agent_environment(include_database=False)
    client = AssessmentClient()
    user_id = ctx.room.name or f"livekit-{uuid.uuid4()}"
    service_available = True
    try:
        created = await client.create_assessment_async(user_id)
    except AssessmentClientError:
        logger.exception("Could not create assessment")
        service_available = False
        created = {
            "assessment_id": "assessment-service-unavailable",
            "current_item": {
                "prompt_id": "UNAVAILABLE",
                "item_id": "UNAVAILABLE",
                "target_level": None,
                "prompt_kind": "calibration",
                "prompt": SERVICE_UNAVAILABLE_MESSAGE,
                "response_limit_seconds": 30,
                "prompt_repetitions_allowed": 0,
            },
        }

    recorder = RawAudioSegmentRecorder(client)
    assessor = LevelAssessmentAgent(
        client,
        recorder,
        created["assessment_id"],
        created["current_item"],
        service_available=service_available,
    )

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            recorder.attach_track(track)

    session = AgentSession(
        stt=build_assessment_stt(),
        vad=build_vad(),
        # This model is never called: LevelAssessmentAgent overrides llm_node.
        llm=inference.LLM(model=runtime_settings.livekit_llm_model),
        tts=build_tts(runtime_settings),
        tts_text_transforms=["filter_markdown", "filter_emoji"],
        turn_handling=TurnHandlingOptions(
            turn_detection="stt",
            endpointing=assessment_endpointing_options(),
            interruption={
                "enabled": True,
                "mode": "vad",
                "min_duration": env_float(
                    "ASSESSMENT_MIN_INTERRUPTION_DURATION_SECONDS", 0.50
                ),
                "min_words": 1,
                "false_interruption_timeout": 1.50,
                "resume_false_interruption": True,
            },
            preemptive_generation={"enabled": False},
        ),
        conn_options=SessionConnectOptions(
            tts_conn_options=APIConnectOptions(
                max_retry=env_int("ASSESSMENT_TTS_MAX_RETRIES", 4),
                retry_interval=2.0,
                timeout=env_float("ASSESSMENT_TTS_TIMEOUT_SECONDS", 20.0),
            )
        ),
        aec_warmup_duration=runtime_settings.aec_warmup_seconds,
        user_away_timeout=None,
    )
    assessor.bind_session(session)

    @session.on("user_state_changed")
    def on_user_state_changed(event) -> None:
        if str(event.new_state).lower().endswith("speaking"):
            assessor.mark_user_speaking()

    await session.start(
        room=ctx.room,
        agent=assessor,
        room_options=room_io.RoomOptions(
            audio_input=build_assessment_audio_input_options()
        ),
    )
    await session.say(
        spoken_prompt(created["current_item"]),
        allow_interruptions=False,
        add_to_chat_ctx=False,
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
