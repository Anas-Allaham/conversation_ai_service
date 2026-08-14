from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "conversation-ai-service"
API_VERSION = "v1"


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
        return all(
            (
                self.livekit_url,
                self.livekit_api_key.get_secret_value(),
                self.livekit_api_secret.get_secret_value(),
                self.livekit_agent_name.strip(),
            )
        )

    def require_conversation_start_environment(self) -> None:
        required = {
            "LIVEKIT_URL": self.livekit_url,
            "LIVEKIT_API_KEY": self.livekit_api_key.get_secret_value(),
            "LIVEKIT_API_SECRET": self.livekit_api_secret.get_secret_value(),
            "LIVEKIT_AGENT_NAME": self.livekit_agent_name.strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError("Missing required environment values: " + ", ".join(missing))

    def require_agent_environment(self) -> None:
        required = {
            "LIVEKIT_URL": self.livekit_url,
            "LIVEKIT_API_KEY": self.livekit_api_key.get_secret_value(),
            "LIVEKIT_API_SECRET": self.livekit_api_secret.get_secret_value(),
            "DEEPGRAM_API_KEY": self.deepgram_api_key.get_secret_value(),
            "DATABASE_URL": self.database_url.get_secret_value(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError("Missing required environment values: " + ", ".join(missing))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
