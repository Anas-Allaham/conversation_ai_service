from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import AssessmentItem, CEFRLevel, CurrentPrompt, ItemBank, PromptKind

CALIBRATION_PROMPT = (
    "Before we begin, say your first name, repeat the sentence 'Clear voices are easy to hear,' "
    "and tell me whether you can hear me clearly."
)

CALIBRATION_CLARIFICATION = (
    "Say three things: your first name, the words 'Clear voices are easy to hear,' "
    "and whether you can hear me clearly."
)

MAIN_PREPARATION_SECONDS = {
    CEFRLevel.A1: 5,
    CEFRLevel.A2: 5,
    CEFRLevel.B1: 10,
    CEFRLevel.B2: 15,
}


class ItemBankError(RuntimeError):
    pass


class ItemBankRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.bank = self._load(path)
        self._active = [item for item in self.bank.items if item.status == "active"]
        self._validate_runtime_bank()

    @staticmethod
    def _load(path: Path) -> ItemBank:
        try:
            return ItemBank.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ItemBankError(f"Item bank does not exist: {path}") from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise ItemBankError(f"Invalid item bank {path}: {exc}") from exc

    def _validate_runtime_bank(self) -> None:
        if self.bank.version not in self.path.name:
            raise ItemBankError("Item bank filename and declared version do not match")
        ids = [item.item_id for item in self.bank.items]
        if len(ids) != len(set(ids)):
            raise ItemBankError("Item IDs must be unique")
        for level in CEFRLevel:
            normal = self.items_for(level, kind="normal")
            tie = self.items_for(level, kind="tie_breaker")
            if len(normal) != 3 or len(tie) != 1:
                raise ItemBankError(f"{level.value} must contain 3 normal and 1 tie-breaker item")
            for item in normal:
                if item.review.review_status != "approved":
                    raise ItemBankError(f"Active item {item.item_id} is not approved")
                if item.source != "original_project_item":
                    raise ItemBankError(f"Active item {item.item_id} has invalid provenance")

    def items_for(self, level: CEFRLevel, kind: str) -> list[AssessmentItem]:
        return [item for item in self._active if item.target_level == level and item.kind == kind]

    def get(self, item_id: str) -> AssessmentItem:
        for item in self._active:
            if item.item_id == item_id:
                return item
        raise ItemBankError(f"Active item not found: {item_id}")

    def select_normal(self, level: CEFRLevel, form_seed: str) -> AssessmentItem:
        candidates = sorted(self.items_for(level, "normal"), key=lambda item: item.item_id)
        digest = hashlib.sha256(f"{form_seed}:{level.value}".encode()).digest()
        index = int.from_bytes(digest[:4], "big") % len(candidates)
        return candidates[index]

    def select_tie_breaker(self, level: CEFRLevel) -> AssessmentItem:
        return self.items_for(level, "tie_breaker")[0]

    @staticmethod
    def calibration_prompt() -> CurrentPrompt:
        return CurrentPrompt(
            prompt_id="CALIBRATION_001",
            item_id="CALIBRATION_001",
            target_level=None,
            prompt_kind=PromptKind.CALIBRATION,
            prompt=CALIBRATION_PROMPT,
            clarification_prompt=CALIBRATION_CLARIFICATION,
            response_limit_seconds=30,
            prompt_repetitions_allowed=1,
            preparation_seconds=0,
        )

    @staticmethod
    def prompt_for(item: AssessmentItem, kind: PromptKind) -> CurrentPrompt:
        if kind == PromptKind.MAIN:
            prompt = item.main_prompt
            clarification = item.main_clarification_prompt or prompt
            window = item.expected_response_seconds
            preparation = MAIN_PREPARATION_SECONDS[item.target_level]
        elif kind == PromptKind.FOLLOW_UP:
            if (
                not item.follow_up_prompt
                or not item.follow_up_response_seconds
            ):
                raise ItemBankError(f"Item {item.item_id} has no follow-up")
            prompt = item.follow_up_prompt
            clarification = item.follow_up_clarification_prompt or prompt
            window = item.follow_up_response_seconds
            preparation = 3
        elif kind == PromptKind.TIE_BREAKER:
            prompt = item.main_prompt
            clarification = item.main_clarification_prompt or prompt
            window = item.expected_response_seconds
            preparation = MAIN_PREPARATION_SECONDS[item.target_level]
        else:
            raise ItemBankError(f"Unsupported prompt kind for item: {kind}")
        return CurrentPrompt(
            prompt_id=f"{item.item_id}:{kind.value}",
            item_id=item.item_id,
            target_level=item.target_level,
            prompt_kind=kind,
            prompt=prompt,
            clarification_prompt=clarification,
            response_limit_seconds=window.maximum,
            prompt_repetitions_allowed=item.support_policy.repeat_prompt,
            preparation_seconds=preparation,
        )
