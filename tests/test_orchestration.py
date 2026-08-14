from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from livekit import api

from conversation_ai.config import Settings
from conversation_ai.metadata import SessionJobMetadata
from conversation_ai.orchestration import LiveKitConversationGateway


def gateway() -> LiveKitConversationGateway:
    return LiveKitConversationGateway(
        Settings(
            _env_file=None,
            app_env="test",
            livekit_url="wss://test.livekit.cloud",
            livekit_api_key="test-key",
            livekit_api_secret="test-secret",
            livekit_agent_name="english-tutor",
        )
    )


async def test_gateway_creates_room_and_dispatch_with_strict_metadata() -> None:
    metadata = SessionJobMetadata(
        schema_version=1,
        session_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        lesson_id="42",
    )
    room_service = SimpleNamespace(
        list_rooms=AsyncMock(return_value=SimpleNamespace(rooms=[])),
        create_room=AsyncMock(return_value=SimpleNamespace(sid="RM_1")),
    )
    dispatch_service = SimpleNamespace(
        list_dispatch=AsyncMock(
            side_effect=[
                api.ServerError("not_found", "requested room does not exist", status=404),
                [],
            ]
        ),
        create_dispatch=AsyncMock(return_value=SimpleNamespace(id="AD_1")),
    )
    client = SimpleNamespace(
        room=room_service,
        agent_dispatch=dispatch_service,
        aclose=AsyncMock(),
    )

    with patch("conversation_ai.orchestration.api.LiveKitAPI", return_value=client):
        result = await gateway().ensure_dispatch(metadata, room_name="conversation-test")

    assert result.dispatch_id == "AD_1"
    assert result.room_sid == "RM_1"
    room_request = room_service.create_room.call_args.args[0]
    assert room_request.name == "conversation-test"
    dispatch_request = dispatch_service.create_dispatch.call_args.args[0]
    assert dispatch_request.agent_name == "english-tutor"
    assert dispatch_request.room == "conversation-test"
    assert json.loads(dispatch_request.metadata) == metadata.model_dump(
        mode="json", exclude_none=True
    )
    client.aclose.assert_awaited_once()


async def test_gateway_reuses_matching_dispatch_without_creating_room() -> None:
    metadata = SessionJobMetadata(
        schema_version=1,
        session_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
    )
    existing = SimpleNamespace(
        id="AD_existing",
        agent_name="english-tutor",
        metadata=metadata.model_dump_json(exclude_none=True),
    )
    room_service = SimpleNamespace(
        list_rooms=AsyncMock(
            return_value=SimpleNamespace(rooms=[SimpleNamespace(sid="RM_existing")])
        ),
        create_room=AsyncMock(),
    )
    dispatch_service = SimpleNamespace(
        list_dispatch=AsyncMock(return_value=[existing]),
        create_dispatch=AsyncMock(),
    )
    client = SimpleNamespace(
        room=room_service,
        agent_dispatch=dispatch_service,
        aclose=AsyncMock(),
    )

    with patch("conversation_ai.orchestration.api.LiveKitAPI", return_value=client):
        result = await gateway().ensure_dispatch(metadata, room_name="conversation-test")

    assert result.dispatch_id == "AD_existing"
    assert result.room_sid == "RM_existing"
    room_service.create_room.assert_not_awaited()
    dispatch_service.create_dispatch.assert_not_awaited()
