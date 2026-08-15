from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger("english-level-assessor")


def read_value(value: Any, *names: str, default: Any = None) -> Any:
    """Read a field from LiveKit objects, mappings, or Pydantic models."""
    if isinstance(value, Mapping):
        for name in names:
            candidate = value.get(name)
            if candidate is not None:
                return candidate

    for name in names:
        candidate = getattr(value, name, None)
        if candidate is not None:
            return candidate

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            for name in names:
                candidate = dumped.get(name)
                if candidate is not None:
                    return candidate

    return default


def number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default


def optional_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return None


def _word_text(word: Any) -> str:
    value = read_value(word, "text", "word", "punctuated_word")
    if value is None and isinstance(word, str):
        value = word
    return str(value or "").strip()


def extract_words(raw_words: Any) -> list[dict[str, Any]]:
    """Normalize provider word timings and discard entries without text."""
    captured: list[dict[str, Any]] = []
    for raw_word in raw_words or []:
        text = _word_text(raw_word)
        if not text:
            logger.debug("Ignoring an STT word entry without text")
            continue

        start = number(read_value(raw_word, "start_time", "start", default=0.0))
        end = number(
            read_value(raw_word, "end_time", "end", default=start),
            default=start,
        )
        end = max(end, start)
        captured.append(
            {
                "word": text,
                "start": start,
                "end": end,
                "confidence": optional_confidence(read_value(raw_word, "confidence")),
            }
        )

    if captured:
        base_start = captured[0]["start"]
        for item in captured:
            item["start"] = max(0.0, item["start"] - base_start)
            item["end"] = max(item["start"], item["end"] - base_start)
    return captured


def valid_submission_words(words: Any) -> list[dict[str, Any]]:
    """Final defense before JSON serialization."""
    valid: list[dict[str, Any]] = []
    for word in words or []:
        if not isinstance(word, Mapping):
            continue
        text = str(word.get("word") or "").strip()
        if not text:
            continue
        start = number(word.get("start"))
        end = max(start, number(word.get("end"), default=start))
        valid.append(
            {
                "word": text,
                "start": start,
                "end": end,
                "confidence": optional_confidence(word.get("confidence")),
            }
        )
    return valid
