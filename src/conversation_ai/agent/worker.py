from __future__ import annotations

import logging
import threading

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

from ..config import get_settings
from ..log_config import configure_logging
from ..metadata import parse_job_metadata
from ..persistence.serialization import sanitize_json
from .persistence import JobPersistence
from .pipeline import (
    TTS_TEXT_TRANSFORMS,
    EnglishTutor,
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


@server.rtc_session(agent_name="english-tutor", on_session_end=on_session_end)
async def english_tutor_session(ctx: agents.JobContext) -> None:
    settings.require_agent_environment()
    metadata = parse_job_metadata(
        getattr(ctx.job, "metadata", ""),
        production=settings.is_production,
    )

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
            },
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
        add_observability(session, persistence)

        await session.start(
            room=ctx.room,
            agent=EnglishTutor(),
            room_options=room_io.RoomOptions(
                audio_input=build_audio_input_options(settings)
            ),
        )
        logger.info("session_ready", extra={"session_id": str(metadata.session_id)})
    except Exception as exc:
        await persistence.fail_before_session_end(exc)
        raise


def add_observability(session: AgentSession, persistence: JobPersistence) -> None:
    session_id = str(persistence.metadata.session_id)

    @session.on("conversation_item_added")
    def on_conversation_item_added(event: ConversationItemAddedEvent) -> None:
        item = event.item
        if not isinstance(item, ChatMessage):
            return
        persistence.record_turn(item, occurred_at=event.created_at)
        logger.info(
            "conversation_turn",
            extra={
                "session_id": session_id,
                "item_id": item.id,
                "role": getattr(item.role, "value", str(item.role)),
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
