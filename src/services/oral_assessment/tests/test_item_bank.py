from __future__ import annotations

import unittest

from services.oral_assessment.item_bank import ItemBankRepository
from services.oral_assessment.models import CEFRLevel

from .helpers import PROJECT_ROOT


class ItemBankTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bank = ItemBankRepository(
            PROJECT_ROOT / "services" / "oral_assessment" / "data" / "item_bank_v0.2.0.json"
        )

    def test_bank_has_required_frozen_inventory(self) -> None:
        self.assertEqual(16, len(self.bank.bank.items))
        for level in CEFRLevel:
            self.assertEqual(3, len(self.bank.items_for(level, "normal")))
            self.assertEqual(1, len(self.bank.items_for(level, "tie_breaker")))

    def test_only_original_approved_items_are_active(self) -> None:
        for item in self.bank.bank.items:
            if item.status == "active":
                self.assertEqual("original_project_item", item.source)
                self.assertEqual("approved", item.review.review_status)
                self.assertFalse(item.grammar_independently_scored)
                if item.kind == "normal":
                    self.assertTrue(item.follow_up_prompt)

    def test_form_selection_is_deterministic(self) -> None:
        first = self.bank.select_normal(CEFRLevel.B1, "same-form")
        second = self.bank.select_normal(CEFRLevel.B1, "same-form")
        self.assertEqual(first.item_id, second.item_id)


if __name__ == "__main__":
    unittest.main()
