from __future__ import annotations

import urllib.error
import urllib.request

from .models import GuidedPronunciationRequestedEvent


class GuidedPronunciationPublisher:
    def __init__(self, url: str, token: str, timeout_seconds: float = 15.0) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    def publish(self, event: GuidedPronunciationRequestedEvent) -> None:
        if not self.configured:
            raise RuntimeError("The pronunciation service is not configured")
        request = urllib.request.Request(
            f"{self.url}/v1/pronunciation/jobs",
            data=event.model_dump_json().encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Idempotency-Key": event.event_id,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status >= 300:
                    raise RuntimeError(f"Pronunciation service returned HTTP {response.status}")
        except urllib.error.URLError as exc:
            raise RuntimeError("Pronunciation service request failed") from exc
