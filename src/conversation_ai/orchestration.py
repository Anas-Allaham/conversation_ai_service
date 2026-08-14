from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass

from livekit import api

from .config import Settings
from .metadata import SessionJobMetadata
from .persistence.repository import SessionRepository

logger = logging.getLogger("conversation-ai.orchestration")


class ConversationStartConflictError(RuntimeError):
    """The idempotency session ID is already bound to different metadata."""


class ConversationCannotRestartError(RuntimeError):
    """A completed or failed session cannot be started again."""


@dataclass(frozen=True)
class LiveKitConnection:
    token: str
    room_name: str
    ws_url: str


@dataclass(frozen=True)
class LiveKitDispatch:
    dispatch_id: str
    room_sid: str | None


class LiveKitConversationGateway:
    """Owns LiveKit room, dispatch, and participant-token operations."""

    def __init__(self, settings: Settings) -> None:
        settings.require_conversation_start_environment()
        livekit = settings.livekit
        self._url = livekit.url
        self._api_key = livekit.api_key
        self._api_secret = livekit.api_secret
        self._agent_name = livekit.agent_name

    async def ensure_dispatch(
        self,
        metadata: SessionJobMetadata,
        *,
        room_name: str,
    ) -> LiveKitDispatch:
        raw_metadata = metadata.model_dump_json(exclude_none=True)
        client = api.LiveKitAPI(self._url, self._api_key, self._api_secret)
        try:
            existing = await self._matching_dispatch(client, room_name, metadata.session_id)
            if existing is not None:
                return LiveKitDispatch(
                    dispatch_id=existing.id,
                    room_sid=await self._room_sid(client, room_name),
                )

            room_sid = await self._ensure_room(client, room_name)

            # Re-check after room creation. This makes retries safe when a prior
            # dispatch succeeded but its HTTP response never reached this API.
            existing = await self._matching_dispatch(client, room_name, metadata.session_id)
            if existing is None:
                existing = await client.agent_dispatch.create_dispatch(
                    api.CreateAgentDispatchRequest(
                        agent_name=self._agent_name,
                        room=room_name,
                        metadata=raw_metadata,
                    )
                )
            return LiveKitDispatch(dispatch_id=existing.id, room_sid=room_sid)
        finally:
            await client.aclose()

    def connection(self, metadata: SessionJobMetadata, *, room_name: str) -> LiveKitConnection:
        grants = api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        )
        identity = str(metadata.subject_id)
        token = (
            api.AccessToken(self._api_key, self._api_secret)
            .with_identity(identity)
            .with_name("learner")
            .with_grants(grants)
            .to_jwt()
        )
        return LiveKitConnection(token=token, room_name=room_name, ws_url=self._url)

    async def _ensure_room(self, client: api.LiveKitAPI, room_name: str) -> str | None:
        rooms = await self._list_rooms(client, room_name)
        if rooms:
            return rooms[0].sid or None

        try:
            room = await client.room.create_room(
                api.CreateRoomRequest(name=room_name, empty_timeout=300)
            )
            return room.sid or None
        except Exception:
            # A concurrent request may have created the deterministic room after
            # our list call. Only suppress the error when the room now exists.
            rooms = await self._list_rooms(client, room_name)
            if not rooms:
                raise
            return rooms[0].sid or None

    async def _room_sid(self, client: api.LiveKitAPI, room_name: str) -> str | None:
        rooms = await self._list_rooms(client, room_name)
        return (rooms[0].sid or None) if rooms else None

    @staticmethod
    async def _list_rooms(client: api.LiveKitAPI, room_name: str) -> list:
        response = await client.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
        return list(response.rooms)

    async def _matching_dispatch(
        self,
        client: api.LiveKitAPI,
        room_name: str,
        session_id: uuid.UUID,
    ):
        try:
            dispatches = await client.agent_dispatch.list_dispatch(room_name)
        except api.ServerError as exc:
            # LiveKit reports a missing room as 404 instead of returning an
            # empty dispatch list. A first start must continue to room creation.
            if exc.status == 404 or exc.code == "not_found":
                return None
            raise

        for dispatch in dispatches:
            if dispatch.agent_name != self._agent_name:
                continue
            try:
                payload = json.loads(dispatch.metadata or "{}")
            except json.JSONDecodeError:
                continue
            if payload.get("session_id") == str(session_id):
                return dispatch
        return None


class ConversationOrchestrator:
    """Coordinates durable session reservation with LiveKit side effects."""

    def __init__(
        self,
        repository: SessionRepository,
        gateway: LiveKitConversationGateway,
    ) -> None:
        self._repository = repository
        self._gateway = gateway

    async def start(self, metadata: SessionJobMetadata) -> LiveKitConnection:
        room_name = f"conversation-{metadata.session_id}"
        await self._repository.reserve_session(metadata, room_name=room_name)

        async with self._repository.lock_session(metadata.session_id) as row:
            self._validate_contract(row, metadata, room_name)
            if row.status in {"completed", "failed"}:
                raise ConversationCannotRestartError(
                    f"Session {metadata.session_id} has already finished."
                )
            if not row.livekit_dispatch_id:
                dispatch = await self._gateway.ensure_dispatch(metadata, room_name=room_name)
                row.livekit_dispatch_id = dispatch.dispatch_id
                if dispatch.room_sid:
                    row.livekit_room_sid = dispatch.room_sid

        logger.info(
            "conversation_connection_issued",
            extra={"session_id": str(metadata.session_id), "room": room_name},
        )
        return self._gateway.connection(metadata, room_name=room_name)

    @staticmethod
    def _validate_contract(row, metadata: SessionJobMetadata, room_name: str) -> None:
        expected = metadata.model_dump(mode="json", exclude_none=True)
        if (
            row.subject_id != metadata.subject_id
            or row.room_name != room_name
            or row.dispatch_metadata != expected
        ):
            raise ConversationStartConflictError(
                f"Session {metadata.session_id} is already bound to different metadata."
            )
