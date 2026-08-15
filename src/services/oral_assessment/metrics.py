from __future__ import annotations

import threading
from collections import Counter

from .models import AssessmentResult, ResponseResult


class ServiceMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = Counter()
        self.response_decisions = Counter()
        self.levels = Counter()
        self.evaluator_failures = 0
        self.invalid_audio = 0
        self.completed = 0
        self.duration_sum_seconds = 0.0
        self.latency_sum_seconds = 0.0
        self.latency_count = 0

    def observe_request(self, method: str, path: str, status: int, latency: float) -> None:
        with self._lock:
            self.requests[(method, path, status)] += 1
            self.latency_sum_seconds += latency
            self.latency_count += 1

    def observe_response(self, result: ResponseResult) -> None:
        if result.idempotent_replay:
            return
        with self._lock:
            self.response_decisions[result.response_decision.value] += 1
            if result.response_decision.value == "invalid_audio":
                self.invalid_audio += 1

    def observe_evaluator_failure(self) -> None:
        with self._lock:
            self.evaluator_failures += 1

    def observe_completion(self, result: AssessmentResult, duration_seconds: float) -> None:
        with self._lock:
            self.completed += 1
            self.levels[str(result.confirmed_level)] += 1
            self.duration_sum_seconds += max(0.0, duration_seconds)

    @staticmethod
    def _line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
        label_text = ""
        if labels:
            escaped = [f'{key}="{value.replace(chr(34), chr(92) + chr(34))}"' for key, value in labels.items()]
            label_text = "{" + ",".join(escaped) + "}"
        return f"{name}{label_text} {value}"

    def render_prometheus(self) -> str:
        with self._lock:
            lines = [
                "# TYPE oral_assessment_requests_total counter",
                *[
                    self._line(
                        "oral_assessment_requests_total",
                        count,
                        {"method": method, "path": path, "status": str(status)},
                    )
                    for (method, path, status), count in sorted(self.requests.items())
                ],
                "# TYPE oral_assessment_completed_total counter",
                self._line("oral_assessment_completed_total", self.completed),
                "# TYPE oral_assessment_evaluator_failures_total counter",
                self._line("oral_assessment_evaluator_failures_total", self.evaluator_failures),
                "# TYPE oral_assessment_invalid_audio_total counter",
                self._line("oral_assessment_invalid_audio_total", self.invalid_audio),
                "# TYPE oral_assessment_level_total counter",
                *[
                    self._line("oral_assessment_level_total", count, {"level": level})
                    for level, count in sorted(self.levels.items())
                ],
                self._line("oral_assessment_request_latency_seconds_sum", round(self.latency_sum_seconds, 6)),
                self._line("oral_assessment_request_latency_seconds_count", self.latency_count),
                self._line("oral_assessment_duration_seconds_sum", round(self.duration_sum_seconds, 6)),
                self._line("oral_assessment_duration_seconds_count", self.completed),
            ]
        return "\n".join(lines) + "\n"

