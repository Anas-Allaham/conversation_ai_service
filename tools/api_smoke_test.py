from __future__ import annotations

import json
import os
import urllib.request
import uuid

BASE_URL = os.getenv("ASSESSMENT_SERVICE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.getenv("ASSESSMENT_SERVICE_TOKEN") or os.getenv(
    "SERVICE_API_KEY", "dev-service-token"
)


def request(method: str, path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as response:
        content = response.read()
        return json.loads(content) if content else {}


def demo_text(level: str | None) -> str:
    if level == "B2":
        return " ".join(["I compare both options, explain their benefits and limitations, recommend a balanced policy, and respond to the new concern with clear conditions."] * 8)
    if level == "B1":
        return " ".join(["I explain what happened in order, why the problem occurred, how people responded, and what I would change next time."] * 6)
    if level == "A2":
        return " ".join(["I make the request clearly, ask for the needed information, and choose another suitable option when the situation changes."] * 4)
    if level == "A1":
        return "I give simple personal information and answer the direct question with familiar words and a clear short sentence."
    return "My name is Demo. Clear voices are easy to hear. Yes, I can hear you clearly."


def main() -> None:
    created = request(
        "POST",
        "/v1/assessments",
        {
            "user_id": "smoke-test-user",
            "assessment_type": "conversational-placement",
            "target_range": ["A1", "A2", "B1", "B2"],
            "language": "en",
            "interface_language": "en",
            "form_seed": "smoke-test",
        },
    )
    assessment_id = created["assessment_id"]
    prompt = created["current_item"]
    for turn in range(16):
        response_id = f"smoke-{turn}-{uuid.uuid4().hex[:8]}"
        result = request(
            "POST",
            f"/v1/assessments/{assessment_id}/responses",
            {
                "response_id": response_id,
                "idempotency_key": f"smoke-idempotency-{response_id}",
                "prompt_id": prompt["prompt_id"],
                "item_id": prompt["item_id"],
                "prompt_kind": prompt["prompt_kind"],
                "transcript": demo_text(prompt.get("target_level")),
                "words": [],
                "response_started_at_ms": 1000,
                "response_ended_at_ms": 31000,
                "audio_uri": None,
                "prompt_repetitions": 0,
                "clarification_requests": 0,
                "asr_confidence": 0.9,
                "explicit_audio_issue": False,
                "audio_issue_reason": None,
                "session_interrupted": False,
            },
        )
        action = result["next_action"]
        print(f"{turn + 1:02d}: {prompt['prompt_kind']} -> {result['response_decision']} -> {action['type']}")
        if action.get("prompt"):
            prompt = action["prompt"]
        else:
            break
    final = request("GET", f"/v1/assessments/{assessment_id}/result")
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
