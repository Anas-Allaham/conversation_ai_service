from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


def _health_errors(base_url: str) -> list[str]:
    url = base_url.rstrip("/") + "/health/ready"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read() or b"{}")
        except json.JSONDecodeError:
            payload = {}
        reasons = payload.get("errors") or [f"HTTP {exc.code} from {url}"]
        return [str(reason) for reason in reasons]
    except (urllib.error.URLError, TimeoutError) as exc:
        return [f"Cannot reach {url}: {exc}"]

    if payload.get("status") != "ready":
        return [str(reason) for reason in payload.get("errors", ["service is not ready"])]
    return []


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env.local")
    load_dotenv(root / ".env", override=False)

    errors: list[str] = []
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "DEEPGRAM_API_KEY"):
        if not os.getenv(name, "").strip():
            errors.append(f"{name} is missing")

    service_url = os.getenv("ASSESSMENT_SERVICE_URL", "http://127.0.0.1:8000")
    errors.extend(_health_errors(service_url))

    if errors:
        print("Assessment preflight failed:", file=sys.stderr)
        for error in dict.fromkeys(errors):
            print(f"  - {error}", file=sys.stderr)
        print(
            "Start scripts\\run_service.ps1 first and fix the listed .env values.",
            file=sys.stderr,
        )
        return 1

    print(f"Assessment preflight passed: {service_url.rstrip('/')}/health/ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
