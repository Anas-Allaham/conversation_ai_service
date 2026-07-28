from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from conversation_ai.metadata import SessionJobMetadata
from conversation_ai.persistence.models import ConversationTurn, SessionEvent
from conversation_ai.persistence.repository import SessionRepository


async def test_repository_persists_and_hard_deletes_full_subject(database) -> None:
    repo = SessionRepository(database.session_factory)
    subject_id = uuid.uuid4()
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()

    for offset, session_id in enumerate((first_id, second_id)):
        metadata = SessionJobMetadata(
            schema_version=1,
            session_id=session_id,
            subject_id=subject_id,
            locale="en",
        )
        await repo.create_session(
            metadata,
            job_id=f"job-{offset}",
            room_name=f"room-{offset}",
            room_sid=f"sid-{offset}",
            started_at=datetime.now(UTC) + timedelta(seconds=offset),
        )

    await repo.upsert_turn(
        session_id=first_id,
        item_id="item-1",
        sequence=1,
        role="user",
        text="Hello",
        interrupted=False,
        metrics={"transcription_delay": 0.2},
        occurred_at=datetime.now(UTC),
    )
    await repo.append_event(
        session_id=first_id,
        sequence=1,
        event_type="agent_state_changed",
        payload={"old_state": "listening", "new_state": "thinking"},
        occurred_at=datetime.now(UTC),
    )

    sessions = await repo.list_subject_sessions(
        subject_id, before_at=None, before_id=None, limit=10
    )
    assert [row.session_id for row in sessions] == [second_id, first_id]
    assert (await repo.list_turns(first_id))[0].text == "Hello"
    assert (await repo.list_events(first_id))[0].event_type == "agent_state_changed"

    assert await repo.delete_subject(subject_id) == 2
    assert await repo.get_session(first_id) is None
    async with database.session() as session:
        turn_count = await session.scalar(select(func.count()).select_from(ConversationTurn))
        event_count = await session.scalar(select(func.count()).select_from(SessionEvent))
    assert turn_count == 0
    assert event_count == 0


async def test_turn_upsert_reconciles_final_metrics(database) -> None:
    repo = SessionRepository(database.session_factory)
    metadata = SessionJobMetadata(
        schema_version=1,
        session_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
    )
    await repo.create_session(metadata, job_id="job", room_name="room", room_sid=None)
    common = {
        "session_id": metadata.session_id,
        "item_id": "same-item",
        "sequence": 1,
        "role": "assistant",
        "text": "Response",
        "interrupted": False,
        "occurred_at": datetime.now(UTC),
    }
    await repo.upsert_turn(**common, metrics={"llm_node_ttft": 0.4})
    await repo.upsert_turn(**common, metrics={"llm_node_ttft": 0.2, "tts_node_ttfb": 0.1})

    rows = await repo.list_turns(metadata.session_id)
    assert len(rows) == 1
    assert rows[0].metrics["tts_node_ttfb"] == 0.1

