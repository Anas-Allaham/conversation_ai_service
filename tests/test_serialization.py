from __future__ import annotations

from pathlib import Path

from conversation_ai.persistence.serialization import safe_error_text, sanitize_json


def test_sanitize_json_removes_secrets_paths_and_binary_audio() -> None:
    payload = sanitize_json(
        {
            "api_key": "secret",
            "audio_recording_path": Path("private.wav"),
            "nested": {"authorization": "Bearer private", "kept": "value"},
            "audio_bytes": b"raw-audio",
        }
    )
    assert payload == {"nested": {"kept": "value"}}


def test_safe_error_text_redacts_credentials() -> None:
    message = safe_error_text(
        "Authorization: Bearer abc.def and https://host/path?token=secret&x=1"
    )
    assert "abc.def" not in message
    assert "token=secret" not in message
    assert "[REDACTED]" in message

