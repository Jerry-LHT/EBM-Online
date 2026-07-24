from __future__ import annotations

from dataclasses import replace
import json

import pytest

from ebm_backend.online_pipeline.domain.common import DataType
from ebm_backend.online_pipeline.domain.grade import (
    GRADEIndirectnessCoverage,
    GRADEIndirectnessEstimate,
    GRADEIndirectnessInput,
    GRADEIndirectnessMappingStatus,
    GRADEIndirectnessSetting,
    GRADEIndirectnessStudyEvidence,
)
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSubgroup,
    AnalysisTimepoint,
    StudyResultComparison,
    StudyResultOutcome,
)
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria
from ebm_backend.online_pipeline.domain.study_characteristics import (
    StudyComparatorCharacteristics,
    StudyInterventionCharacteristics,
    StudyOutcomeCharacteristics,
    StudyPopulationCharacteristics,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMAPIError
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.errors import (
    GRADEIndirectnessClassificationError,
    GRADEIndirectnessInvocationError,
    GRADEIndirectnessJudgementError,
    GRADEIndirectnessThresholdError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.method import (
    Method,
)


CONFIG = {
    "api_key": "test-key",
    "base_url": "https://example.invalid/v1",
    "model": "test-model",
    "api_mode": "responses",
}


def test_fully_direct_evidence_skips_threshold_generation() -> None:
    grade_input = _grade_input()
    calls = []

    def caller(**kwargs):
        calls.append(kwargs)
        if kwargs["json_schema_name"].endswith("classification"):
            return _classification(grade_input)
        return _judgement([])

    result = Method(config=CONFIG, caller=caller).run(grade_input=grade_input)

    assert [call["json_schema_name"] for call in calls] == [
        "grade_indirectness_result_blind_classification",
        "grade_indirectness_bounded_judgement",
    ]
    classifier_payload = _payload(calls[0])
    assert classifier_payload["result_blinding"]["study_effects_provided"] is False
    assert "effect_value" not in calls[0]["prompt"]
    assert calls[0]["config"]["sdk_max_retries"] == 0
    assert calls[0]["config"]["json_marker_retry_enabled"] is False
    judge_schema = calls[1]["json_schema"]
    assert judge_schema["properties"]["severity"]["enum"] == ["none"]
    assert judge_schema["properties"]["coverage_affects_judgement"]["enum"] == [
        False
    ]
    assert judge_schema["properties"]["group_judgements"]["maxItems"] == 0
    assert judge_schema["properties"]["baseline_risk_assessment"]["enum"] == [
        "unavailable"
    ]
    assert result["severity"] == "not_serious"
    assert result["assessment_status"] == "assessed"
    assert result["decision_features"]["evidence_profile"]["threshold_profile"][
        "status"
    ] == "not_needed"
    assert result["decision_features"]["execution_trace"]["stage_attempts"] == {
        "study_classification": 1,
        "threshold_generation": 0,
        "evidence_body_judgement": 1,
    }


def test_delivery_difference_uses_one_row_threshold_and_effect_concordance() -> None:
    grade_input = _grade_input(effects=[-1.5, -0.2])
    group_id = "intervention-delivery-effect-modification"
    result, calls = _run(
        grade_input=grade_input,
        classification=_classification(
            grade_input,
            concern_domain="intervention",
            concern_facet="delivery",
            concern_mechanism="effect_modification",
            affected_rows={"row-1"},
        ),
        threshold=_threshold_generated(effect_scale="mean_difference"),
        judgement=_judgement([group_id], impacts={group_id: "meaningful"}, severity="serious"),
    )

    assert [call["json_schema_name"] for call in calls] == [
        "grade_indirectness_result_blind_classification",
        "grade_indirectness_clinical_threshold",
        "grade_indirectness_bounded_judgement",
    ]
    threshold_payload = _payload(calls[1])
    assert threshold_payload["result_blinding"]["study_effects_provided"] is False
    assert "row_evidence" not in threshold_payload
    assert calls[1]["json_schema"]["properties"]["effect_scale"] == {
        "type": "string",
        "enum": ["mean_difference"],
    }
    judge_schema = calls[2]["json_schema"]
    group_schema = judge_schema["properties"]["group_judgements"]
    assert group_schema["minItems"] == group_schema["maxItems"] == 1
    assert group_schema["items"]["properties"]["group_id"]["enum"] == [
        group_id
    ]
    assert "unclear" not in judge_schema["properties"]["severity"]["enum"]
    profile = result["decision_features"]["evidence_profile"]
    assert profile["effect_range_profile"]["concern_concordance"][0][
        "range_concordance"
    ] == "different_clinical_ranges"
    concordance = profile["effect_range_profile"]["concern_concordance"][0]
    assert concordance["less_direct_weight_by_range"] == {
        "important_benefit": 0.4
    }
    assert concordance["more_direct_weight_by_range"] == {
        "no_important_effect": 0.6
    }
    assert result["levels"] == 1


def test_unspecified_target_timepoint_does_not_create_engineering_concern() -> None:
    grade_input = _grade_input(timepoint="")
    result, calls = _run(
        grade_input=grade_input,
        classification=_classification(grade_input),
        judgement=_judgement([]),
    )

    assert len(calls) == 2
    assert result["severity"] == "not_serious"


def test_missing_study_outcome_is_coverage_not_an_indirectness_concern() -> None:
    grade_input = _grade_input()
    missing_row = replace(
        grade_input.study_evidence[0],
        study_outcome=None,
        mapping_status=replace(
            grade_input.study_evidence[0].mapping_status,
            outcome="not_found",
            timepoint="not_found",
        ),
    )
    grade_input = replace(
        grade_input,
        study_evidence=[missing_row, grade_input.study_evidence[1]],
    )
    result, calls = _run(
        grade_input=grade_input,
        classification=_classification(grade_input),
        judgement=_judgement([]),
    )

    first_outcome = result["decision_features"]["classification"][
        "study_assessments"
    ][0]["domains"]["outcome"]
    assert first_outcome == {
        "information_status": "study_information_insufficient",
        "overall_directness": "not_assessable",
        "factors": [],
    }
    judge_schema = calls[-1]["json_schema"]
    assert "enum" not in judge_schema["properties"][
        "coverage_affects_judgement"
    ]
    assert "unclear" in judge_schema["properties"]["severity"]["enum"]
    assert result["severity"] == "not_serious"


def test_surrogate_outcome_concern_does_not_request_numeric_threshold() -> None:
    grade_input = _grade_input()
    group_id = "outcome-surrogate-surrogate-or-proxy"
    result, calls = _run(
        grade_input=grade_input,
        classification=_classification(
            grade_input,
            concern_domain="outcome",
            concern_facet="surrogate",
            concern_mechanism="surrogate_or_proxy",
            affected_rows={"row-1", "row-2"},
        ),
        judgement=_judgement([group_id], impacts={group_id: "meaningful"}, severity="serious"),
    )

    assert len(calls) == 2
    assert result["decision_features"]["evidence_profile"]["threshold_requirement"][
        "reason"
    ] == "non_numeric_applicability_concern"


def test_risk_ratio_population_concern_uses_model_baseline_sensitivity() -> None:
    grade_input = _grade_input(
        effect_measure="Risk Ratio",
        data_type=DataType.DICHOTOMOUS,
        effects=[0.5, 0.9],
    )
    group_id = "population-disease-severity-baseline-risk"
    result, _ = _run(
        grade_input=grade_input,
        classification=_classification(
            grade_input,
            concern_domain="population",
            concern_facet="disease_severity",
            concern_mechanism="baseline_risk",
            affected_rows={"row-1"},
        ),
        threshold=_threshold_generated(
            effect_scale="risk_difference",
            benefit=-0.05,
            harm=0.05,
            baseline=(0.1, 0.3),
        ),
        judgement=_judgement(
            [group_id],
            impacts={group_id: "meaningful"},
            severity="serious",
            baseline="concern",
        ),
    )

    profile = result["decision_features"]["evidence_profile"]
    assert profile["baseline_risk"]["target_baseline_risk_source"] == "model_scenario"
    assert profile["baseline_risk"]["model_scenario_is_observed_study_risk"] is False
    assert profile["effect_range_profile"]["row_ranges"][0][
        "target_scenario_effect"
    ] == pytest.approx(-0.1)
    assert result["decision_features"]["execution_trace"][
        "baseline_risk_evaluations"
    ][0]["data_row_id"] == "row-1"


@pytest.mark.parametrize(
    ("weights", "expected_status", "expected_total"),
    [
        ([None, 0.6], "incomplete", 0.6),
        ([0.3, 0.3], "invalid", 0.6),
    ],
)
def test_incomplete_or_invalid_weights_are_not_used(
    weights: list[float | None], expected_status: str, expected_total: float
) -> None:
    grade_input = _grade_input(effects=[-1.5, -0.2])
    grade_input = replace(
        grade_input,
        study_evidence=[
            replace(row, weight_fraction=weight)
            for row, weight in zip(grade_input.study_evidence, weights)
        ],
    )
    group_id = "intervention-delivery-effect-modification"
    result, _ = _run(
        grade_input=grade_input,
        classification=_classification(
            grade_input,
            concern_domain="intervention",
            concern_facet="delivery",
            concern_mechanism="effect_modification",
            affected_rows={"row-1"},
        ),
        threshold=_threshold_generated(effect_scale="mean_difference"),
        judgement=_judgement(
            [group_id], impacts={group_id: "meaningful"}, severity="serious"
        ),
    )

    profile = result["decision_features"]["evidence_profile"]
    assert profile["weight_coverage"]["status"] == expected_status
    assert profile["weight_coverage"]["total_weight"] == expected_total
    assert profile["effect_range_profile"]["weights_used"] is False
    assert all(row["weight_fraction"] is None for row in profile["row_evidence"])
    group = profile["concern_groups"][0]
    assert group["less_direct_weight"] is None
    assert group["more_direct_weight"] is None
    concordance = profile["effect_range_profile"]["concern_concordance"][0]
    assert concordance["less_direct_weight_by_range"] is None
    assert concordance["more_direct_weight_by_range"] is None


def test_impossible_risk_ratio_scenario_is_row_level_unclassifiable() -> None:
    grade_input = _grade_input(
        effect_measure="Risk Ratio",
        data_type=DataType.DICHOTOMOUS,
        effects=[2.0, 1.0],
    )
    group_id = "population-disease-severity-baseline-risk"
    result, _ = _run(
        grade_input=grade_input,
        classification=_classification(
            grade_input,
            concern_domain="population",
            concern_facet="disease_severity",
            concern_mechanism="baseline_risk",
            affected_rows={"row-1"},
        ),
        threshold=_threshold_generated(
            effect_scale="risk_difference",
            benefit=-0.05,
            harm=0.05,
            baseline=(0.8, 0.9),
        ),
        judgement=_judgement(
            [group_id],
            impacts={group_id: "meaningful"},
            severity="serious",
            baseline="concern",
        ),
    )

    row = result["decision_features"]["evidence_profile"][
        "effect_range_profile"
    ]["row_ranges"][0]
    assert row["numeric_status"] == "unclassifiable"
    assert row["target_scenario_range"] == "unclassified"
    assert row["unclassifiable_reason"] == (
        "target_baseline_scenario_contains_impossible_risk"
    )
    assert result["severity"] == "serious"


def test_odds_ratio_sensitivity_checks_the_full_baseline_range() -> None:
    grade_input = _grade_input(
        effect_measure="Odds Ratio",
        data_type=DataType.DICHOTOMOUS,
        effects=[4.0, 1.0],
    )
    group_id = "population-disease-severity-baseline-risk"
    result, _ = _run(
        grade_input=grade_input,
        classification=_classification(
            grade_input,
            concern_domain="population",
            concern_facet="disease_severity",
            concern_mechanism="baseline_risk",
            affected_rows={"row-1"},
        ),
        threshold=_threshold_generated(
            effect_scale="risk_difference",
            benefit=-0.05,
            harm=0.32,
            baseline=(0.1, 0.9),
        ),
        judgement=_judgement(
            [group_id],
            impacts={group_id: "meaningful"},
            severity="serious",
            baseline="sensitivity_only",
        ),
    )

    row = result["decision_features"]["evidence_profile"][
        "effect_range_profile"
    ]["row_ranges"][0]
    evaluations = {item["point"]: item for item in row["target_baseline_evaluations"]}
    assert evaluations["low"]["clinical_range"] == "no_important_effect"
    assert evaluations["midpoint"]["clinical_range"] == "no_important_effect"
    assert evaluations["high"]["clinical_range"] == "no_important_effect"
    assert evaluations["odds_ratio_extremum"]["clinical_range"] == "important_harm"
    assert row["target_baseline_range_sensitivity"] == "sensitive"


def test_non_finite_threshold_is_retried_then_rejected() -> None:
    grade_input = _grade_input()
    classification = _classification(
        grade_input,
        concern_domain="intervention",
        concern_facet="delivery",
        concern_mechanism="effect_modification",
        affected_rows={"row-1"},
    )
    invalid = _threshold_generated(effect_scale="mean_difference")
    invalid["important_harm_threshold"] = float("nan")
    calls = []

    def caller(**kwargs):
        calls.append(kwargs)
        if kwargs["json_schema_name"].endswith("classification"):
            return classification
        return invalid

    with pytest.raises(GRADEIndirectnessThresholdError):
        Method(config=CONFIG, caller=caller).run(grade_input=grade_input)

    assert [call["json_schema_name"] for call in calls].count(
        "grade_indirectness_clinical_threshold"
    ) == 2


def test_standardized_mean_difference_can_fall_back_to_no_effect_only() -> None:
    grade_input = _grade_input(effect_measure="SMD", effects=[-0.5, -0.1])
    group_id = "intervention-delivery-effect-modification"
    result, _ = _run(
        grade_input=grade_input,
        classification=_classification(
            grade_input,
            concern_domain="intervention",
            concern_facet="delivery",
            concern_mechanism="effect_modification",
            affected_rows={"row-1"},
        ),
        threshold=_threshold_no_effect("standardized_mean_difference"),
        judgement=_judgement([group_id]),
    )

    profile = result["decision_features"]["evidence_profile"]
    assert profile["threshold_profile"]["status"] == "no_effect_only"
    assert profile["effect_range_profile"]["row_ranges"][0][
        "target_scenario_range"
    ] == "benefit_side"


def test_invalid_threshold_is_retried_once_then_has_stage_error() -> None:
    grade_input = _grade_input()
    classification = _classification(
        grade_input,
        concern_domain="intervention",
        concern_facet="delivery",
        concern_mechanism="effect_modification",
        affected_rows={"row-1"},
    )
    invalid = _threshold_generated(effect_scale="mean_difference")
    invalid["important_benefit_threshold"] = 1.0
    calls = []

    def caller(**kwargs):
        calls.append(kwargs)
        if kwargs["json_schema_name"].endswith("classification"):
            return classification
        return invalid

    with pytest.raises(GRADEIndirectnessThresholdError) as raised:
        Method(config=CONFIG, caller=caller).run(grade_input=grade_input)

    assert [call["json_schema_name"] for call in calls].count(
        "grade_indirectness_clinical_threshold"
    ) == 2
    assert raised.value.attempts == 2


def test_invalid_classification_and_judgement_have_separate_stage_errors() -> None:
    grade_input = _grade_input()
    invalid_classification = _classification(grade_input)
    invalid_classification["study_assessments"].reverse()
    with pytest.raises(GRADEIndirectnessClassificationError):
        Method(config=CONFIG, caller=lambda **_kwargs: invalid_classification).run(
            grade_input=grade_input
        )

    calls = []

    def judgement_caller(**kwargs):
        calls.append(kwargs)
        if kwargs["json_schema_name"].endswith("classification"):
            return _classification(grade_input)
        return {
            **_judgement([]),
            "group_judgements": [{"group_id": "unknown", "impact": "meaningful"}],
        }

    with pytest.raises(GRADEIndirectnessJudgementError):
        Method(config=CONFIG, caller=judgement_caller).run(grade_input=grade_input)
    assert len(calls) == 3


def test_identical_target_and_study_values_cannot_support_a_concern_factor() -> None:
    grade_input = _grade_input()
    invalid = _classification(
        grade_input,
        concern_domain="population",
        concern_facet="life_stage_or_age",
        concern_mechanism="effect_modification",
        affected_rows={"row-1"},
    )
    factor = invalid["study_assessments"][0]["domains"]["population"]["factors"][0]
    factor["study_value"] = factor["target_value"]

    with pytest.raises(GRADEIndirectnessClassificationError):
        Method(config=CONFIG, caller=lambda **_kwargs: invalid).run(
            grade_input=grade_input
        )


def test_one_major_group_can_support_very_serious_without_group_count_formula() -> None:
    grade_input = _grade_input()
    group_id = "outcome-surrogate-surrogate-or-proxy"
    result, _ = _run(
        grade_input=grade_input,
        classification=_classification(
            grade_input,
            concern_domain="outcome",
            concern_facet="surrogate",
            concern_mechanism="surrogate_or_proxy",
            affected_rows={"row-1", "row-2"},
            concern_directness="not_sufficiently_direct",
        ),
        judgement=_judgement(
            [group_id], impacts={group_id: "major"}, severity="very_serious"
        ),
    )

    assert result["levels"] == 2
    assert result["decision_features"]["judge"]["decision_basis"] == (
        "major_applicability_limitation"
    )


def test_provider_retry_budget_is_first_call_plus_one_retry() -> None:
    grade_input = _grade_input()
    attempts = {"classification": 0, "judge": 0}

    def caller(**kwargs):
        stage = (
            "classification"
            if kwargs["json_schema_name"].endswith("classification")
            else "judge"
        )
        attempts[stage] += 1
        if attempts[stage] == 1:
            raise _provider_error(retryable=True)
        return _classification(grade_input) if stage == "classification" else _judgement([])

    result = Method(config=CONFIG, caller=caller).run(grade_input=grade_input)

    assert attempts == {"classification": 2, "judge": 2}
    assert result["severity"] == "not_serious"


def test_non_retryable_provider_and_unknown_programming_errors_are_not_retried() -> None:
    calls = []

    def provider_failure(**kwargs):
        calls.append(kwargs)
        raise _provider_error(retryable=False)

    with pytest.raises(GRADEIndirectnessInvocationError) as raised:
        Method(config=CONFIG, caller=provider_failure).run(grade_input=_grade_input())
    assert len(calls) == 1
    assert raised.value.stage == "study_classification"

    def programming_failure(**_kwargs):
        raise RuntimeError("programming failure")

    with pytest.raises(RuntimeError, match="programming failure"):
        Method(config=CONFIG, caller=programming_failure).run(
            grade_input=_grade_input()
        )


def test_no_rows_or_no_usable_study_pio_is_unclear_without_llm() -> None:
    method = Method(
        config=CONFIG,
        caller=lambda **_kwargs: pytest.fail("unavailable evidence must not call LLM"),
    )
    assert method.run(grade_input=_grade_input(row_count=0))["severity"] == "unclear"
    assert method.run(grade_input=_grade_input(pio_available=False))["severity"] == "unclear"


def _run(
    *,
    grade_input: GRADEIndirectnessInput,
    classification: dict,
    judgement: dict,
    threshold: dict | None = None,
) -> tuple[dict, list[dict]]:
    calls = []

    def caller(**kwargs):
        calls.append(kwargs)
        name = kwargs["json_schema_name"]
        if name.endswith("classification"):
            return classification
        if name.endswith("clinical_threshold"):
            assert threshold is not None
            return threshold
        return judgement

    return Method(config=CONFIG, caller=caller).run(grade_input=grade_input), calls


def _grade_input(
    *,
    row_count: int = 2,
    pio_available: bool = True,
    effect_measure: str = "Mean Difference",
    data_type: DataType = DataType.CONTINUOUS,
    effects: list[float] | None = None,
    timepoint: str = "12 weeks",
) -> GRADEIndirectnessInput:
    effect_values = effects or [-1.2, -0.2]
    rows = [
        _study_evidence(
            index=index,
            pio_available=pio_available,
            effect_value=effect_values[index - 1],
        )
        for index in range(1, row_count + 1)
    ]
    ids = [row.data_row_id for row in rows]
    return GRADEIndirectnessInput(
        setting=GRADEIndirectnessSetting(
            setting_id="setting-1",
            setting_family_id="family-1",
            population="Children aged 6 to 12 years with migraine",
            comparison=AnalysisComparison(
                experimental="CGRP monoclonal antibody",
                comparator="Placebo",
            ),
            outcome=AnalysisOutcome(
                label="Monthly migraine days",
                measure="Change from baseline",
            ),
            timepoint=AnalysisTimepoint(label=timepoint),
            subgroup=AnalysisSubgroup(),
            data_type=data_type,
            effect_measure=effect_measure,
        ),
        estimate=GRADEIndirectnessEstimate(
            estimate_type="overall",
            estimate_id="estimate-1",
            estimation_status="computed",
            included_study_ids=[row.study_id for row in rows],
            included_data_row_ids=ids,
            study_count=row_count,
            participant_count=row_count * 100,
            effect_measure=effect_measure,
            analysis_model="random_effect",
            pooled_effect=None if not rows else sum(row.effect_value or 0 for row in rows) / len(rows),
            ci_lower=None,
            ci_upper=None,
        ),
        review_population=["Children with migraine"],
        review_intervention=["CGRP monoclonal antibody"],
        review_comparator=["Placebo"],
        review_outcome=["Monthly migraine days"],
        screening_criteria=ScreeningCriteria(
            inclusion_criteria=["Randomized trials in children aged 6 to 12 years"],
            exclusion_criteria=["Adults-only populations"],
        ),
        study_evidence=rows,
        direct_comparison_status="pairwise_direct",
        subgroup_estimates=[],
        subgroup_difference_tests=[],
        coverage=GRADEIndirectnessCoverage(
            expected_data_row_ids=ids,
            available_data_row_ids=ids,
            missing_data_row_ids=[],
            missing_study_pio_data_row_ids=(ids if rows and not pio_available else []),
            ambiguous_mapping_data_row_ids=[],
            missing_weight_data_row_ids=[],
        ),
    )


def _study_evidence(
    *, index: int, pio_available: bool, effect_value: float
) -> GRADEIndirectnessStudyEvidence:
    status = "matched" if pio_available else "study_pio_missing"
    return GRADEIndirectnessStudyEvidence(
        data_row_id=f"row-{index}",
        study_id=f"study-{index}",
        comparison=StudyResultComparison(
            experimental_arm="CGRP monoclonal antibody",
            control_arm="Placebo",
        ),
        outcome=StudyResultOutcome(
            label="Monthly migraine days",
            timepoint="12 weeks",
        ),
        subgroup=AnalysisSubgroup(),
        population=(
            StudyPopulationCharacteristics(
                description="Children aged 6 to 12 years with episodic migraine"
            )
            if pio_available
            else None
        ),
        intervention=(
            StudyInterventionCharacteristics(
                label="CGRP monoclonal antibody",
                description="Monthly subcutaneous administration",
            )
            if pio_available
            else None
        ),
        comparator=(
            StudyComparatorCharacteristics(label="Placebo", description="Matched placebo")
            if pio_available
            else None
        ),
        study_outcome=(
            StudyOutcomeCharacteristics(
                outcome_label="Monthly migraine days",
                measurement="Change from baseline",
                timepoints=["12 weeks"],
            )
            if pio_available
            else None
        ),
        mapping_status=GRADEIndirectnessMappingStatus(
            intervention=status,
            comparator=status,
            outcome=status,
            timepoint=status,
        ),
        candidate_interventions=[],
        candidate_comparators=[],
        candidate_outcomes=[],
        effect_value=effect_value,
        ci_lower=effect_value - 0.3,
        ci_upper=effect_value + 0.3,
        weight_fraction=0.4 if index == 1 else 0.6,
        control_baseline_risk=0.2 if index == 1 else 0.3,
    )


def _classification(
    grade_input: GRADEIndirectnessInput,
    *,
    concern_domain: str | None = None,
    concern_facet: str | None = None,
    concern_mechanism: str | None = None,
    affected_rows: set[str] | None = None,
    concern_directness: str = "probably_not_sufficiently_direct",
) -> dict:
    affected = affected_rows or set()
    assessments = []
    for row in grade_input.study_evidence:
        availability = {
            "population": row.population is not None,
            "intervention": row.intervention is not None and row.mapping_status.intervention == "matched",
            "comparator": row.comparator is not None and row.mapping_status.comparator == "matched",
            "outcome": row.study_outcome is not None and row.mapping_status.outcome == "matched",
        }
        domains = {}
        for domain, available in availability.items():
            if not available:
                domains[domain] = {
                    "information_status": "study_information_insufficient",
                    "overall_directness": "not_assessable",
                    "factors": [],
                }
            elif domain == concern_domain and row.data_row_id in affected:
                domains[domain] = {
                    "information_status": "sufficient",
                    "overall_directness": concern_directness,
                    "factors": [
                        _factor(
                            domain=domain,
                            facet=concern_facet or "identity",
                            mechanism=concern_mechanism or "effect_modification",
                            directness=concern_directness,
                        )
                    ],
                }
            else:
                domains[domain] = {
                    "information_status": "sufficient",
                    "overall_directness": "sufficiently_direct",
                    "factors": [],
                }
        assessments.append(
            {"data_row_id": row.data_row_id, "study_id": row.study_id, "domains": domains}
        )
    return {"assessment_status": "completed", "study_assessments": assessments}


def _factor(*, domain: str, facet: str, mechanism: str, directness: str) -> dict:
    fields = {
        "population": ["target.population", "study.population"],
        "intervention": ["target.intervention", "study.intervention"],
        "comparator": ["target.comparator", "study.comparator"],
        "outcome": ["target.outcome", "study.outcome"],
    }[domain]
    return {
        "facet": facet,
        "target_value": "Target specification",
        "study_value": "Different study specification",
        "directness": directness,
        "effect_difference_likelihood": "likely",
        "mechanism": mechanism,
        "difference_summary": "The target-versus-study difference may materially change the effect.",
        "supporting_fields": fields,
    }


def _threshold_generated(
    *,
    effect_scale: str,
    benefit: float = -1.0,
    harm: float = 1.0,
    baseline: tuple[float, float] | None = None,
) -> dict:
    return {
        "status": "generated",
        "effect_scale": effect_scale,
        "unit": "outcome units",
        "benefit_direction": "lower_is_better",
        "important_benefit_threshold": benefit,
        "important_harm_threshold": harm,
        "basis": "model_expert_assumption",
        "rationale": "The boundaries reflect an important target-outcome change.",
        "applicability": "Applies to this target outcome row.",
        "confidence": "moderate",
        "baseline_risk_plan": {
            "status": "model_scenario" if baseline else "not_required",
            "low": baseline[0] if baseline else None,
            "high": baseline[1] if baseline else None,
            "basis": "target-population expert scenario" if baseline else "not required",
            "rationale": "Scenario for absolute effects." if baseline else "Absolute scale is direct.",
        },
    }


def _threshold_no_effect(effect_scale: str) -> dict:
    return {
        "status": "no_effect_only",
        "effect_scale": effect_scale,
        "unit": None,
        "benefit_direction": "lower_is_better",
        "important_benefit_threshold": None,
        "important_harm_threshold": None,
        "basis": "no_effect_only",
        "rationale": "No defensible important-difference boundary is available.",
        "applicability": "Direction only.",
        "confidence": "low",
        "baseline_risk_plan": {
            "status": "not_required",
            "low": None,
            "high": None,
            "basis": "not required",
            "rationale": "No ratio conversion is needed.",
        },
    }


def _judgement(
    group_ids: list[str],
    *,
    impacts: dict[str, str] | None = None,
    severity: str | None = None,
    baseline: str = "unavailable",
) -> dict:
    impact_map = impacts or {group_id: "meaningful" for group_id in group_ids}
    return {
        "assessment_status": "completed",
        "severity": severity or ("serious" if group_ids else "none"),
        "coverage_affects_judgement": False,
        "group_judgements": [
            {"group_id": group_id, "impact": impact_map.get(group_id, "no_concern")}
            for group_id in group_ids
        ],
        "baseline_risk_assessment": baseline,
    }


def _payload(call: dict) -> dict:
    return json.loads(call["prompt"].split("Input JSON:\n", 1)[1])


def _provider_error(*, retryable: bool) -> LLMAPIError:
    return LLMAPIError(
        "provider error",
        status_code=503 if retryable else 400,
        request_id="request-1",
        retry_after_seconds=None,
        retryable=retryable,
        provider_message="provider error",
    )
