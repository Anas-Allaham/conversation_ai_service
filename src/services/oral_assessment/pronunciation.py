from __future__ import annotations

import urllib.error
import urllib.request

from .config import Settings
from .models import PronunciationRequestedEvent
from .service import PronunciationPublisher


class HttpPronunciationPublisher(PronunciationPublisher):
    def __init__(self, settings: Settings) -> None:
        self.url = settings.pronunciation_service_url.rstrip("/")
        self.token = settings.pronunciation_service_token
        self.timeout = settings.evaluator_timeout_seconds

    def publish(self, event: PronunciationRequestedEvent) -> None:
        if not self.url:
            raise RuntimeError("PRONUNCIATION_SERVICE_URL is not configured")
        request = urllib.request.Request(
            f"{self.url}/v1/pronunciation/jobs",
            data=event.model_dump_json().encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Idempotency-Key": event.event_id,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.status >= 300:
                    raise RuntimeError(f"Pronunciation service returned HTTP {response.status}")
        except urllib.error.URLError as exc:
            raise RuntimeError("Pronunciation service request failed") from exc

