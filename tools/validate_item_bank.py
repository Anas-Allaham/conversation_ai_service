from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from services.oral_assessment.item_bank import ItemBankRepository
from services.oral_assessment.models import CEFRLevel


def main() -> None:
    data_root = ROOT / "src" / "services" / "oral_assessment" / "data"
    path = data_root / "item_bank_v0.2.0.json"
    bank = ItemBankRepository(path)
    assert len(bank.bank.items) == 16
    for level in CEFRLevel:
        assert len(bank.items_for(level, "normal")) == 3
        assert len(bank.items_for(level, "tie_breaker")) == 1
    schemas = [
        data_root / "item_schema.json",
        data_root / "pronunciation_event_schema.json",
        data_root / "pronunciation_result_schema.json",
    ]
    for schema in schemas:
        json.loads(schema.read_text(encoding="utf-8"))
    print(
        f"Validated item bank {bank.bank.version}: 16 active original records, "
        "3 normal + 1 same-level boundary item per level."
    )


if __name__ == "__main__":
    main()
