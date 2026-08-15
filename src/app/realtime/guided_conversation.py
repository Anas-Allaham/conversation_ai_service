from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterable, Callable
from typing import Any

from livekit import agents, rtc
from livekit.agents import Agent, AgentSession, TurnHandlingOptions, llm, room_io

from app.realtime.assessment_payload import (
    extract_words,
    optional_confidence,
    read_value,
    valid_submission_words,
)
from app.realtime.conversation_fluency import conversation_metadata
from app.services.assessment_client import AssessmentClient, AssessmentClientError
from app.services.raw_audio import RawAudioSegmentRecorder

logger = logging.getLogger("english-tutor.guided")

GUIDED_INSTRUCTIONS = """
This is a deterministic guided role-play runtime.
Never generate content with a language model. Every spoken response is supplied
by the versioned scenario service.
"""


class DisabledGuidedLLM(llm.LLM):
    """Satisfy LiveKit's reply scheduler without configuring an LLM provider."""

    @property
    def model(self) -> str:
        return "disabled-guided-runtime"

    @property
    def provider(self) -> str:
        return "local-deterministic"

    def chat(self, **_kwargs):
        raise RuntimeError("Guided progression cannot call an LLM")


def guided_session_id(source: Any) -> str:
    metadata = conversation_metadata(source)
    session_id = metadata.get("guided_session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise RuntimeError(
            "Guided LiveKit rooms require metadata.guided_session_id from the backend"
        )
    return session_id.strip()


def _message_text(message: Any) -> str:
    value = getattr(message, "text_content", "")
    if callable(value):
        value = value()
    return str(value or "").strip()


def _recognition_feedback(
    transcript: str,
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build ephemeral word colors without treating ASR confidence as pronunciation."""
    if not words:
        return [
            {
                "text": token,
                "recognition_confidence_percent": None,
                "color_band": "white",
            }
            for token in re.findall(r"\S+", transcript)
        ]
    feedback: list[dict[str, Any]] = []
    for word in words:
        confidence = optional_confidence(word.get("confidence"))
        percent = round(confidence * 100) if confidence is not None else None
        band = (
            "red"
            if percent is not None and percent < 25
            else "orange"
            if percent is not None and percent < 75
            else "white"
        )
        feedback.append(
            {
                "text": str(word.get("word") or ""),
                "recognition_confidence_percent": percent,
                "color_band": band,
            }
        )
    return feedback


class GuidedRuntimeController:
    def __init__(
        self,
        room: Any,
        session_id: str,
        client: AssessmentClient,
        recorder: RawAudioSegmentRecorder,
        turn_observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.room = room
        self.session_id = session_id
        self.client = client
        self.recorder = recorder
        self.turn_observer = turn_observer
        self.view: dict[str, Any] = {}
        self._words: list[dict[str, Any]] = []
        self._asr_confidence: float | None = None
        self._turn_started_ms: int | None = None
        self._prompt_available_ms: int | None = None
        self._pending_spoken_reply = ""
        self._closed = asyncio.Event()

    async def initialize(self) -> str:
        self.view = await self.client.get_guided_session_async(self.session_id)
        current = self.view.get("current_turn") or {}
        if self.view.get("state") == "assistant_speaking":
            return str(current.get("assistant_spoken_text") or "")
        if self.view.get("state") in {"user_prompt_visible", "awaiting_retry_decision"}:
            return "Please continue with the line shown on screen."
        return ""

    @property
    def is_terminal(self) -> bool:
        return self.view.get("status") in {"completed", "stopped"}

    @property
    def is_paused(self) -> bool:
        return self.view.get("state") == "paused"

    async def wait_closed(self) -> None:
        await self._closed.wait()

    def mark_closed(self) -> None:
        self._closed.set()

    async def publish(self, event: dict[str, Any]) -> None:
        try:
            await self.room.local_participant.publish_data(
                json.dumps(event, ensure_ascii=False),
                reliable=True,
                topic="guided.events",
            )
        except Exception:
            logger.exception("Could not publish a guided conversation event")

    async def publish_session_ready(self) -> None:
        await self.publish(
            {
                "type": "guided.session_ready",
                "data": self.view,
            }
        )

    async def mark_prompt_available(self) -> None:
        if self.is_terminal or self.is_paused:
            return
        state = self.view.get("state")
        if state == "assistant_speaking":
            try:
                self.view = await self.client.mark_guided_prompt_ready_async(self.session_id)
            except AssessmentClientError:
                logger.exception("Could not mark the guided learner prompt ready")
                return
        if self.view.get("state") == "user_prompt_visible":
            self._prompt_available_ms = int(time.time() * 1000)
            await self.publish(
                {
                    "type": "guided.learner_prompt_active",
                    "data": self.view,
                }
            )

    def mark_user_speaking(self) -> None:
        if self.is_terminal or self.is_paused:
            return
        if self._turn_started_ms is None:
            self._turn_started_ms = int(time.time() * 1000)
            asyncio.create_task(self.recorder.start_segment())

    def observe_stt_event(self, event: Any) -> None:
        alternatives = read_value(event, "alternatives", default=[]) or []
        if not alternatives:
            return
        alternative = alternatives[0]
        words = extract_words(read_value(alternative, "words", default=[]))
        if words:
            self._words = words
        confidence = optional_confidence(read_value(alternative, "confidence"))
        if confidence is not None:
            self._asr_confidence = confidence

    def _reset_turn_evidence(self) -> None:
        self._words = []
        self._asr_confidence = None
        self._turn_started_ms = None

    async def handle_user_turn(self, transcript: str) -> None:
        if self.is_terminal or self.is_paused:
            self._pending_spoken_reply = ""
            self._reset_turn_evidence()
            return
        normalized = " ".join(transcript.lower().split()).strip(" .!?،")
        if self.view.get("state") == "awaiting_retry_decision" and normalized in {
            "continue",
            "continue please",
            "skip",
        }:
            await self.handle_command("continue")
            return
        if self.view.get("state") == "awaiting_retry_decision" and normalized in {
            "retry",
            "try again",
        }:
            await self.handle_command("retry")
            return

        current = self.view.get("current_turn") or {}
        turn_id = str(current.get("turn_id") or "")
        if not turn_id:
            self._pending_spoken_reply = ""
            return
        attempt_id = f"attempt-{uuid.uuid4()}"
        idempotency_key = f"guided-{uuid.uuid4()}"
        await self.recorder.stop_and_upload_guided(
            self.session_id,
            attempt_id,
            upload=bool(self.view.get("recording_consent")),
        )
        submission_words = valid_submission_words(self._words)
        payload = {
            "attempt_id": attempt_id,
            "idempotency_key": idempotency_key,
            "turn_id": turn_id,
            "transcript": transcript,
            "words": submission_words,
            "prompt_available_at_ms": self._prompt_available_ms,
            "response_started_at_ms": self._turn_started_ms,
            "response_ended_at_ms": int(time.time() * 1000),
            "asr_confidence": self._asr_confidence,
            "completed": True,
            "explicit_audio_issue": False,
            "audio_issue_reason": None,
        }
        self._reset_turn_evidence()
        try:
            result = await self.client.submit_guided_attempt_async(self.session_id, payload)
        except AssessmentClientError:
            logger.exception("The guided attempt could not be stored")
            self._pending_spoken_reply = (
                "I could not save that line. Please wait a moment and try the same line again."
            )
            await self.publish(
                {
                    "type": "guided.error",
                    "data": {
                        "session_id": self.session_id,
                        "code": "attempt_not_saved",
                        "recoverable": True,
                    },
                }
            )
            return
        self.view = result.get("session") or self.view
        self._pending_spoken_reply = str(result.get("spoken_reply") or "")
        conversation_turn = {
            "attempt_id": attempt_id,
            "turn_id": turn_id,
            "assistant_text": str(current.get("assistant_display_text") or ""),
            "expected_learner_text": str(current.get("learner_display_text") or ""),
            "learner_transcript": transcript,
            "words": _recognition_feedback(transcript, submission_words),
            "recognition_confidence_interpretation": (
                "STT recognition confidence for debugging; not pronunciation accuracy."
            ),
        }
        if self.turn_observer is not None:
            self.turn_observer(conversation_turn)
        event = result.get("live_event")
        if isinstance(event, dict):
            data = event.setdefault("data", {})
            if isinstance(data, dict):
                data["conversation_turn"] = conversation_turn
                data["assistant_reply"] = self._pending_spoken_reply
            await self.publish(event)

    async def handle_command(self, command: str) -> str:
        if command in {"replay", "replay_slow"}:
            if self.is_terminal or self.is_paused:
                return ""
            current = self.view.get("current_turn") or {}
            spoken = str(current.get("assistant_spoken_text") or "")
            if not spoken:
                return "That line is no longer available."
            if command == "replay_slow":
                # Commas create deterministic TTS pacing without generating or
                # paraphrasing the versioned scenario text.
                words = re.findall(r"\S+", spoken)
                spoken = ", ".join(words)
            await self.publish(
                {
                    "type": "guided.line_replayed",
                    "data": {
                        "session_id": self.session_id,
                        "turn_id": current.get("turn_id"),
                        "speed": "slow" if command == "replay_slow" else "normal",
                    },
                }
            )
            return spoken
        try:
            result = await self.client.guided_control_async(self.session_id, command)
        except (AssessmentClientError, ValueError):
            logger.exception("Guided command failed: %s", command)
            spoken = "That action is not available right now."
            self._pending_spoken_reply = spoken
            return spoken
        self.view = result.get("session") or self.view
        spoken = str(result.get("spoken_reply") or "")
        self._pending_spoken_reply = spoken
        event = result.get("live_event")
        if isinstance(event, dict):
            data = event.setdefault("data", {})
            if isinstance(data, dict):
                data["assistant_reply"] = spoken
            await self.publish(event)
        return spoken

    def consume_spoken_reply(self) -> str:
        reply = self._pending_spoken_reply
        self._pending_spoken_reply = ""
        return reply


class GuidedConversationAgent(Agent):
    def __init__(self, controller: GuidedRuntimeController) -> None:
        super().__init__(instructions=GUIDED_INSTRUCTIONS)
        self.controller = controller

    async def stt_node(self, audio, model_settings) -> AsyncIterable[Any]:
        async for event in Agent.default.stt_node(self, audio, model_settings):
            self.controller.observe_stt_event(event)
            yield event

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        await self.controller.handle_user_turn(_message_text(new_message))

    async def llm_node(self, chat_ctx, tools, model_settings) -> str:
        # The session owns a placeholder model because LiveKit's pipeline needs
        # an LLM object to schedule replies. This override guarantees that the
        # provider is never called during guided progression.
        return self.controller.consume_spoken_reply()


async def run_guided_conversation_session(
    ctx: agents.JobContext,
    *,
    stt,
    vad,
    tts,
    audio_input_options: room_io.AudioInputOptions,
    aec_warmup_duration: float,
    turn_observer: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    session_id = guided_session_id(ctx)
    client = AssessmentClient()
    recorder = RawAudioSegmentRecorder(client)
    controller = GuidedRuntimeController(
        ctx.room,
        session_id,
        client,
        recorder,
        turn_observer=turn_observer,
    )
    initial_spoken_text = await controller.initialize()
    guided_agent = GuidedConversationAgent(controller)
    close_lock = asyncio.Lock()
    session_closed = False

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            recorder.attach_track(track)

    @ctx.room.on("data_received")
    def on_data_received(packet) -> None:
        if packet.topic != "guided.command":
            return
        try:
            payload = json.loads(packet.data.decode("utf-8"))
            command = str(payload.get("command") or "").lower()
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return
        if command not in {
            "retry",
            "continue",
            "replay",
            "replay_slow",
            "pause",
            "resume",
            "stop",
        }:
            return

        async def apply_command() -> None:
            spoken = await controller.handle_command(command)
            if command == "pause":
                try:
                    await session.interrupt(force=True)
                except RuntimeError:
                    pass
                await recorder.pause_segment(preserve=False)
            if spoken:
                handle = session.say(
                    spoken,
                    allow_interruptions=False,
                    add_to_chat_ctx=False,
                )
                if command == "stop":
                    await handle.wait_for_playout()
            if controller.is_terminal:
                await close_guided_session()

        asyncio.create_task(apply_command())

    session = AgentSession(
        stt=stt,
        vad=vad,
        # LiveKit's auto-reply scheduler requires an LLM-shaped object before it
        # invokes the agent's overridden llm_node. This local adapter has no
        # provider, credentials, network path, or generation capability.
        llm=DisabledGuidedLLM(),
        tts=tts,
        tts_text_transforms=["filter_markdown", "filter_emoji"],
        turn_handling=TurnHandlingOptions(
            turn_detection="stt",
            endpointing={"mode": "fixed", "min_delay": 0.25, "max_delay": 1.25},
            interruption={
                "enabled": True,
                "mode": "vad",
                "min_duration": 0.40,
                "min_words": 0,
                "false_interruption_timeout": 1.50,
                "resume_false_interruption": True,
            },
            preemptive_generation={"enabled": False},
        ),
        aec_warmup_duration=aec_warmup_duration,
        user_away_timeout=None,
    )

    @session.on("user_state_changed")
    def on_user_state_changed(event) -> None:
        if str(event.new_state).lower().endswith("speaking"):
            controller.mark_user_speaking()

    @session.on("agent_state_changed")
    def on_agent_state_changed(event) -> None:
        if str(event.old_state).lower().endswith("speaking") and str(
            event.new_state
        ).lower().endswith("listening"):
            if controller.is_terminal:
                asyncio.create_task(close_guided_session())
            else:
                asyncio.create_task(controller.mark_prompt_available())

    async def close_guided_session() -> None:
        nonlocal session_closed
        async with close_lock:
            if session_closed:
                return
            session_closed = True
            await recorder.pause_segment(preserve=False)
            await controller.publish(
                {
                    "type": "guided.session_closed",
                    "data": {
                        "session_id": controller.session_id,
                        "status": controller.view.get("status"),
                        "reason": "completed"
                        if controller.view.get("status") == "completed"
                        else "stopped",
                    },
                }
            )
            session.shutdown(drain=False)
            await ctx.room.disconnect()
            controller.mark_closed()
            ctx.shutdown("guided conversation ended")

    @ctx.room.on("disconnected")
    def on_room_disconnected(*_args: Any) -> None:
        controller.mark_closed()

    await session.start(
        room=ctx.room,
        agent=guided_agent,
        room_options=room_io.RoomOptions(audio_input=audio_input_options),
    )
    await controller.publish_session_ready()
    if controller.is_terminal:
        await close_guided_session()
    elif initial_spoken_text:
        await session.say(
            initial_spoken_text,
            allow_interruptions=False,
            add_to_chat_ctx=False,
        )
    await controller.wait_closed()
