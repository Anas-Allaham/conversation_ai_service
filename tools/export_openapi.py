from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        os.environ["ASSESSMENT_DATABASE_URL"] = (
            f"sqlite:///{Path(directory) / 'openapi.db'}"
        )
        os.environ.setdefault("EVALUATOR_PROVIDER", "heuristic")
        os.environ.setdefault("ALLOW_HEURISTIC_EVALUATOR", "true")
        os.environ.setdefault("ASSESSMENT_SERVICE_TOKEN", "openapi-export-token")
        os.environ.setdefault("ASSESSMENT_ADMIN_TOKEN", "openapi-export-admin-token")
        from services.oral_assessment.main import create_app

        schema = create_app(ROOT).openapi()
    target = ROOT / "docs" / "api" / "openapi.yaml"
    target.write_text(
        yaml.safe_dump(schema, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
