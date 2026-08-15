from __future__ import annotations

import httpx

from conversation_ai.api.main import create_app
from conversation_ai.config import Settings


async def test_core_and_tutor_contracts_share_one_fastapi_app(database, monkeypatch) -> None:
    sync_database_url = database.url.replace("sqlite+aiosqlite://", "sqlite://")
    environment = {
        "ASSESSMENT_DATABASE_URL": sync_database_url,
        "ASSESSMENT_SERVICE_TOKEN": "test-service-key",
        "ASSESSMENT_ADMIN_TOKEN": "test-admin-key",
        "EVALUATOR_PROVIDER": "heuristic",
        "ALLOW_HEURISTIC_EVALUATOR": "true",
        "PIPER_REQUIRED": "false",
        "STORE_ALL_ASSESSMENT_AUDIO": "false",
        "LIVEKIT_URL": "wss://test.livekit.cloud",
        "LIVEKIT_API_KEY": "test-key",
        "LIVEKIT_API_SECRET": "test-secret-value-with-at-least-32-bytes",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=database.url,
        service_api_key="test-service-key",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret="test-secret-value-with-at-least-32-bytes",
        tutor_enabled=True,
        tutor_required=True,
    )
    app = create_app(
        settings_override=settings,
        database_override=database,
        include_tutor=True,
    )
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"Authorization": "Bearer test-service-key"},
    )
    try:
        schema = app.openapi()
        assert schema["paths"]["/v1/guided-conversations/domains"]["get"]["security"] == [
            {"ServiceApiKey": []}
        ]
        assert schema["paths"][
            "/v1/admin/guided-conversations/sessions/{session_id}/debug-report"
        ]["get"]["security"] == [{"TutorAdminToken": []}]
        assessment_operation = schema["paths"]["/v1/assessments"]["post"]
        assessment_example = assessment_operation["requestBody"]["content"][
            "application/json"
        ]["example"]
        assert assessment_example == {
            "user_id": "learner-001",
            "interface_language": "en",
        }
        assessment_schema = schema["components"]["schemas"]["AssessmentCreateRequest"]
        assert "target_range" not in assessment_schema["properties"]

        core = await client.get("/api/v1/capabilities")
        assert core.status_code == 200
        assert core.json()["data"]["practice_modes"] == ["free", "guided"]

        tutor = await client.get(
            "/v1/guided-conversations/domains",
            params={"placement_completed": "true", "placement_level": "A2"},
        )
        assert tutor.status_code == 200
        assert {domain["domain_id"] for domain in tutor.json()} == {"airport", "restaurant"}

        created_assessment = await client.post("/v1/assessments", json=assessment_example)
        assert created_assessment.status_code == 201, created_assessment.text

        free_example = schema["paths"]["/v1/practice-sessions"]["post"]["requestBody"][
            "content"
        ]["application/json"]["example"]
        free_session = await client.post("/v1/practice-sessions", json=free_example)
        assert free_session.status_code == 201, free_session.text
        assert free_session.json()["mode"] == "free"

        guided_example = schema["paths"]["/v1/guided-conversations/sessions"]["post"][
            "requestBody"
        ]["content"]["application/json"]["example"]
        guided_session = await client.post(
            "/v1/guided-conversations/sessions", json=guided_example
        )
        assert guided_session.status_code == 201, guided_session.text
        assert guided_session.json()["scenario_id"] == "restaurant.order_meal.a1"

        invalid = await client.post(
            "/v1/practice-sessions",
            json={"user_id": "learner", "mode": "unsupported"},
        )
        assert invalid.status_code == 422
        assert isinstance(invalid.json()["detail"], list)

        metrics = await client.get("/metrics", headers={"Authorization": "Bearer wrong"})
        assert metrics.status_code == 401

        assessment = await client.post(
            "/v1/assessment-sessions",
            json={"user_id": "learner", "interface_language": "en"},
        )
        assert assessment.status_code == 201, assessment.text
        assessment_body = assessment.json()
        assert assessment_body["agent_name"] == "english-level-assessor"
        assert assessment_body["room_name"] == assessment_body["assessment_id"]
        assert assessment_body["result_url"].endswith("/result")
        assert assessment_body["participant_token"]

        ready = await client.get("/health/ready")
        assert ready.status_code == 200
    finally:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)
