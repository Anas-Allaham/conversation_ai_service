from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "conversation-ai-service"
API_VERSION = "v1"


def load_runtime_environment(project_root: Path | None = None) -> None:
    """Load local environment files once with `.env.local` taking precedence."""

    root = (project_root or Path.cwd()).resolve()
    load_dotenv(root / ".env.local")
    load_dotenv(root / ".env", override=False)


def env_float(name: str, default: float) -> float:
    """Read a numeric runtime override with one consistent error contract."""

    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number; received {raw!r}.") from exc


def env_int(name: str, default: int) -> int:
    """Read an integer runtime override with one consistent error contract."""

    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer; received {raw!r}.") from exc


@dataclass(frozen=True, slots=True)
class LiveKitConfig:
    """Shared LiveKit credentials and dispatch identity for every local service."""

    url: str
    api_key: str
    api_secret: str
    agent_name: str = "english-tutor"

    @classmethod
    def from_env(cls) -> LiveKitConfig:
        return cls(
            url=os.getenv("LIVEKIT_URL", ""),
            api_key=os.getenv("LIVEKIT_API_KEY", ""),
            api_secret=os.getenv("LIVEKIT_API_SECRET", ""),
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", "english-tutor").strip()
            or "english-tutor",
        )

    def missing(self, *, include_agent_name: bool = True) -> list[str]:
        values = {
            "LIVEKIT_URL": self.url,
            "LIVEKIT_API_KEY": self.api_key,
            "LIVEKIT_API_SECRET": self.api_secret,
        }
        if include_agent_name:
            values["LIVEKIT_AGENT_NAME"] = self.agent_name
        return [name for name, value in values.items() if not value]


class Settings(BaseSettings):
    """Validated runtime settings shared by the worker and internal API."""

    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    livekit_url: str = ""
    livekit_api_key: SecretStr = SecretStr("")
    livekit_api_secret: SecretStr = SecretStr("")
    livekit_agent_name: str = "english-tutor"
    deepgram_api_key: SecretStr = SecretStr("")
    database_url: SecretStr = SecretStr("")
    service_api_key: SecretStr = SecretStr("")

    livekit_llm_model: str = "google/gemini-2.5-flash-lite"
    deepgram_tts_model: str = "aura-2-andromeda-en"
    llm_temperature: float = Field(default=0.30, ge=0.0, le=2.0)
    llm_max_completion_tokens: int = Field(default=320, ge=32, le=4096)

    aec_warmup_seconds: float = Field(default=1.0, ge=0.0, le=10.0)
    audio_enhancement: Literal["quail_l", "none"] = "quail_l"
    audio_enhancement_level: float | None = Field(default=None, ge=0.0, le=1.0)

    flux_eager_eot_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    flux_eot_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    flux_eot_timeout_ms: int = Field(default=7000, ge=500, le=30000)

    @field_validator("audio_enhancement", mode="before")
    @classmethod
    def normalize_audio_enhancement(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() in {
            "",
            "off",
            "false",
            "disabled",
        }:
            return "none"
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("audio_enhancement_level", mode="before")
    @classmethod
    def empty_enhancement_level_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be a standard Python logging level")
        return normalized

    @property
    def is_production(self) -> bool:
        return self.app_env in {"staging", "production"}

    @property
    def api_auth_configured(self) -> bool:
        return bool(self.service_api_key.get_secret_value())

    @property
    def conversation_start_configured(self) -> bool:
        return not self.livekit.missing()

    @property
    def livekit(self) -> LiveKitConfig:
        return LiveKitConfig(
            url=self.livekit_url,
            api_key=self.livekit_api_key.get_secret_value(),
            api_secret=self.livekit_api_secret.get_secret_value(),
            agent_name=self.livekit_agent_name.strip(),
        )

    def require_conversation_start_environment(self) -> None:
        missing = self.livekit.missing()
        if missing:
            raise RuntimeError("Missing required environment values: " + ", ".join(missing))

    def require_agent_environment(self, *, include_database: bool = True) -> None:
        required = {
            "DEEPGRAM_API_KEY": self.deepgram_api_key.get_secret_value(),
        }
        if include_database:
            required["DATABASE_URL"] = self.database_url.get_secret_value()
        missing = self.livekit.missing(include_agent_name=False)
        missing.extend(name for name, value in required.items() if not value)
        if missing:
            raise RuntimeError("Missing required environment values: " + ", ".join(missing))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_runtime_environment()
    return Settings()
