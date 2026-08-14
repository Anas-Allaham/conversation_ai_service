from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from conversation_ai.config import LiveKitConfig


class LiveKitConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedParticipantToken:
    token: str
    expires_at: datetime


class LiveKitTokenIssuer:
    """Issue a short-lived participant token with explicit agent dispatch."""

    def __init__(
        self,
        server_url: str,
        api_key: str,
        api_secret: str,
        *,
        ttl_minutes: int = 20,
        agent_name: str = "english-tutor",
    ) -> None:
        self.config = LiveKitConfig(
            url=server_url,
            api_key=api_key,
            api_secret=api_secret,
            agent_name=agent_name,
        )
        self.ttl = timedelta(minutes=ttl_minutes)

    @classmethod
    def from_config(
        cls,
        config: LiveKitConfig,
        *,
        ttl_minutes: int = 20,
    ) -> LiveKitTokenIssuer:
        return cls(
            config.url,
            config.api_key,
            config.api_secret,
            ttl_minutes=ttl_minutes,
            agent_name=config.agent_name,
        )

    @property
    def server_url(self) -> str:
        return self.config.url

    @property
    def api_key(self) -> str:
        return self.config.api_key

    @property
    def api_secret(self) -> str:
        return self.config.api_secret

    def validate_configuration(self) -> None:
        missing = self.config.missing(include_agent_name=False)
        if missing:
            raise LiveKitConfigurationError(
                "Missing LiveKit configuration: " + ", ".join(missing)
            )
        try:
            from livekit import api as _api  # noqa: F401
        except ImportError as exc:
            raise LiveKitConfigurationError(
                "livekit-api is unavailable; install the project dependencies"
            ) from exc

    def issue(
        self,
        *,
        room_name: str,
        participant_identity: str,
        participant_name: str,
        dispatch_metadata: dict[str, object],
    ) -> IssuedParticipantToken:
        self.validate_configuration()
        from livekit import api

        expires_at = datetime.now(timezone.utc) + self.ttl
        metadata_json = json.dumps(dispatch_metadata, ensure_ascii=False, separators=(",", ":"))
        token = (
            api.AccessToken(self.api_key, self.api_secret)
            .with_identity(participant_identity)
            .with_name(participant_name)
            .with_metadata(json.dumps({"user_id": dispatch_metadata["user_id"]}))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .with_room_config(
                api.RoomConfiguration(
                    agents=[
                        api.RoomAgentDispatch(
                            agent_name=self.config.agent_name,
                            metadata=metadata_json,
                        )
                    ]
                )
            )
            .with_ttl(self.ttl)
            .to_jwt()
        )
        return IssuedParticipantToken(token=token, expires_at=expires_at)
