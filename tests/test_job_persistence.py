from __future__ import annotations

import uuid
from pathlib import Path

from livekit.agents.llm import ChatMessage

from conversation_ai.agent.persistence import JobPersistence
from conversation_ai.metadata import SessionJobMetadata


class FakeReport:
    model_usage = [{"provider": "deepgram", "audio_seconds": 2.5}]

    def to_dict(self):
        return {
            "job_id": "job-1",
            "audio_recording_path": Path("private.wav"),
            "api_key": "must-not-persist",
            "chat_history": {"items": [{"role": "user", "content": ["Hello"]}]},
        }


async def test_job_persistence_reconciles_report_without_audio_or_secrets(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'job.db').as_posix()}"
    metadata = SessionJobMetadata(
        schema_version=1,
        session_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
    )
    persistence = JobPersistence(database_url, metadata)
    await persistence.database.create_schema_for_tests()
    try:
        await persistence.start(job_id="job-1", room_name="room-1", room_sid="RM_1")
        message = ChatMessage(
            id="item-1",
            role="user",
            content=["Hello"],
            metrics={"transcription_delay": 0.2},
        )
        persistence.record_turn(message)
        await persistence.finalize(report=FakeReport(), history_items=[message])

        row = await persistence.repository.get_session(metadata.session_id)
        assert row is not None
        assert row.status == "completed"
        assert row.final_report == {
            "job_id": "job-1",
            "chat_history": {"items": [{"role": "user", "content": ["Hello"]}]},
        }
        assert row.model_usage == [{"provider": "deepgram", "audio_seconds": 2.5}]
        turns = await persistence.repository.list_turns(metadata.session_id)
        assert len(turns) == 1
        assert turns[0].text == "Hello"
    finally:
        await persistence.close()


async def test_guided_text_turns_are_available_through_team_persistence(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'guided.db').as_posix()}"
    metadata = SessionJobMetadata(
        schema_version=1,
        session_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        conversation_mode="guided",
        practice_session_id="guided-example",
        guided_session_id="guided-example",
    )
    persistence = JobPersistence(database_url, metadata)
    await persistence.database.create_schema_for_tests()
    try:
        await persistence.start(job_id="job-guided", room_name="guided-example", room_sid=None)
        persistence.record_text_turn(
            item_id="attempt-1:assistant",
            role="assistant",
            text="May I see your passport?",
            metrics={"conversation_mode": "guided"},
        )
        persistence.record_text_turn(
            item_id="attempt-1:user",
            role="user",
            text="Yes, here it is.",
            metrics={"conversation_mode": "guided"},
        )
        await persistence.finalize_external({"result_status": "completed"})

        turns = await persistence.repository.list_turns(metadata.session_id)
        assert [(turn.role, turn.text) for turn in turns] == [
            ("assistant", "May I see your passport?"),
            ("user", "Yes, here it is."),
        ]
    finally:
        await persistence.close()
