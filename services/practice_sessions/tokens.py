from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


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
    ) -> None:
        self.server_url = server_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.ttl = timedelta(minutes=ttl_minutes)

    def validate_configuration(self) -> None:
        missing = [
            name
            for name, value in (
                ("LIVEKIT_URL", self.server_url),
                ("LIVEKIT_API_KEY", self.api_key),
                ("LIVEKIT_API_SECRET", self.api_secret),
            )
            if not value
        ]
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

        expires_at = datetime.now(UTC) + self.ttl
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
                            agent_name="english-tutor",
                            metadata=metadata_json,
                        )
                    ]
                )
            )
            .with_ttl(self.ttl)
            .to_jwt()
        )
        return IssuedParticipantToken(token=token, expires_at=expires_at)
