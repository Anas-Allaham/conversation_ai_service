from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from services.guided_conversation.models import GuidedScenario


def main() -> None:
    target = (
        ROOT / "src" / "services" / "guided_conversation" / "content" / "_scenario_schema.json"
    )
    target.write_text(
        json.dumps(GuidedScenario.model_json_schema(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
