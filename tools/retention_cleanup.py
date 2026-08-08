from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.oral_assessment.config import Settings
from services.oral_assessment.storage import build_audio_storage


def main() -> None:
    settings = Settings.from_env()
    storage = build_audio_storage(settings)
    deleted = storage.delete_expired(settings.audio_retention_days)
    print(f"Deleted {deleted} encrypted audio objects older than {settings.audio_retention_days} days.")


if __name__ == "__main__":
    main()
