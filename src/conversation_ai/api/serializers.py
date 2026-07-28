from __future__ import annotations

from typing import Any

from ..persistence.models import ConversationSession, ConversationTurn, SessionEvent
from ..persistence.serialization import sanitize_json


def session_data(row: ConversationSession) -> dict[str, Any]:
    return {
        "session_id": str(row.session_id),
        "subject_id": str(row.subject_id),
        "schema_version": row.schema_version,
        "lesson_id": row.lesson_id,
        "locale": row.locale,
        "livekit_job_id": row.livekit_job_id,
        "livekit_room_sid": row.livekit_room_sid,
        "room_name": row.room_name,
        "status": row.status,
        "dispatch_metadata": sanitize_json(row.dispatch_metadata),
        "model_usage": sanitize_json(row.model_usage),
        "final_report": sanitize_json(row.final_report),
        "error": (
            {"type": row.error_type, "message": row.error_message}
            if row.error_type or row.error_message
            else None
        ),
        "started_at": row.started_at.isoformat(),
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def session_summary(row: ConversationSession) -> dict[str, Any]:
    data = session_data(row)
    data.pop("final_report", None)
    data.pop("dispatch_metadata", None)
    return data


def turn_data(row: ConversationTurn) -> dict[str, Any]:
    return {
        "item_id": row.item_id,
        "sequence": row.sequence,
        "role": row.role,
        "text": row.text,
        "interrupted": row.interrupted,
        "metrics": sanitize_json(row.metrics),
        "occurred_at": row.occurred_at.isoformat(),
    }


def event_data(row: SessionEvent) -> dict[str, Any]:
    return {
        "sequence": row.sequence,
        "type": row.event_type,
        "payload": sanitize_json(row.payload),
        "occurred_at": row.occurred_at.isoformat(),
    }

