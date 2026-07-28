from __future__ import annotations

import dataclasses
import re
import uuid
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

_REDACTED_KEYS = {
    "access_token",
    "api_key",
    "api_secret",
    "audio_recording_path",
    "authorization",
    "database_url",
    "secret",
}

_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_QUERY_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:token|key|secret|signature)=)[^&\s]+"
)


def safe_error_text(value: object, *, limit: int = 1000) -> str:
    text = str(value)
    text = _BEARER_PATTERN.sub(r"\1[REDACTED]", text)
    text = _QUERY_SECRET_PATTERN.sub(r"\1[REDACTED]", text)
    return text[:limit]


def sanitize_json(value: Any) -> Any:
    """Convert SDK values to JSON while dropping secrets, paths, and binary audio."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes | bytearray | memoryview | Path):
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return sanitize_json(value.value)
    if hasattr(value, "model_dump"):
        return sanitize_json(value.model_dump(mode="json", exclude_none=True))
    if dataclasses.is_dataclass(value):
        return sanitize_json(dataclasses.asdict(value))
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key.lower() in _REDACTED_KEYS:
                continue
            converted = sanitize_json(raw_value)
            if converted is not None:
                cleaned[key] = converted
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [converted for item in value if (converted := sanitize_json(item)) is not None]
    return safe_error_text(value)

