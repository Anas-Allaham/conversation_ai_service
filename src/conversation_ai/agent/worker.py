from __future__ import annotations

import asyncio
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

from app.realtime.conversation_fluency import ConversationFluencyTracker
from app.realtime.guided_conversation import run_guided_conversation_session
from services.fluency.models import PracticeMode

from ..config import get_settings
from ..log_config import configure_logging
from ..metadata import (
    PracticeJobMetadata,
    SessionJobMetadata,
    parse_tutor_job_metadata,
)
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


async def on_session_end(ctx: agents.JobContext) -> None:
    persistence: JobPersistence | None = ctx.proc.userdata.pop(PERSISTENCE_KEY, None)
    session: AgentSession | None = ctx.proc.userdata.pop(SESSION_KEY, None)
    if persistence is None:
        return

    try:
        if session is None:
            await persistence.flush()
            logger.info(
                "session_report_unavailable",
                extra={"session_id": str(persistence.metadata.session_id)},
            )
            return

        report = ctx.make_session_report(session)
        await persistence.finalize(report=report, history_items=list(session.history.items))
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
    metadata = parse_tutor_job_metadata(
        getattr(ctx.job, "metadata", ""),
        production=settings.is_production,
    )
    is_main_session = isinstance(metadata, SessionJobMetadata)
    settings.require_agent_environment(include_database=is_main_session)

    mode = (
        PracticeMode(metadata.conversation_mode)
        if isinstance(metadata, PracticeJobMetadata)
        else PracticeMode.FREE
    )
    logger.info(
        "session_starting",
        extra={
            "room": ctx.room.name,
            "mode": mode.value,
            "contract": "main" if is_main_session else "practice",
            "worker_thread": threading.current_thread().name,
        },
    )

    if mode == PracticeMode.GUIDED:
        await run_guided_conversation_session(
            ctx,
            stt=build_stt(settings),
            vad=build_vad(),
            tts=build_tts(settings),
            audio_input_options=build_audio_input_options(settings),
            aec_warmup_duration=settings.aec_warmup_seconds,
        )
        return

    persistence: JobPersistence | None = None
    if isinstance(metadata, SessionJobMetadata):
        job_room = getattr(ctx.job, "room", None)
        persistence = JobPersistence(
            settings.database_url.get_secret_value(),
            metadata,
        )
        await persistence.start(
            job_id=getattr(ctx.job, "id", None),
            room_name=ctx.room.name,
            room_sid=getattr(job_room, "sid", None),
        )
        ctx.proc.userdata[PERSISTENCE_KEY] = persistence

    tracker_session_id = (
        metadata.practice_session_id
        if isinstance(metadata, PracticeJobMetadata)
        else ctx.room.name
    )
    tracker = ConversationFluencyTracker(
        session_id=tracker_session_id,
        mode=PracticeMode.FREE,
    )

    try:
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
        add_observability(session, persistence=persistence, tracker=tracker)

        @session.on("user_state_changed")
        def on_user_state_changed(event) -> None:
            if str(event.new_state).lower().endswith("speaking"):
                tracker.mark_user_speaking()

        await session.start(
            room=ctx.room,
            agent=FluencyTrackingTutor(tracker),
            room_options=room_io.RoomOptions(
                audio_input=build_audio_input_options(settings)
            ),
        )
        logger.info("session_ready", extra={"room": ctx.room.name, "mode": mode.value})
    except Exception as exc:
        if persistence is not None:
            await persistence.fail_before_session_end(exc)
        raise


def add_observability(
    session: AgentSession,
    *,
    persistence: JobPersistence | None,
    tracker: ConversationFluencyTracker,
) -> None:
    session_id = (
        str(persistence.metadata.session_id) if persistence is not None else tracker.session_id
    )

    @session.on("conversation_item_added")
    def on_conversation_item_added(event: ConversationItemAddedEvent) -> None:
        item = event.item
        if not isinstance(item, ChatMessage):
            return

        if persistence is not None:
            persistence.record_turn(item, occurred_at=event.created_at)

        role = getattr(item.role, "value", str(item.role))
        if role == "user":
            content = getattr(item, "text_content", "")
            if callable(content):
                content = content()
            transcript = str(content or "").strip()
            if transcript:
                turn_id = str(
                    getattr(item, "id", None)
                    or getattr(item, "item_id", None)
                    or f"turn-{threading.get_ident()}-{id(item)}"
                )
                asyncio.create_task(tracker.submit_turn(transcript, turn_id))

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
        if persistence is not None:
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
        if persistence is not None:
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
