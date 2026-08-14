from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx

from conversation_ai.api.main import create_app
from conversation_ai.config import Settings
from conversation_ai.metadata import SessionJobMetadata
from conversation_ai.orchestration import LiveKitConnection, LiveKitDispatch
from conversation_ai.persistence.repository import SessionRepository


async def make_client(database, *, livekit_gateway=None):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=database.url,
        service_api_key="test-service-key",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret="test-secret",
    )
    app = create_app(
        settings_override=settings,
        database_override=database,
        livekit_gateway_override=livekit_gateway,
    )
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )
    return client, lifespan


class FakeLiveKitGateway:
    def __init__(self) -> None:
        self.dispatches = []
        self.connections = []

    async def ensure_dispatch(self, metadata, *, room_name):
        self.dispatches.append((metadata, room_name))
        return LiveKitDispatch(dispatch_id="dispatch-1", room_sid="RM_1")

    def connection(self, metadata, *, room_name):
        self.connections.append((metadata, room_name))
        return LiveKitConnection(
            token=f"token-{len(self.connections)}",
            room_name=room_name,
            ws_url="wss://test.livekit.cloud",
        )


async def seed_session(database, *, subject_id=None, started_at=None):
    repo = SessionRepository(database.session_factory)
    metadata = SessionJobMetadata(
        schema_version=1,
        session_id=uuid.uuid4(),
        subject_id=subject_id or uuid.uuid4(),
    )
    await repo.create_session(
        metadata,
        job_id=f"job-{metadata.session_id}",
        room_name=f"room-{metadata.session_id}",
        room_sid=None,
        started_at=started_at,
    )
    return repo, metadata


async def test_health_and_authentication(database) -> None:
    client, lifespan = await make_client(database)
    try:
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 200

        response = await client.get("/api/v1/capabilities")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

        response = await client.get(
            "/api/v1/capabilities",
            headers={"Authorization": "Bearer test-service-key"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["persistence"]["raw_audio"] is False
    finally:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)


async def test_start_session_is_idempotent_and_returns_a_fresh_token(database) -> None:
    gateway = FakeLiveKitGateway()
    client, lifespan = await make_client(database, livekit_gateway=gateway)
    headers = {"Authorization": "Bearer test-service-key"}
    session_id = uuid.uuid4()
    subject_id = uuid.uuid4()
    payload = {
        "session_id": str(session_id),
        "subject_id": str(subject_id),
        "lesson_id": "42",
        "locale": "en",
    }
    try:
        first = await client.post("/api/v1/sessions/start", json=payload, headers=headers)
        second = await client.post("/api/v1/sessions/start", json=payload, headers=headers)

        assert first.status_code == 200
        assert first.json()["data"] == {
            "session_id": str(session_id),
            "token": "token-1",
            "room_name": f"conversation-{session_id}",
            "ws_url": "wss://test.livekit.cloud",
        }
        assert second.status_code == 200
        assert second.json()["data"]["token"] == "token-2"
        assert len(gateway.dispatches) == 1
        assert len(gateway.connections) == 2

        row = await SessionRepository(database.session_factory).get_session(session_id)
        assert row is not None
        assert row.status == "starting"
        assert row.livekit_dispatch_id == "dispatch-1"
        assert row.livekit_room_sid == "RM_1"
    finally:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)


async def test_start_session_rejects_reusing_id_for_another_subject(database) -> None:
    gateway = FakeLiveKitGateway()
    client, lifespan = await make_client(database, livekit_gateway=gateway)
    headers = {"Authorization": "Bearer test-service-key"}
    session_id = uuid.uuid4()
    try:
        first = await client.post(
            "/api/v1/sessions/start",
            json={"session_id": str(session_id), "subject_id": str(uuid.uuid4())},
            headers=headers,
        )
        second = await client.post(
            "/api/v1/sessions/start",
            json={"session_id": str(session_id), "subject_id": str(uuid.uuid4())},
            headers=headers,
        )

        assert first.status_code == 200
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "conflict"
        assert len(gateway.dispatches) == 1
    finally:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)


async def test_session_queries_pagination_and_cascade_delete(database) -> None:
    repo, metadata = await seed_session(database)
    for sequence in range(1, 4):
        await repo.upsert_turn(
            session_id=metadata.session_id,
            item_id=f"item-{sequence}",
            sequence=sequence,
            role="user" if sequence % 2 else "assistant",
            text=f"turn {sequence}",
            interrupted=False,
            metrics={},
            occurred_at=datetime.now(UTC),
        )

    client, lifespan = await make_client(database)
    headers = {"Authorization": "Bearer test-service-key"}
    try:
        response = await client.get(f"/api/v1/sessions/{metadata.session_id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"]["subject_id"] == str(metadata.subject_id)

        first = await client.get(
            f"/api/v1/sessions/{metadata.session_id}/turns?limit=2", headers=headers
        )
        first_data = first.json()["data"]
        assert [item["sequence"] for item in first_data["items"]] == [1, 2]
        assert first_data["next_cursor"]

        second = await client.get(
            f"/api/v1/sessions/{metadata.session_id}/turns",
            params={"limit": 2, "cursor": first_data["next_cursor"]},
            headers=headers,
        )
        assert [item["sequence"] for item in second.json()["data"]["items"]] == [3]

        deleted = await client.delete(f"/api/v1/subjects/{metadata.subject_id}", headers=headers)
        assert deleted.json()["data"]["deleted_sessions"] == 1
        missing = await client.get(f"/api/v1/sessions/{metadata.session_id}", headers=headers)
        assert missing.status_code == 404
    finally:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)


async def test_subject_session_cursor(database) -> None:
    subject_id = uuid.uuid4()
    base = datetime.now(UTC)
    for offset in range(3):
        await seed_session(
            database,
            subject_id=subject_id,
            started_at=base + timedelta(seconds=offset),
        )

    client, lifespan = await make_client(database)
    headers = {"Authorization": "Bearer test-service-key"}
    try:
        first = await client.get(f"/api/v1/subjects/{subject_id}/sessions?limit=2", headers=headers)
        data = first.json()["data"]
        assert len(data["items"]) == 2
        second = await client.get(
            f"/api/v1/subjects/{subject_id}/sessions",
            params={"limit": 2, "cursor": data["next_cursor"]},
            headers=headers,
        )
        assert len(second.json()["data"]["items"]) == 1
    finally:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)
