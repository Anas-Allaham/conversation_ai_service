from __future__ import annotations

import logging
import threading
from pathlib import Path

from livekit import agents
from livekit.agents import (
    AgentServer,
    AgentSession,
    AgentStateChangedEvent,
    ConversationItemAddedEvent,
    ErrorEvent,
    room_io,
)
from livekit.agents.llm import ChatMessage

from app.realtime.conversation_fluency import ConversationFluencyTracker
from app.realtime.guided_conversation import run_guided_conversation_session
from app.realtime.piper_tts import PiperTTS
from app.services.assessment_client import AssessmentClient, AssessmentClientError
from services.fluency.models import PracticeMode

from ..config import get_settings
from ..log_config import configure_logging
from ..metadata import parse_worker_job_metadata
from ..persistence.serialization import sanitize_json
from .persistence import JobPersistence
from .pipeline import (
    TTS_TEXT_TRANSFORMS,
    FluencyTrackingTutor,
    build_audio_input_options,
    build_llm,
    build_stt,
    build_tts,
    build_turn_handling_options,
    build_vad,
)

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("conversation-ai.worker")

PERSISTENCE_KEY = "conversation_ai_job_persistence"
SESSION_KEY = "conversation_ai_agent_session"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


async def on_session_end(ctx: agents.JobContext) -> None:
    persistence: JobPersistence | None = ctx.proc.userdata.pop(PERSISTENCE_KEY, None)
    session: AgentSession | None = ctx.proc.userdata.pop(SESSION_KEY, None)
    if persistence is None:
        return

    try:
        if session is None:
            # Startup can fail after the database row is created but before an
            # AgentSession exists. There is no LiveKit report to build in that
            # case; fail_before_session_end() has already marked the row failed.
            await persistence.flush()
            logger.info(
                "session_report_unavailable",
                extra={"session_id": str(persistence.metadata.session_id)},
            )
            return

        report = ctx.make_session_report(session)
        history_items = list(session.history.items)
        await persistence.finalize(report=report, history_items=history_items)
        logger.info(
            "session_persisted",
            extra={"session_id": str(persistence.metadata.session_id)},
        )
    except Exception as exc:
        logger.exception(
            "session_finalization_failed",
            extra={
                "session_id": str(persistence.metadata.session_id),
                "error_type": type(exc).__name__,
            },
        )
    finally:
        await persistence.close()


server = AgentServer(
    shutdown_process_timeout=20.0,
    session_end_timeout=60.0,
)


@server.rtc_session(agent_name=settings.livekit_agent_name, on_session_end=on_session_end)
async def english_tutor_session(ctx: agents.JobContext) -> None:
    settings.require_agent_environment()
    worker_metadata = parse_worker_job_metadata(
        getattr(ctx.job, "metadata", ""),
        production=settings.is_production,
    )
    metadata = worker_metadata.session

    job_id = getattr(ctx.job, "id", None)
    job_room = getattr(ctx.job, "room", None)
    room_sid = getattr(job_room, "sid", None)
    persistence = JobPersistence(
        settings.database_url.get_secret_value(),
        metadata,
    )
    await persistence.start(
        job_id=job_id,
        room_name=ctx.room.name,
        room_sid=room_sid,
    )
    ctx.proc.userdata[PERSISTENCE_KEY] = persistence

    try:
        logger.info(
            "session_starting",
            extra={
                "session_id": str(metadata.session_id),
                "subject_id": str(metadata.subject_id),
                "room": ctx.room.name,
                "worker_thread": threading.current_thread().name,
                "conversation_mode": worker_metadata.conversation_mode,
                "metadata_source": worker_metadata.source,
            },
        )

        if worker_metadata.conversation_mode == PracticeMode.GUIDED.value:
            def observe_guided_turn(turn: dict[str, object]) -> None:
                attempt_id = str(turn.get("attempt_id") or "guided-attempt")
                shared_metrics = {
                    "conversation_mode": "guided",
                    "turn_id": turn.get("turn_id"),
                    "expected_learner_text": turn.get("expected_learner_text"),
                    "words": turn.get("words"),
                }
                persistence.record_text_turn(
                    item_id=f"{attempt_id}:assistant",
                    role="assistant",
                    text=str(turn.get("assistant_text") or ""),
                    metrics=shared_metrics,
                )
                persistence.record_text_turn(
                    item_id=f"{attempt_id}:user",
                    role="user",
                    text=str(turn.get("learner_transcript") or ""),
                    metrics=shared_metrics,
                )

            await run_guided_conversation_session(
                ctx,
                stt=build_stt(settings),
                vad=build_vad(),
                tts=PiperTTS(PROJECT_ROOT),
                audio_input_options=build_audio_input_options(settings),
                aec_warmup_duration=settings.aec_warmup_seconds,
                turn_observer=observe_guided_turn,
            )
            guided_session_id = worker_metadata.guided_session_id
            report: dict[str, object] = {
                "conversation_mode": "guided",
                "guided_session_id": guided_session_id,
            }
            if guided_session_id:
                try:
                    report["learner_result"] = (
                        await AssessmentClient().get_guided_learner_result_async(
                            guided_session_id
                        )
                    )
                except AssessmentClientError as exc:
                    logger.warning("guided_final_report_unavailable: %s", exc)
            persistence.record_event("guided_session_finished", report)
            await persistence.finalize_external(report)
            ctx.proc.userdata.pop(PERSISTENCE_KEY, None)
            await persistence.close()
            return

        fluency_tracker = ConversationFluencyTracker(
            session_id=worker_metadata.practice_session_id or str(metadata.session_id),
            mode=PracticeMode.FREE,
        )

        session = AgentSession(
            stt=build_stt(settings),
            vad=build_vad(),
            llm=build_llm(settings),
            tts=build_tts(settings),
            tts_text_transforms=TTS_TEXT_TRANSFORMS,
            turn_handling=build_turn_handling_options(),
            aec_warmup_duration=settings.aec_warmup_seconds,
            user_away_timeout=None,
        )
        ctx.proc.userdata[SESSION_KEY] = session
        add_observability(session, persistence, fluency_tracker)

        @session.on("user_state_changed")
        def on_user_state_changed(event) -> None:
            if str(event.new_state).lower().endswith("speaking"):
                fluency_tracker.mark_user_speaking()

        await session.start(
            room=ctx.room,
            agent=FluencyTrackingTutor(fluency_tracker),
            room_options=room_io.RoomOptions(audio_input=build_audio_input_options(settings)),
        )
        logger.info("session_ready", extra={"session_id": str(metadata.session_id)})
    except Exception as exc:
        await persistence.fail_before_session_end(exc)
        raise


def add_observability(
    session: AgentSession,
    persistence: JobPersistence,
    fluency_tracker: ConversationFluencyTracker | None = None,
) -> None:
    session_id = str(persistence.metadata.session_id)

    @session.on("conversation_item_added")
    def on_conversation_item_added(event: ConversationItemAddedEvent) -> None:
        item = event.item
        if not isinstance(item, ChatMessage):
            return
        persistence.record_turn(item, occurred_at=event.created_at)
        role = getattr(item.role, "value", str(item.role))
        if role == "user" and fluency_tracker is not None:
            transcript = str(item.text_content or "").strip()
            if transcript:
                import asyncio

                asyncio.create_task(fluency_tracker.submit_turn(transcript, item.id))
        logger.info(
            "conversation_turn",
            extra={
                "session_id": session_id,
                "item_id": item.id,
                "role": role,
                "interrupted": bool(item.interrupted),
                "metrics": sanitize_json(getattr(item, "metrics", {}) or {}),
            },
        )

    @session.on("agent_state_changed")
    def on_agent_state_changed(event: AgentStateChangedEvent) -> None:
        persistence.record_event(
            "agent_state_changed",
            {"old_state": event.old_state, "new_state": event.new_state},
            occurred_at=event.created_at,
        )
        logger.info(
            "agent_state_changed",
            extra={
                "session_id": session_id,
                "old_state": event.old_state,
                "new_state": event.new_state,
            },
        )

    @session.on("error")
    def on_error(event: ErrorEvent) -> None:
        recoverable = bool(
            getattr(event, "recoverable", getattr(event.error, "recoverable", False))
        )
        persistence.record_error(
            error=event.error,
            source=event.source,
            recoverable=recoverable,
            occurred_at=event.created_at,
        )
        logger.error(
            "session_error",
            extra={
                "session_id": session_id,
                "error_type": type(event.error).__name__,
                "source": type(event.source).__name__,
                "recoverable": recoverable,
            },
        )
