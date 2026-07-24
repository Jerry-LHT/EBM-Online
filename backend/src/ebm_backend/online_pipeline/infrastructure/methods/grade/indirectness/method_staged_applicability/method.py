"""Staged, result-blind GRADE indirectness assessment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ebm_backend.online_pipeline.domain.grade import GRADEIndirectnessInput
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.llm import (
    LLMAPIError,
    LLMConfig,
    call_llm_json,
    load_llm_config,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.aggregation import (
    build_concern_groups,
    build_evidence_profile,
    build_weight_profile,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.classification import (
    classification_schema,
    parse_classification,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.decision import (
    judged_indirectness,
    unavailable_judgement,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.errors import (
    GRADEIndirectnessClassificationError,
    GRADEIndirectnessConfigurationError,
    GRADEIndirectnessInvocationError,
    GRADEIndirectnessJudgementError,
    GRADEIndirectnessThresholdError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.judgement import (
    judgement_schema,
    parse_judgement,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.threshold import (
    not_needed_threshold,
    parse_threshold,
    threshold_requirement,
    threshold_schema,
)


MAX_ATTEMPTS = 2
LLMCaller = Callable[..., dict[str, Any]]
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
CLASSIFIER_PROMPT_PATH = PROMPTS_DIR / "classifier_system.txt"
THRESHOLD_PROMPT_PATH = PROMPTS_DIR / "threshold_system.txt"
JUDGE_PROMPT_PATH = PROMPTS_DIR / "judge_system.txt"


class Method:
    domain = "indirectness"

    def __init__(
        self,
        *,
        config: LLMConfig | dict[str, Any] | None = None,
        caller: LLMCaller = call_llm_json,
    ) -> None:
        try:
            loaded = config if config is not None else load_llm_config()
            if loaded is None:
                raise RuntimeError("Missing required LLM configuration")
            self.config = _disable_sdk_retry(loaded)
            self.classifier_system_prompt = CLASSIFIER_PROMPT_PATH.read_text(
                encoding="utf-8"
            ).strip()
            self.threshold_system_prompt = THRESHOLD_PROMPT_PATH.read_text(
                encoding="utf-8"
            ).strip()
            self.judge_system_prompt = JUDGE_PROMPT_PATH.read_text(
                encoding="utf-8"
            ).strip()
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise GRADEIndirectnessConfigurationError(
                "GRADE indirectness LLM configuration is unavailable"
            ) from exc
        self.caller = caller

    def run(self, *, grade_input: GRADEIndirectnessInput) -> dict[str, Any]:
        if not grade_input.study_evidence:
            return unavailable_judgement(
                "The matched estimate has no available contributing DataRows."
            )
        if len(grade_input.coverage.missing_study_pio_data_row_ids) == len(
            grade_input.study_evidence
        ):
            return unavailable_judgement(
                "No contributing DataRow has usable Study PIO evidence."
            )

        classification, classification_attempts = self._classify(
            grade_input=grade_input,
            prompt=(
                "Classify target-versus-study applicability without observing effect "
                "results. Input JSON:\n"
                + json.dumps(
                    _result_blind_payload(grade_input),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            ),
        )
        weight_profile = build_weight_profile(grade_input)
        concern_groups = build_concern_groups(
            grade_input=grade_input,
            classification=classification,
            weight_profile=weight_profile,
        )
        requirement = threshold_requirement(
            grade_input=grade_input,
            concern_groups=concern_groups,
        )
        if requirement["needed"]:
            threshold_profile, threshold_attempts = self._threshold(
                grade_input=grade_input,
                requirement=requirement,
                prompt=(
                    "Generate one result-blind clinical threshold policy for this "
                    "Summary-of-Findings row. Input JSON:\n"
                    + json.dumps(
                        _threshold_payload(
                            grade_input=grade_input,
                            requirement=requirement,
                            concern_groups=concern_groups,
                        ),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
            )
        else:
            threshold_profile = not_needed_threshold(requirement)
            threshold_attempts = 0

        evidence_profile = build_evidence_profile(
            grade_input=grade_input,
            classification=classification,
            concern_groups=concern_groups,
            threshold_requirement=requirement,
            threshold_profile=threshold_profile,
            weight_profile=weight_profile,
        )
        judgement, judgement_attempts = self._judge(
            grade_input=grade_input,
            prompt=(
                "Make the final bounded GRADE indirectness judgement from frozen "
                "classification and deterministic evidence. Input JSON:\n"
                + json.dumps(
                    {
                        "target": _target_payload(grade_input),
                        "frozen_classification": classification,
                        "evidence_profile": evidence_profile,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            ),
            evidence_profile=evidence_profile,
        )
        return judged_indirectness(
            judgement=judgement,
            classification=classification,
            evidence_profile=evidence_profile,
            execution_trace=_execution_trace(
                classification_attempts=classification_attempts,
                threshold_attempts=threshold_attempts,
                judgement_attempts=judgement_attempts,
                threshold_requirement=requirement,
                evidence_profile=evidence_profile,
            ),
        )

    def _classify(
        self,
        *,
        grade_input: GRADEIndirectnessInput,
        prompt: str,
    ) -> tuple[dict[str, Any], int]:
        expected_rows = [
            (
                item.data_row_id,
                item.study_id,
                _domain_availability(item),
            )
            for item in grade_input.study_evidence
        ]
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                raw = self.caller(
                    config=self.config,
                    system=self.classifier_system_prompt,
                    prompt=prompt,
                    json_schema=classification_schema(),
                    json_schema_name="grade_indirectness_result_blind_classification",
                )
                return parse_classification(raw, expected_rows=expected_rows), attempt
            except LLMAPIError as exc:
                last_error = exc
                if not exc.retryable:
                    raise _invocation_error(
                        grade_input, "study_classification", attempt, False, exc
                    )
            except ValueError as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    raise GRADEIndirectnessClassificationError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                    ) from exc
        raise _invocation_error(
            grade_input,
            "study_classification",
            MAX_ATTEMPTS,
            True,
            last_error,
        )

    def _threshold(
        self,
        *,
        grade_input: GRADEIndirectnessInput,
        requirement: dict[str, Any],
        prompt: str,
    ) -> tuple[dict[str, Any], int]:
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                raw = self.caller(
                    config=self.config,
                    system=self.threshold_system_prompt,
                    prompt=prompt,
                    json_schema=threshold_schema(
                        effect_scale=requirement["threshold_scale"]
                    ),
                    json_schema_name="grade_indirectness_clinical_threshold",
                )
                return parse_threshold(raw, requirement=requirement), attempt
            except LLMAPIError as exc:
                last_error = exc
                if not exc.retryable:
                    raise _invocation_error(
                        grade_input, "threshold_generation", attempt, False, exc
                    )
            except ValueError as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    raise GRADEIndirectnessThresholdError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                    ) from exc
        raise _invocation_error(
            grade_input,
            "threshold_generation",
            MAX_ATTEMPTS,
            True,
            last_error,
        )

    def _judge(
        self,
        *,
        grade_input: GRADEIndirectnessInput,
        prompt: str,
        evidence_profile: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                raw = self.caller(
                    config=self.config,
                    system=self.judge_system_prompt,
                    prompt=prompt,
                    json_schema=judgement_schema(evidence_profile=evidence_profile),
                    json_schema_name="grade_indirectness_bounded_judgement",
                )
                return parse_judgement(
                    raw, evidence_profile=evidence_profile
                ), attempt
            except LLMAPIError as exc:
                last_error = exc
                if not exc.retryable:
                    raise _invocation_error(
                        grade_input, "evidence_body_judgement", attempt, False, exc
                    )
            except ValueError as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    raise GRADEIndirectnessJudgementError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                    ) from exc
        raise _invocation_error(
            grade_input,
            "evidence_body_judgement",
            MAX_ATTEMPTS,
            True,
            last_error,
        )


def build_method(
    *,
    config: LLMConfig | dict[str, Any] | None = None,
    caller: LLMCaller = call_llm_json,
) -> Method:
    return Method(config=config, caller=caller)


def _result_blind_payload(grade_input: GRADEIndirectnessInput) -> dict[str, Any]:
    return {
        "task": "Classify study-level PICO applicability without effect results.",
        "target": _target_payload(grade_input),
        "studies": [
            {
                "data_row_id": item.data_row_id,
                "study_id": item.study_id,
                "domain_information_available": _domain_availability(item),
                "result_mapping": {
                    "comparison": to_jsonable(item.comparison),
                    "outcome": to_jsonable(item.outcome),
                    "subgroup": to_jsonable(item.subgroup),
                },
                "study_pio": {
                    "population": to_jsonable(item.population),
                    "intervention": to_jsonable(item.intervention),
                    "comparator": to_jsonable(item.comparator),
                    "outcome": to_jsonable(item.study_outcome),
                },
                "mapping_status": to_jsonable(item.mapping_status),
                "candidate_interventions": to_jsonable(item.candidate_interventions),
                "candidate_comparators": to_jsonable(item.candidate_comparators),
                "candidate_outcomes": to_jsonable(item.candidate_outcomes),
            }
            for item in grade_input.study_evidence
        ],
        "result_blinding": {
            "study_effects_provided": False,
            "pooled_effect_provided": False,
            "weights_provided": False,
            "heterogeneity_provided": False,
            "subgroup_results_provided": False,
        },
    }


def _threshold_payload(
    *,
    grade_input: GRADEIndirectnessInput,
    requirement: dict[str, Any],
    concern_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = {
        group_id for group_id in requirement["candidate_group_ids"]
    }
    return {
        "task": (
            "Specify clinically important benefit and harm boundaries without "
            "observing study or meta-analysis results."
        ),
        "target": _target_payload(grade_input),
        "threshold_request": requirement,
        "applicability_concern_types": [
            {
                "domain": group["domain"],
                "facet": group["facet"],
                "mechanism": group["mechanism"],
            }
            for group in concern_groups
            if group["group_id"] in selected
        ],
        "result_blinding": {
            "study_effects_provided": False,
            "pooled_effect_provided": False,
            "weights_provided": False,
            "observed_control_risks_provided": False,
        },
    }


def _target_payload(grade_input: GRADEIndirectnessInput) -> dict[str, Any]:
    return {
        "review_scope_pico": {
            "population": list(grade_input.review_population),
            "intervention": list(grade_input.review_intervention),
            "comparator": list(grade_input.review_comparator),
            "outcome": list(grade_input.review_outcome),
        },
        "synthesis_target": to_jsonable(grade_input.setting),
        "screening_criteria": to_jsonable(grade_input.screening_criteria),
    }


def _domain_availability(item: Any) -> dict[str, bool]:
    return {
        "population": item.population is not None,
        "intervention": item.intervention is not None
        and item.mapping_status.intervention == "matched",
        "comparator": item.comparator is not None
        and item.mapping_status.comparator == "matched",
        "outcome": item.study_outcome is not None
        and item.mapping_status.outcome == "matched",
    }


def _invocation_error(
    grade_input: GRADEIndirectnessInput,
    stage: str,
    attempts: int,
    retry_exhausted: bool,
    cause: Exception | None,
) -> GRADEIndirectnessInvocationError:
    error = GRADEIndirectnessInvocationError(
        setting_id=grade_input.setting.setting_id,
        stage=stage,
        attempts=attempts,
        retry_exhausted=retry_exhausted,
    )
    if cause is not None:
        error.__cause__ = cause
    return error


def _disable_sdk_retry(config: LLMConfig | dict[str, Any]) -> dict[str, Any]:
    payload = config.to_dict() if isinstance(config, LLMConfig) else dict(config)
    payload["sdk_max_retries"] = 0
    payload["json_marker_retry_enabled"] = False
    return payload


def _execution_trace(
    *,
    classification_attempts: int,
    threshold_attempts: int,
    judgement_attempts: int,
    threshold_requirement: dict[str, Any],
    evidence_profile: dict[str, Any],
) -> dict[str, Any]:
    effect_profile = evidence_profile["effect_range_profile"]
    return {
        "stage_attempts": {
            "study_classification": classification_attempts,
            "threshold_generation": threshold_attempts,
            "evidence_body_judgement": judgement_attempts,
        },
        "threshold_gate": {
            "needed": threshold_requirement["needed"],
            "reason": threshold_requirement["reason"],
        },
        "weight_coverage": evidence_profile["weight_coverage"],
        "numeric_warnings": effect_profile["numeric_warnings"],
        "baseline_risk_evaluations": [
            {
                "data_row_id": row["data_row_id"],
                "evaluations": row["target_baseline_evaluations"],
            }
            for row in effect_profile["row_ranges"]
            if row["target_baseline_evaluations"]
        ],
        "concern_range_aggregation": effect_profile["concern_concordance"],
    }
