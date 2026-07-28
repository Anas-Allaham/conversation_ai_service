from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from conversation_ai.config import Settings
from conversation_ai.metadata import JobMetadataError, parse_job_metadata
from conversation_ai.persistence.database import normalize_database_url


def test_settings_normalize_empty_enhancement_level() -> None:
    settings = Settings(
        _env_file=None,
        audio_enhancement="off",
        audio_enhancement_level="",
    )
    assert settings.audio_enhancement == "none"
    assert settings.audio_enhancement_level is None


def test_settings_validate_thresholds() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, flux_eot_threshold=1.5)


def test_production_metadata_is_required() -> None:
    with pytest.raises(JobMetadataError, match="require dispatch metadata"):
        parse_job_metadata("", production=True)


def test_local_metadata_fallback_is_anonymous() -> None:
    metadata = parse_job_metadata(None, production=False)
    assert isinstance(metadata.session_id, uuid.UUID)
    assert isinstance(metadata.subject_id, uuid.UUID)
    assert metadata.locale == "en"


def test_dispatch_metadata_is_strict_and_versioned() -> None:
    payload = {
        "schema_version": 1,
        "session_id": str(uuid.uuid4()),
        "subject_id": str(uuid.uuid4()),
        "locale": "en",
    }
    parsed = parse_job_metadata(json.dumps(payload), production=True)
    assert parsed.schema_version == 1

    payload["unknown"] = True
    with pytest.raises(JobMetadataError, match="Invalid dispatch metadata"):
        parse_job_metadata(json.dumps(payload), production=True)


def test_agent_environment_lists_missing_values_without_secrets() -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(RuntimeError) as error:
        settings.require_agent_environment()
    message = str(error.value)
    assert "LIVEKIT_URL" in message
    assert "DATABASE_URL" in message


def test_managed_postgres_url_is_normalized_for_asyncpg() -> None:
    normalized = normalize_database_url(
        "postgresql://user:password@db.example/test"
        "?sslmode=require&channel_binding=require"
    )
    assert normalized.startswith("postgresql+asyncpg://")
    assert "ssl=require" in normalized
    assert "sslmode" not in normalized
    assert "channel_binding" not in normalized
