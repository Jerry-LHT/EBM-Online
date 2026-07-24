from __future__ import annotations

from dataclasses import replace
import json

import pytest

from ebm_backend.online_pipeline.domain.common import DataType, EstimationStatus
from ebm_backend.online_pipeline.domain.grade import (
    GRADEInconsistencyCoverage,
    GRADEInconsistencyEstimate,
    GRADEInconsistencyInput,
    GRADEInconsistencySetting,
    GRADEInconsistencyStudyEffect,
)
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSubgroup,
    AnalysisTimepoint,
    HeterogeneitySummary,
    StudyResultComparison,
    StudyResultOutcome,
    SubgroupDifferenceTest,
    SubgroupEstimate,
)
from ebm_backend.online_pipeline.domain.study_characteristics import (
    StudyPIOCharacteristics,
    StudyPopulationCharacteristics,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMAPIError
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.errors import (
    GRADEInconsistencyInvocationError,
    GRADEInconsistencyJudgementError,
    GRADEInconsistencyPolicyError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.method import (
    Method,
)


CONFIG = {
    "api_key": "test-key",
    "base_url": "https://example.invalid/v1",
    "model": "test-model",
    "api_mode": "responses",
}


def test_policy_input_is_result_blind_and_same_range_bypasses_judge() -> None:
    captured = []

    def caller(**kwargs):
        captured.append(kwargs)
        return _policy()

    result = Method(config=CONFIG, caller=caller).run(
        grade_input=_grade_input([0.65, 0.75], i2=91.0)
    )

    assert len(captured) == 1
    payload = json.loads(captured[0]["prompt"].split("Input JSON:\n", 1)[1])
    assert payload["result_blinding"] == {
        "observed_study_effects_provided": False,
        "pooled_effect_provided": False,
        "heterogeneity_statistics_provided": False,
        "subgroup_results_provided": False,
    }
    assert '"effect_value"' not in captured[0]["prompt"]
    assert '"heterogeneity":' not in captured[0]["prompt"]
    assert captured[0]["config"]["sdk_max_retries"] == 0
    assert captured[0]["config"]["json_marker_retry_enabled"] is False
    assert captured[0]["json_schema_name"] == "grade_inconsistency_result_blind_policy"
    assert result["levels"] == 0
    assert result["decision_features"]["judge"] is None


def test_multi_range_flow_freezes_policy_then_calls_bounded_judge() -> None:
    calls = []

    def caller(**kwargs):
        calls.append(kwargs)
        if kwargs["json_schema_name"] == "grade_inconsistency_result_blind_policy":
            return _policy()
        return _judgement(
            severity="serious",
            evidence=[("important_benefit", ["row-1"]), ("no_important_effect", ["row-2"])],
        )

    result = Method(config=CONFIG, caller=caller).run(
        grade_input=_grade_input([0.65, 1.0], i2=70.0)
    )

    assert [item["json_schema_name"] for item in calls] == [
        "grade_inconsistency_result_blind_policy",
        "grade_inconsistency_bounded_judgement",
    ]
    judge_payload = json.loads(calls[1]["prompt"].split("Input JSON:\n", 1)[1])
    assert judge_payload["frozen_policy"]["effect_range_policy"]["important_benefit_boundary"] == 0.8
    profile = judge_payload["evidence_profile"]
    assert profile["threshold_span"] == 1
    assert profile["heterogeneity"]["i2"] == 70.0
    assert profile["range_distribution"]["important_benefit"]["weight_fraction"] == 0.5
    assert profile["range_distribution"]["no_important_effect"]["weight_fraction"] == 0.5
    assert profile["pooled_estimate"]["point_range"] == "no_important_effect"
    assert profile["pooled_estimate"]["ci_ranges"] == [
        "important_benefit",
        "no_important_effect",
    ]
    assert profile["pooled_estimate"]["ci_crosses_frozen_threshold"] is True
    assert result["levels"] == 1
    assert result["decision_features"]["judge"]["distribution_is_meaningful"] is True
    assert "confidence interval spans: important_benefit, no_important_effect" in result["rationale"]


def test_judge_not_hardcoded_distribution_rule_controls_final_severity() -> None:
    result = _run(
        [0.65, 1.0],
        policy=_policy(),
        judgement=_judgement(
            severity="none",
            meaningful=False,
            imprecision_overlap=True,
            evidence=[("important_benefit", ["row-1"]), ("no_important_effect", ["row-2"])],
        ),
    )

    assert result["levels"] == 0
    assert result["severity"] == "not_serious"
    assert result["assessment_status"] == "assessed"
    assert result["decision_features"]["judge"]["imprecision_overlap_risk"] is True


def test_very_serious_requires_multiple_frozen_thresholds() -> None:
    result = _run(
        [0.65, 1.35],
        policy=_policy(),
        judgement=_judgement(
            severity="very_serious",
            evidence=[("important_benefit", ["row-1"]), ("important_harm", ["row-2"])],
        ),
    )
    assert result["levels"] == 2

    with pytest.raises(GRADEInconsistencyJudgementError):
        _run(
            [0.75, 1.25],
            policy=_policy(with_boundaries=False),
            judgement=_judgement(
                severity="very_serious",
                target_range="below_no_effect",
                pooled_ci_ranges=["at_no_effect", "below_no_effect"],
                evidence=[("below_no_effect", ["row-1"]), ("above_no_effect", ["row-2"])],
            ),
        )


def test_judge_must_reference_real_rows_in_their_deterministic_ranges() -> None:
    invalid = _judgement(
        severity="serious",
        evidence=[("important_harm", ["row-1"]), ("no_important_effect", ["row-2"])],
    )
    with pytest.raises(GRADEInconsistencyJudgementError) as raised:
        _run([0.65, 1.0], policy=_policy(), judgement=invalid)
    assert raised.value.attempts == 2


def test_result_blind_modifier_and_subgroup_test_can_explain_variation() -> None:
    grade_input = _grade_input([0.65, 1.0], i2=70.0)
    grade_input = replace(
        grade_input,
        subgroup_estimates=[
            _subgroup_estimate("sub-younger", "younger", ["study-1"]),
            _subgroup_estimate("sub-older", "older", ["study-2"]),
        ],
        subgroup_difference_tests=[
            SubgroupDifferenceTest(
                test_id="test-age",
                setting_family_id="family-1",
                subgroup_factor="age group",
                compared_subgroup_estimate_ids=["sub-younger", "sub-older"],
                test_status="computed",
                p_value=0.01,
            )
        ],
    )
    calls = []

    def caller(**kwargs):
        calls.append(kwargs)
        if kwargs["json_schema_name"] == "grade_inconsistency_result_blind_policy":
            return _policy(with_modifier=True)
        return _judgement(
            severity="none",
            explained=True,
            meaningful=True,
            factor="age group",
            test_id="test-age",
            evidence=[("important_benefit", ["row-1"]), ("no_important_effect", ["row-2"])],
        )

    result = Method(config=CONFIG, caller=caller).run(grade_input=grade_input)

    assert result["levels"] == 0
    assert result["decision_features"]["judge"]["inconsistency_explained"] is True
    profile = json.loads(calls[1]["prompt"].split("Input JSON:\n", 1)[1])["evidence_profile"]
    assert profile["subgroup_evidence"][0]["test_id"] == "test-age"
    assert profile["subgroup_evidence"][0]["p_value"] == 0.01
    assert "effect modifier 'age group'" in result["rationale"]
    assert "subgroup test 'test-age'" in result["rationale"]


def test_judge_cannot_reinterpret_deterministic_pooled_ci_ranges() -> None:
    invalid = _judgement(
        severity="serious",
        pooled_ci_ranges=["important_benefit"],
        evidence=[("important_benefit", ["row-1"]), ("no_important_effect", ["row-2"])],
    )

    with pytest.raises(GRADEInconsistencyJudgementError) as raised:
        _run([0.65, 1.0], policy=_policy(), judgement=invalid)

    assert raised.value.attempts == 2


def test_single_study_and_incomplete_coverage_do_not_call_llm() -> None:
    method = Method(
        config=CONFIG,
        caller=lambda **_kwargs: pytest.fail("deterministic boundary must not call LLM"),
    )
    single_study = method.run(grade_input=_grade_input([0.7]))
    assert single_study["severity"] == "not_serious"
    assert single_study["levels"] == 0
    assert single_study["downgraded"] == "no"
    assert single_study["level_evaluable"] is True
    assert single_study["assessment_status"] == "single_study_not_estimable"
    assert "cannot be estimated" in single_study["rationale"]

    grade_input = _grade_input([0.7, 1.1])
    incomplete = replace(
        grade_input,
        study_effects=grade_input.study_effects[:1],
        coverage=GRADEInconsistencyCoverage(
            expected_data_row_ids=["row-1", "row-2"],
            available_data_row_ids=["row-1"],
            missing_data_row_ids=["row-2"],
        ),
    )
    result = method.run(grade_input=incomplete)
    assert result["levels"] == "unclear"
    assert result["level_evaluable"] is False
    assert result["assessment_status"] == "insufficient_evidence"


def test_invalid_policy_is_retried_once_then_fails_with_policy_error() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        return {"assessment_status": "completed"}

    with pytest.raises(GRADEInconsistencyPolicyError) as raised:
        Method(config=CONFIG, caller=caller).run(
            grade_input=_grade_input([0.65, 1.0])
        )
    assert calls == 2
    assert raised.value.attempts == 2


def test_invalid_judgement_is_retried_once_then_fails_with_judgement_error() -> None:
    calls = []

    def caller(**kwargs):
        calls.append(kwargs["json_schema_name"])
        if len(calls) == 1:
            return _policy()
        return {"assessment_status": "completed"}

    with pytest.raises(GRADEInconsistencyJudgementError) as raised:
        Method(config=CONFIG, caller=caller).run(
            grade_input=_grade_input([0.65, 1.0])
        )
    assert calls == [
        "grade_inconsistency_result_blind_policy",
        "grade_inconsistency_bounded_judgement",
        "grade_inconsistency_bounded_judgement",
    ]
    assert raised.value.attempts == 2


def test_retryable_provider_error_on_judge_has_independent_retry_budget() -> None:
    calls = []

    def caller(**kwargs):
        calls.append(kwargs["json_schema_name"])
        if len(calls) == 1:
            return _policy()
        raise _provider_error(retryable=True)

    with pytest.raises(GRADEInconsistencyInvocationError) as raised:
        Method(config=CONFIG, caller=caller).run(
            grade_input=_grade_input([0.65, 1.0])
        )
    assert raised.value.stage == "judgement"
    assert raised.value.retry_exhausted is True
    assert raised.value.attempts == 2
    assert len(calls) == 3


def test_nonretryable_provider_error_is_not_retried() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        raise _provider_error(retryable=False)

    with pytest.raises(GRADEInconsistencyInvocationError) as raised:
        Method(config=CONFIG, caller=caller).run(
            grade_input=_grade_input([0.65, 1.0])
        )
    assert calls == 1
    assert raised.value.stage == "policy_generation"
    assert raised.value.retry_exhausted is False


def test_unknown_programming_error_is_not_captured_as_llm_failure() -> None:
    with pytest.raises(RuntimeError, match="programming defect"):
        Method(
            config=CONFIG,
            caller=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("programming defect")
            ),
        ).run(grade_input=_grade_input([0.65, 1.0]))


def _run(
    effects: list[float],
    *,
    policy: dict,
    judgement: dict,
) -> dict:
    def caller(**kwargs):
        if kwargs["json_schema_name"] == "grade_inconsistency_result_blind_policy":
            return policy
        return judgement

    return Method(config=CONFIG, caller=caller).run(
        grade_input=_grade_input(effects, i2=60.0)
    )


def _grade_input(
    effects: list[float],
    *,
    i2: float = 0.0,
) -> GRADEInconsistencyInput:
    study_effects = [
        GRADEInconsistencyStudyEffect(
            data_row_id=f"row-{index}",
            study_id=f"study-{index}",
            effect_value=value,
            ci_lower=value - 0.05,
            ci_upper=value + 0.05,
            weight_fraction=1.0 / len(effects),
            analysis_scale="natural",
            effect_measure="Risk Ratio",
            comparison=StudyResultComparison(
                experimental_arm="treatment",
                control_arm="control",
            ),
            outcome=StudyResultOutcome(label="mortality", timepoint="30 days"),
            subgroup=AnalysisSubgroup(),
        )
        for index, value in enumerate(effects, start=1)
    ]
    row_ids = [item.data_row_id for item in study_effects]
    return GRADEInconsistencyInput(
        setting=GRADEInconsistencySetting(
            setting_id="setting-1",
            setting_family_id="family-1",
            population="critically ill adults",
            comparison=AnalysisComparison(
                experimental="treatment",
                comparator="control",
            ),
            outcome=AnalysisOutcome(label="mortality", measure="all-cause mortality"),
            timepoint=AnalysisTimepoint(label="30 days"),
            subgroup=AnalysisSubgroup(),
            data_type=DataType.DICHOTOMOUS,
            effect_measure="Risk Ratio",
        ),
        estimate=GRADEInconsistencyEstimate(
            estimate_type="overall",
            estimate_id="estimate-1",
            estimation_status="computed",
            included_study_ids=[item.study_id for item in study_effects],
            included_data_row_ids=row_ids,
            study_count=len(study_effects),
            participant_count=100 * len(study_effects),
            effect_measure="Risk Ratio",
            analysis_model="random_effect",
            pooled_effect=0.9,
            ci_lower=0.8,
            ci_upper=1.0,
            heterogeneity=HeterogeneitySummary(
                i2=i2,
                p_value=0.02 if i2 >= 50 else 0.5,
            ),
            prediction_interval=None,
        ),
        study_effects=study_effects,
        subgroup_estimates=[],
        subgroup_difference_tests=[],
        study_characteristics=[
            StudyPIOCharacteristics(
                study_id=item.study_id,
                population=StudyPopulationCharacteristics(
                    description="critically ill adults"
                ),
            )
            for item in study_effects
        ],
        coverage=GRADEInconsistencyCoverage(
            expected_data_row_ids=row_ids,
            available_data_row_ids=row_ids,
            missing_data_row_ids=[],
        ),
    )


def _policy(
    *,
    with_boundaries: bool = True,
    with_modifier: bool = False,
) -> dict:
    modifiers = []
    if with_modifier:
        modifiers = [
            {
                "domain": "population",
                "factor": "age group",
                "categories": ["younger", "older"],
                "plausibility": "credible",
                "hypothesis_basis": "workflow_prespecified",
                "rationale": "Age could modify treatment response.",
            }
        ]
    return {
        "assessment_status": "completed",
        "effect_range_policy": {
            "no_effect_value": 1.0,
            "benefit_direction": "lower" if with_boundaries else "unknown",
            "important_benefit_boundary": 0.8 if with_boundaries else None,
            "important_harm_boundary": 1.2 if with_boundaries else None,
            "threshold_basis": "llm_contextual" if with_boundaries else "no_effect_only",
            "rationale": "Context-specific mortality thresholds.",
        },
        "plausible_effect_modifiers": modifiers,
        "limitations": [],
        "rationale": "Result-blind inconsistency policy.",
    }


def _judgement(
    *,
    severity: str,
    evidence: list[tuple[str, list[str]]],
    target_range: str | None = "no_important_effect",
    pooled_ci_ranges: list[str] | None = None,
    meaningful: bool = True,
    explained: bool = False,
    factor: str | None = None,
    test_id: str | None = None,
    imprecision_overlap: bool = False,
) -> dict:
    if pooled_ci_ranges is None:
        pooled_ci_ranges = ["important_benefit", "no_important_effect"]
    if explained:
        decision_basis = "inconsistency_explained"
    elif severity != "none":
        decision_basis = "meaningful_unexplained_inconsistency"
    elif imprecision_overlap:
        decision_basis = "likely_imprecision"
    else:
        decision_basis = "no_meaningful_inconsistency"
    return {
        "assessment_status": "completed",
        "severity": severity,
        "target_range": target_range,
        "pooled_ci_ranges": pooled_ci_ranges,
        "distribution_is_meaningful": meaningful,
        "inconsistency_explained": explained,
        "effect_modifier_factor": factor,
        "subgroup_test_id": test_id,
        "imprecision_overlap_risk": imprecision_overlap,
        "decision_basis": decision_basis,
        "supporting_evidence": [
            {"range": range_name, "data_row_ids": row_ids}
            for range_name, row_ids in evidence
        ],
    }


def _subgroup_estimate(
    estimate_id: str,
    level: str,
    study_ids: list[str],
) -> SubgroupEstimate:
    return SubgroupEstimate(
        subgroup_estimate_id=estimate_id,
        setting_id=f"setting-{level}",
        setting_family_id="family-1",
        method_id="method-1",
        subgroup=AnalysisSubgroup(factor="age group", level=level),
        included_study_ids=study_ids,
        study_count=len(study_ids),
        participant_count=100,
        data_type=DataType.DICHOTOMOUS,
        effect_measure="Risk Ratio",
        analysis_model="random_effect",
        statistical_method="Mantel-Haenszel",
        ci_level="95%",
        estimation_status=EstimationStatus.COMPUTED,
        heterogeneity=None,
    )


def _provider_error(*, retryable: bool) -> LLMAPIError:
    return LLMAPIError(
        "provider failed",
        status_code=503 if retryable else 400,
        request_id="request-1",
        retry_after_seconds=None,
        retryable=retryable,
        provider_message="provider failed",
    )
