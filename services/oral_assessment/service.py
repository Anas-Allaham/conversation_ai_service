from __future__ import annotations

import threading
import uuid
from collections import defaultdict

from .branching_engine import decide_stage_evidence, tie_breaker_passed
from .config import Settings
from .item_bank import ItemBankRepository
from .models import (
    LEVELS,
    AssessmentCreateRequest,
    AssessmentCreateResponse,
    AssessmentProgress,
    AssessmentRecord,
    AssessmentResult,
    AssessmentStatus,
    AudioQuality,
    CEFRLevel,
    CurrentPrompt,
    DimensionEvidence,
    DimensionScores,
    NextAction,
    NextActionType,
    PromptKind,
    ResponseDecision,
    ResponseResult,
    ResponseSubmission,
    ScoredResponse,
    StoredResponse,
    VersionSet,
    utc_now,
)
from .repository import AssessmentRepository, ConcurrencyConflict
from .result_aggregator import build_result
from .rubric_evaluator import EvaluationInput, EvaluationUnavailable, RubricEvaluator
from .scoring_engine import score_evaluator_output
from .speech_metrics import extract_speech_metrics, invalid_audio_reason


class AssessmentNotFound(LookupError):
    pass


class InvalidAssessmentState(RuntimeError):
    pass


class SubmissionConflict(RuntimeError):
    pass


class AssessmentService:
    def __init__(
        self,
        settings: Settings,
        repository: AssessmentRepository,
        item_bank: ItemBankRepository,
        evaluator: RubricEvaluator,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.item_bank = item_bank
        self.evaluator = evaluator
        self._locks: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)

    def create_assessment(
        self, request: AssessmentCreateRequest, correlation_id: str = ""
    ) -> AssessmentCreateResponse:
        assessment_id = f"assess-{uuid.uuid4()}"
        now = utc_now()
        prompt = self.item_bank.calibration_prompt()
        versions = VersionSet(
            assessment=self.settings.assessment_version,
            item_bank=self.item_bank.bank.version,
            rubric=self.settings.rubric_version,
            scorer=self.settings.scorer_version,
        )
        record = AssessmentRecord(
            assessment_id=assessment_id,
            user_id=request.user_id,
            status=AssessmentStatus.IN_PROGRESS,
            current_level_index=0,
            current_item_id=prompt.item_id,
            current_prompt_kind=prompt.prompt_kind,
            current_prompt_id=prompt.prompt_id,
            form_seed=request.form_seed or assessment_id,
            created_at=now,
            updated_at=now,
            versions=versions,
            interface_language=request.interface_language,
        )
        self.repository.create_assessment(record, correlation_id)
        return AssessmentCreateResponse(
            assessment_id=assessment_id,
            status=record.status,
            current_item=prompt,
            assessment_version=versions.assessment,
            item_bank_version=versions.item_bank,
            progress=self.progress(record, questions_answered=0),
        )

    def _record(self, assessment_id: str) -> AssessmentRecord:
        record = self.repository.get_assessment(assessment_id)
        if record is None:
            raise AssessmentNotFound(assessment_id)
        return record

    def current_prompt(self, record: AssessmentRecord) -> CurrentPrompt:
        if record.current_prompt_kind == PromptKind.CALIBRATION:
            return self.item_bank.calibration_prompt()
        item = self.item_bank.get(record.current_item_id)
        return self.item_bank.prompt_for(item, record.current_prompt_kind)

    def progress(
        self,
        record: AssessmentRecord,
        *,
        questions_answered: int | None = None,
    ) -> AssessmentProgress:
        if questions_answered is None:
            questions_answered = len(self.repository.list_responses(record.assessment_id))

        confirmed: list[CEFRLevel] = []
        if record.highest_confirmed_level is not None:
            confirmed = LEVELS[: LEVELS.index(record.highest_confirmed_level) + 1]

        if record.status in {AssessmentStatus.COMPLETED, AssessmentStatus.CANCELLED}:
            return AssessmentProgress(
                status=record.status,
                current_section="complete" if record.status == AssessmentStatus.COMPLETED else "cancelled",
                current_prompt_kind=None,
                questions_answered=questions_answered,
                confirmed_levels=confirmed,
                estimated_questions_remaining_min=0,
                estimated_questions_remaining_max=0,
                display_text="Assessment complete." if record.status == AssessmentStatus.COMPLETED else "Assessment cancelled.",
            )

        if record.current_prompt_kind == PromptKind.CALIBRATION:
            current_section = "audio check"
            minimum = 1 + 2
            maximum = 1 + len(LEVELS) * 3
        else:
            level = LEVELS[record.current_level_index]
            current_section = level.value
            within = {
                PromptKind.MAIN: (2, 3),
                PromptKind.FOLLOW_UP: (1, 2),
                PromptKind.TIE_BREAKER: (1, 1),
            }[record.current_prompt_kind]
            higher_levels = len(LEVELS) - record.current_level_index - 1
            minimum = within[0]
            maximum = within[1] + higher_levels * 3

        display = (
            f"{questions_answered} responses completed; approximately {minimum} to {maximum} "
            "questions remain because the assessment is adaptive."
        )
        return AssessmentProgress(
            status=record.status,
            current_section=current_section,
            current_prompt_kind=record.current_prompt_kind,
            questions_answered=questions_answered,
            confirmed_levels=confirmed,
            estimated_questions_remaining_min=minimum,
            estimated_questions_remaining_max=maximum,
            display_text=display,
        )

    @staticmethod
    def _invalid_score(reason: str) -> ScoredResponse:
        evidence = DimensionEvidence(
            task_achievement=reason,
            interactive_communication=reason,
            fluency=reason,
            coherence=reason,
            lexical_adequacy=reason,
            intelligibility=reason,
        )
        return ScoredResponse(
            scores=DimensionScores(
                task_achievement=0,
                interactive_communication=0,
                fluency=0,
                coherence=0,
                lexical_adequacy=0,
                intelligibility=0,
            ),
            weighted_score=0,
            decision=ResponseDecision.INVALID_AUDIO,
            meaning_blocked=False,
            audio_quality=AudioQuality.INVALID,
            evaluator_confidence="low",
            evidence=evidence,
            decision_reasons=[reason],
            evaluator_provider="validity-gate",
            evaluator_model="deterministic-audio-v1",
        )

    def _validate_submission(self, record: AssessmentRecord, submission: ResponseSubmission) -> None:
        if submission.prompt_id != record.current_prompt_id:
            raise SubmissionConflict(
                f"Expected prompt_id {record.current_prompt_id}; received {submission.prompt_id}"
            )
        if submission.item_id != record.current_item_id:
            raise SubmissionConflict(
                f"Expected item_id {record.current_item_id}; received {submission.item_id}"
            )
        if submission.prompt_kind != record.current_prompt_kind:
            raise SubmissionConflict(
                f"Expected prompt_kind {record.current_prompt_kind.value}; received {submission.prompt_kind.value}"
            )

    def submit_response(
        self,
        assessment_id: str,
        submission: ResponseSubmission,
        correlation_id: str = "",
    ) -> ResponseResult:
        replay = self.repository.get_response_replay(assessment_id, submission.idempotency_key)
        if replay:
            return replay
        if self.repository.get_response_by_id(assessment_id, submission.response_id):
            raise SubmissionConflict("response_id was already used with a different idempotency key")
        with self._locks[assessment_id]:
            replay = self.repository.get_response_replay(assessment_id, submission.idempotency_key)
            if replay:
                return replay
            if self.repository.get_response_by_id(assessment_id, submission.response_id):
                raise SubmissionConflict("response_id was already used with a different idempotency key")
            record = self._record(assessment_id)
            if record.status != AssessmentStatus.IN_PROGRESS:
                raise InvalidAssessmentState(f"Assessment is {record.status.value}")
            self._validate_submission(record, submission)
            metrics = extract_speech_metrics(submission)
            invalid_reason = invalid_audio_reason(submission, metrics)

            if record.current_prompt_kind == PromptKind.CALIBRATION:
                scored = self._invalid_score(invalid_reason) if invalid_reason else None
                result = self._handle_calibration(record, submission, invalid_reason)
            else:
                item = self.item_bank.get(record.current_item_id)
                prompt = self.current_prompt(record)
                if invalid_reason:
                    scored = self._invalid_score(invalid_reason)
                else:
                    try:
                        evaluator_output = self.evaluator.evaluate(
                            EvaluationInput(
                                item=item,
                                prompt_kind=record.current_prompt_kind,
                                prompt_text=prompt.prompt,
                                submission=submission,
                                metrics=metrics,
                            )
                        )
                    except EvaluationUnavailable:
                        record.evaluator_failure_count += 1
                        record.updated_at = utc_now()
                        self.repository.save_record(record)
                        self.repository.audit(
                            "evaluator.unavailable",
                            {
                                "response_id": submission.response_id,
                                "prompt_id": submission.prompt_id,
                                "failure_count": record.evaluator_failure_count,
                            },
                            assessment_id,
                            correlation_id,
                        )
                        raise
                    scored = score_evaluator_output(
                        evaluator_output,
                        provider=self.evaluator.provider_name,
                        model=self.evaluator.model_name,
                    )
                result = self._advance_scored_response(record, submission, scored)

            stored = StoredResponse(
                assessment_id=assessment_id,
                submission=submission,
                metrics=metrics,
                scored=scored,
                created_at=utc_now(),
            )
            record.updated_at = utc_now()
            try:
                self.repository.save_transition(record, stored, result, correlation_id)
            except ConcurrencyConflict as exc:
                replay = self.repository.get_response_replay(assessment_id, submission.idempotency_key)
                if replay:
                    return replay
                raise SubmissionConflict(str(exc)) from exc
            return result

    def _set_prompt(self, record: AssessmentRecord, prompt: CurrentPrompt) -> None:
        record.current_item_id = prompt.item_id
        record.current_prompt_kind = prompt.prompt_kind
        record.current_prompt_id = prompt.prompt_id

    def _result(
        self,
        record: AssessmentRecord,
        submission: ResponseSubmission,
        decision: ResponseDecision,
        stage_status: str,
        action: NextAction,
        weighted: float | None = None,
    ) -> ResponseResult:
        current_level = LEVELS[record.current_level_index] if record.current_level_index < len(LEVELS) else None
        return ResponseResult(
            assessment_id=record.assessment_id,
            response_id=submission.response_id,
            response_decision=decision,
            weighted_score=weighted,
            stage_status=stage_status,
            next_action=action,
            current_level=current_level,
            progress=self.progress(
                record,
                questions_answered=len(self.repository.list_responses(record.assessment_id)) + 1,
            ),
        )

    def _handle_calibration(
        self,
        record: AssessmentRecord,
        submission: ResponseSubmission,
        invalid_reason: str | None,
    ) -> ResponseResult:
        if invalid_reason:
            record.invalid_audio_count += 1
            existing = [
                response
                for response in self.repository.list_responses(record.assessment_id)
                if response.submission.prompt_id == record.current_prompt_id
                and response.scored
                and response.scored.decision == ResponseDecision.INVALID_AUDIO
            ]
            if len(existing) + 1 >= 2:
                self._complete(record, first_unconfirmed=None, reason="audio_unusable")
                return self._result(
                    record,
                    submission,
                    ResponseDecision.INVALID_AUDIO,
                    "completed_without_placement",
                    NextAction(
                        type=NextActionType.SHOW_RESULT,
                        message="I could not obtain usable audio, so no level was assigned.",
                    ),
                )
            prompt = self.item_bank.calibration_prompt()
            return self._result(
                record,
                submission,
                ResponseDecision.INVALID_AUDIO,
                "calibration_repeat_required",
                NextAction(type=NextActionType.REPEAT_PROMPT, prompt=prompt, message=invalid_reason),
            )
        item = self.item_bank.select_normal(CEFRLevel.A1, record.form_seed)
        prompt = self.item_bank.prompt_for(item, PromptKind.MAIN)
        self._set_prompt(record, prompt)
        return self._result(
            record,
            submission,
            ResponseDecision.NOT_SCORED,
            "calibration_passed",
            NextAction(type=NextActionType.ASK_MAIN, prompt=prompt),
        )

    def _invalid_repeat_or_stop(
        self,
        record: AssessmentRecord,
        submission: ResponseSubmission,
        scored: ScoredResponse,
    ) -> ResponseResult | None:
        if scored.decision != ResponseDecision.INVALID_AUDIO:
            return None
        record.invalid_audio_count += 1
        existing = [
            response
            for response in self.repository.list_responses(record.assessment_id)
            if response.submission.prompt_id == record.current_prompt_id
            and response.scored
            and response.scored.decision == ResponseDecision.INVALID_AUDIO
        ]
        if len(existing) + 1 >= 2:
            current_level = LEVELS[record.current_level_index]
            self._complete(record, first_unconfirmed=current_level, reason="audio_unusable")
            return self._result(
                record,
                submission,
                ResponseDecision.INVALID_AUDIO,
                "completed_with_low_confidence",
                NextAction(
                    type=NextActionType.SHOW_RESULT,
                    message="Audio remained unusable. Earlier confirmed evidence is preserved; this level was not downgraded.",
                ),
            )
        return self._result(
            record,
            submission,
            ResponseDecision.INVALID_AUDIO,
            "repeat_required",
            NextAction(
                type=NextActionType.REPEAT_PROMPT,
                prompt=self.current_prompt(record),
                message=scored.decision_reasons[0],
            ),
        )

    def _advance_scored_response(
        self,
        record: AssessmentRecord,
        submission: ResponseSubmission,
        scored: ScoredResponse,
    ) -> ResponseResult:
        invalid_result = self._invalid_repeat_or_stop(record, submission, scored)
        if invalid_result:
            return invalid_result
        item = self.item_bank.get(record.current_item_id)
        if record.current_prompt_kind == PromptKind.MAIN:
            prompt = self.item_bank.prompt_for(item, PromptKind.FOLLOW_UP)
            self._set_prompt(record, prompt)
            return self._result(
                record,
                submission,
                scored.decision,
                "follow_up_required",
                NextAction(type=NextActionType.ASK_FOLLOW_UP, prompt=prompt),
                scored.weighted_score,
            )
        if record.current_prompt_kind == PromptKind.FOLLOW_UP:
            previous = [
                response
                for response in self.repository.list_responses(record.assessment_id)
                if response.submission.item_id == item.item_id
                and response.submission.prompt_kind == PromptKind.MAIN
                and response.scored
                and response.scored.decision != ResponseDecision.INVALID_AUDIO
            ]
            if not previous or previous[-1].scored is None:
                raise InvalidAssessmentState("Follow-up response has no valid main observation")
            stage = decide_stage_evidence(previous[-1].scored, scored)
            if stage.value == "pass":
                return self._pass_stage(record, submission, scored)
            return self._request_boundary_verification(record, submission, scored)
        if record.current_prompt_kind == PromptKind.TIE_BREAKER:
            if tie_breaker_passed(scored.decision):
                return self._pass_stage(record, submission, scored)
            return self._fail_stage(record, submission, scored)
        raise InvalidAssessmentState(f"Unsupported prompt kind {record.current_prompt_kind}")

    def _request_boundary_verification(
        self,
        record: AssessmentRecord,
        submission: ResponseSubmission,
        scored: ScoredResponse,
    ) -> ResponseResult:
        """Use a different same-level task before closing a level boundary."""
        level = LEVELS[record.current_level_index]
        if level in record.boundary_verification_levels:
            return self._fail_stage(record, submission, scored)
        tie = self.item_bank.select_tie_breaker(level)
        prompt = self.item_bank.prompt_for(tie, PromptKind.TIE_BREAKER)
        record.tie_breaker_count += 1
        record.boundary_verification_levels.append(level)
        self._set_prompt(record, prompt)
        return self._result(
            record,
            submission,
            scored.decision,
            "boundary_verification_required",
            NextAction(type=NextActionType.ASK_TIE_BREAKER, prompt=prompt),
            scored.weighted_score,
        )

    def _pass_stage(
        self, record: AssessmentRecord, submission: ResponseSubmission, scored: ScoredResponse
    ) -> ResponseResult:
        level = LEVELS[record.current_level_index]
        record.highest_confirmed_level = level
        if level == CEFRLevel.B2:
            self._complete(record, first_unconfirmed=None, reason="ceiling_reached")
            return self._post_placement_action(record, submission, scored)
        record.current_level_index += 1
        next_level = LEVELS[record.current_level_index]
        item = self.item_bank.select_normal(next_level, record.form_seed)
        prompt = self.item_bank.prompt_for(item, PromptKind.MAIN)
        self._set_prompt(record, prompt)
        return self._result(
            record,
            submission,
            scored.decision,
            "level_passed",
            NextAction(type=NextActionType.ASK_MAIN, prompt=prompt),
            scored.weighted_score,
        )

    def _fail_stage(
        self, record: AssessmentRecord, submission: ResponseSubmission, scored: ScoredResponse
    ) -> ResponseResult:
        level = LEVELS[record.current_level_index]
        self._complete(
            record,
            first_unconfirmed=level,
            reason="first_unconfirmed_level_reached",
        )
        return self._post_placement_action(record, submission, scored)

    def _complete(
        self,
        record: AssessmentRecord,
        *,
        first_unconfirmed: CEFRLevel | None,
        reason: str,
    ) -> None:
        record.first_unconfirmed_level = first_unconfirmed
        record.provisional_unconfirmed_level = None
        record.completion_reason = reason
        record.completed_at = utc_now()
        record.status = AssessmentStatus.COMPLETED

    def _post_placement_action(
        self, record: AssessmentRecord, submission: ResponseSubmission, scored: ScoredResponse
    ) -> ResponseResult:
        return self._result(
            record,
            submission,
            scored.decision,
            "assessment_completed",
            NextAction(type=NextActionType.SHOW_RESULT, message="Your placement profile is ready."),
            scored.weighted_score,
        )

    def get_result(self, assessment_id: str) -> AssessmentResult:
        record = self._record(assessment_id)
        if record.status == AssessmentStatus.IN_PROGRESS:
            raise InvalidAssessmentState("Assessment is still in progress")
        responses = self.repository.list_responses(assessment_id)
        pronunciation = self.repository.get_pronunciation(assessment_id)
        return build_result(record, responses, pronunciation)

    def cancel(self, assessment_id: str, correlation_id: str = "") -> None:
        with self._locks[assessment_id]:
            record = self._record(assessment_id)
            if record.status in {AssessmentStatus.COMPLETED, AssessmentStatus.CANCELLED}:
                return
            record.status = AssessmentStatus.CANCELLED
            record.completion_reason = "cancelled"
            record.completed_at = utc_now()
            record.updated_at = utc_now()
            self.repository.save_record(record)
            self.repository.audit(
                "assessment.cancelled", {"status": record.status.value}, assessment_id, correlation_id
            )
