from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any


class InvalidCursor(ValueError):
    pass


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidCursor("Cursor is malformed.") from exc
    if not isinstance(payload, dict):
        raise InvalidCursor("Cursor is malformed.")
    return payload


def datetime_cursor(value: datetime, identifier: object) -> str:
    return encode_cursor({"at": value.isoformat(), "id": str(identifier)})

