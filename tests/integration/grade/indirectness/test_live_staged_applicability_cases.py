from __future__ import annotations

import json
import os

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
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.method import (
    Method,
)


RUN_LIVE_LLM_TESTS = os.getenv("RUN_LIVE_LLM_TESTS") == "1"


@pytest.mark.skipif(
    not RUN_LIVE_LLM_TESTS,
    reason="Set RUN_LIVE_LLM_TESTS=1 to run live GRADE indirectness cases.",
)
@pytest.mark.parametrize(
    ("case_id", "expected_threshold", "expected_domain"),
    [
        ("fully_direct", False, None),
        ("uniform_age_indirectness", False, "population"),
        ("mixed_delivery", True, "intervention"),
        ("risk_ratio_baseline", True, "population"),
    ],
)
def test_live_staged_applicability_cases(
    case_id: str,
    expected_threshold: bool,
    expected_domain: str | None,
) -> None:
    grade_input = CASE_BUILDERS[case_id]()
    result = Method().run(grade_input=grade_input)
    profile = result["decision_features"]["evidence_profile"]
    summary = {
        "case_id": case_id,
        "severity": result["severity"],
        "levels": result["levels"],
        "threshold_needed": profile["threshold_requirement"]["needed"],
        "threshold_status": profile["threshold_profile"]["status"],
        "threshold": {
            "benefit": profile["threshold_profile"]["important_benefit_threshold"],
            "harm": profile["threshold_profile"]["important_harm_threshold"],
            "baseline": profile["threshold_profile"]["baseline_risk_plan"],
        },
        "concern_groups": [
            {
                "group_id": group["group_id"],
                "domain": group["domain"],
                "less_direct_weight": group["less_direct_weight"],
                "more_direct_weight": group["more_direct_weight"],
            }
            for group in profile["concern_groups"]
        ],
        "concordance": profile["effect_range_profile"]["concern_concordance"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert profile["threshold_requirement"]["needed"] is expected_threshold
    if expected_domain is None:
        assert result["severity"] == "not_serious"
        assert not profile["concern_groups"]
    else:
        assert any(
            group["domain"] == expected_domain for group in profile["concern_groups"]
        )
        assert result["severity"] in {"serious", "very_serious"}
    if case_id == "risk_ratio_baseline" and profile["threshold_profile"][
        "status"
    ] == "generated":
        assert profile["threshold_profile"]["baseline_risk_plan"]["status"] == (
            "model_scenario"
        )


def _fully_direct_case() -> GRADEIndirectnessInput:
    return _build_case(
        case_id="fully-direct",
        target_population="Adults with uncomplicated primary hypertension",
        intervention="Lisinopril 10 mg orally once daily",
        comparator="Placebo",
        outcome="Change in systolic blood pressure",
        outcome_measure="Mean change from baseline in mmHg",
        timepoint="12 weeks",
        review_pico={
            "P": ["Adults with uncomplicated primary hypertension"],
            "I": ["Lisinopril 10 mg orally once daily"],
            "C": ["Placebo"],
            "O": ["Change in systolic blood pressure at 12 weeks"],
        },
        inclusion=[
            "Adults with uncomplicated primary hypertension receiving lisinopril 10 mg daily or placebo"
        ],
        exclusion=["Secondary hypertension"],
        effect_measure="Mean Difference",
        data_type=DataType.CONTINUOUS,
        studies=[
            {
                "population": "Adults with uncomplicated primary hypertension",
                "intervention": "Lisinopril 10 mg orally once daily",
                "effect": -8.0,
                "weight": 0.45,
            },
            {
                "population": "Adults with uncomplicated primary hypertension",
                "intervention": "Lisinopril 10 mg orally once daily",
                "effect": -7.5,
                "weight": 0.55,
            },
        ],
    )


def _uniform_age_indirectness_case() -> GRADEIndirectnessInput:
    return _build_case(
        case_id="uniform-age",
        target_population="Children aged 6 to 12 years with persistent asthma",
        intervention="Inhaled budesonide 200 micrograms twice daily",
        comparator="Placebo inhaler",
        outcome="Asthma symptom-free days",
        outcome_measure="Mean symptom-free days per month",
        timepoint="16 weeks",
        review_pico={
            "P": ["Children aged 6 to 12 years with persistent asthma"],
            "I": ["Inhaled budesonide"],
            "C": ["Placebo inhaler"],
            "O": ["Asthma symptom-free days"],
        },
        inclusion=["Randomized trials in children aged 6 to 12 years"],
        exclusion=["Adult-only populations"],
        effect_measure="Mean Difference",
        data_type=DataType.CONTINUOUS,
        studies=[
            {
                "population": "Adults aged 25 to 55 years with persistent asthma",
                "intervention": "Inhaled budesonide 200 micrograms twice daily",
                "effect": 3.0,
                "weight": 0.5,
            },
            {
                "population": "Adults aged 30 to 60 years with persistent asthma",
                "intervention": "Inhaled budesonide 200 micrograms twice daily",
                "effect": 2.5,
                "weight": 0.5,
            },
        ],
    )


def _mixed_delivery_case() -> GRADEIndirectnessInput:
    return _build_case(
        case_id="mixed-delivery",
        target_population="Adults with symptomatic knee osteoarthritis",
        intervention="Exercise therapy",
        comparator="Usual care",
        outcome="WOMAC pain score",
        outcome_measure="Mean change on a 0 to 100 scale; lower is better",
        timepoint="12 weeks",
        review_pico={
            "P": ["Adults with symptomatic knee osteoarthritis"],
            "I": ["Supervised clinic-based exercise therapy"],
            "C": ["Usual care"],
            "O": ["WOMAC pain score at 12 weeks"],
        },
        inclusion=["Supervised clinic-based exercise delivered by a physiotherapist"],
        exclusion=["Unsupervised home exercise as the sole intervention"],
        effect_measure="Mean Difference",
        data_type=DataType.CONTINUOUS,
        studies=[
            {
                "population": "Adults with symptomatic knee osteoarthritis",
                "intervention": "Unsupervised home exercise using a printed leaflet",
                "effect": -2.0,
                "weight": 0.4,
            },
            {
                "population": "Adults with symptomatic knee osteoarthritis",
                "intervention": "Supervised clinic exercise delivered by a physiotherapist",
                "effect": -10.0,
                "weight": 0.6,
            },
        ],
    )


def _risk_ratio_baseline_case() -> GRADEIndirectnessInput:
    return _build_case(
        case_id="risk-ratio-baseline",
        target_population="Adults aged 75 years or older after hip-fracture surgery",
        intervention="Prophylactic anticoagulation",
        comparator="Placebo",
        outcome="Symptomatic venous thromboembolism",
        outcome_measure="Participants with symptomatic VTE",
        timepoint="90 days",
        review_pico={
            "P": ["Adults aged 75 years or older after hip-fracture surgery"],
            "I": ["Prophylactic anticoagulation"],
            "C": ["Placebo"],
            "O": ["Symptomatic venous thromboembolism by 90 days"],
        },
        inclusion=["Adults aged 75 years or older after hip-fracture surgery"],
        exclusion=["Younger elective orthopedic populations"],
        effect_measure="Risk Ratio",
        data_type=DataType.DICHOTOMOUS,
        studies=[
            {
                "population": "Adults aged 40 to 60 years after elective knee arthroplasty",
                "intervention": "Prophylactic anticoagulation",
                "effect": 0.60,
                "weight": 0.35,
                "baseline": 0.05,
            },
            {
                "population": "Adults aged 75 years or older after hip-fracture surgery",
                "intervention": "Prophylactic anticoagulation",
                "effect": 0.85,
                "weight": 0.65,
                "baseline": 0.20,
            },
        ],
    )


def _build_case(
    *,
    case_id: str,
    target_population: str,
    intervention: str,
    comparator: str,
    outcome: str,
    outcome_measure: str,
    timepoint: str,
    review_pico: dict[str, list[str]],
    inclusion: list[str],
    exclusion: list[str],
    effect_measure: str,
    data_type: DataType,
    studies: list[dict[str, object]],
) -> GRADEIndirectnessInput:
    row_ids = [f"{case_id}-row-{index}" for index in range(1, len(studies) + 1)]
    evidence = []
    for index, (row_id, study) in enumerate(zip(row_ids, studies), start=1):
        evidence.append(
            GRADEIndirectnessStudyEvidence(
                data_row_id=row_id,
                study_id=f"{case_id}-study-{index}",
                comparison=StudyResultComparison(
                    experimental_arm=intervention,
                    control_arm=comparator,
                ),
                outcome=StudyResultOutcome(label=outcome, timepoint=timepoint),
                subgroup=AnalysisSubgroup(),
                population=StudyPopulationCharacteristics(
                    description=str(study["population"])
                ),
                intervention=StudyInterventionCharacteristics(
                    label=intervention,
                    description=str(study["intervention"]),
                ),
                comparator=StudyComparatorCharacteristics(
                    label=comparator,
                    description=f"Matched {comparator}",
                ),
                study_outcome=StudyOutcomeCharacteristics(
                    outcome_label=outcome,
                    measurement=outcome_measure,
                    timepoints=[timepoint],
                ),
                mapping_status=GRADEIndirectnessMappingStatus(
                    intervention="matched",
                    comparator="matched",
                    outcome="matched",
                    timepoint="matched",
                ),
                candidate_interventions=[],
                candidate_comparators=[],
                candidate_outcomes=[],
                effect_value=float(study["effect"]),
                ci_lower=None,
                ci_upper=None,
                weight_fraction=float(study["weight"]),
                control_baseline_risk=(
                    float(study["baseline"]) if "baseline" in study else None
                ),
            )
        )
    return GRADEIndirectnessInput(
        setting=GRADEIndirectnessSetting(
            setting_id=f"{case_id}-setting",
            setting_family_id=f"{case_id}-family",
            population=target_population,
            comparison=AnalysisComparison(
                experimental=intervention,
                comparator=comparator,
            ),
            outcome=AnalysisOutcome(label=outcome, measure=outcome_measure),
            timepoint=AnalysisTimepoint(label=timepoint),
            subgroup=AnalysisSubgroup(),
            data_type=data_type,
            effect_measure=effect_measure,
        ),
        estimate=GRADEIndirectnessEstimate(
            estimate_type="overall",
            estimate_id=f"{case_id}-estimate",
            estimation_status="computed",
            included_study_ids=[item.study_id for item in evidence],
            included_data_row_ids=row_ids,
            study_count=len(evidence),
            participant_count=400,
            effect_measure=effect_measure,
            analysis_model="random_effect",
            pooled_effect=None,
            ci_lower=None,
            ci_upper=None,
        ),
        review_population=review_pico["P"],
        review_intervention=review_pico["I"],
        review_comparator=review_pico["C"],
        review_outcome=review_pico["O"],
        screening_criteria=ScreeningCriteria(
            inclusion_criteria=inclusion,
            exclusion_criteria=exclusion,
        ),
        study_evidence=evidence,
        direct_comparison_status="pairwise_direct",
        subgroup_estimates=[],
        subgroup_difference_tests=[],
        coverage=GRADEIndirectnessCoverage(
            expected_data_row_ids=row_ids,
            available_data_row_ids=row_ids,
            missing_data_row_ids=[],
            missing_study_pio_data_row_ids=[],
            ambiguous_mapping_data_row_ids=[],
            missing_weight_data_row_ids=[],
        ),
    )


CASE_BUILDERS = {
    "fully_direct": _fully_direct_case,
    "uniform_age_indirectness": _uniform_age_indirectness_case,
    "mixed_delivery": _mixed_delivery_case,
    "risk_ratio_baseline": _risk_ratio_baseline_case,
}
