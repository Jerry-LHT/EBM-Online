from __future__ import annotations

import json
import os

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_grade import (
    _grade_indirectness_input,
)
from ebm_backend.online_pipeline.domain.common import DataType, EstimationStatus
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSetting,
    AnalysisSubgroup,
    AnalysisTimepoint,
    ContinuousResultData,
    MetaAnalysisDataRow,
    MetaAnalysisResultPackage,
    OverallEstimate,
    StudyResultComparison,
    StudyResultOutcome,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria
from ebm_backend.online_pipeline.domain.study_characteristics import (
    StudyComparatorCharacteristics,
    StudyInterventionCharacteristics,
    StudyOutcomeCharacteristics,
    StudyPIOCharacteristics,
    StudyPopulationCharacteristics,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.method import (
    Method,
)


RUN_LIVE_LLM_TESTS = os.getenv("RUN_LIVE_LLM_TESTS") == "1"


@pytest.mark.skipif(
    not RUN_LIVE_LLM_TESTS,
    reason="Set RUN_LIVE_LLM_TESTS=1 to run live GRADE indirectness assessment.",
)
def test_live_mixed_directness_evidence_for_child_target() -> None:
    setting = AnalysisSetting(
        setting_id="setting-child-migraine",
        setting_family_id="family-migraine",
        population_scope="Children aged 6 to 12 years with episodic migraine",
        comparison=AnalysisComparison(
            experimental="CGRP monoclonal antibody",
            comparator="Placebo",
        ),
        outcome=AnalysisOutcome(
            label="Monthly migraine days",
            measure="Change from baseline",
        ),
        timepoint=AnalysisTimepoint(label="12 weeks"),
        subgroup=AnalysisSubgroup(),
        data_type=DataType.CONTINUOUS,
    )
    estimate = OverallEstimate(
        overall_estimate_id="estimate-migraine",
        setting_id=setting.setting_id,
        setting_family_id=setting.setting_family_id,
        method_id="inverse-variance-random",
        included_study_ids=["adult-rct-1", "adult-rct-2"],
        included_data_row_ids=["row-adult-1", "row-adult-2"],
        study_count=2,
        participant_count=400,
        data_type=DataType.CONTINUOUS,
        effect_measure="Mean Difference",
        analysis_model="random_effect",
        statistical_method="inverse_variance",
        ci_level="95%",
        estimation_status=EstimationStatus.COMPUTED,
        effect_value=-1.1,
        ci_lower=-1.5,
        ci_upper=-0.7,
    )
    rows = [
        _data_row(
            index=1,
            setting=setting,
            effect=-1.2,
            ci_lower=-1.8,
            ci_upper=-0.6,
            weight_fraction=0.45,
        ),
        _data_row(
            index=2,
            setting=setting,
            effect=-1.0,
            ci_lower=-1.5,
            ci_upper=-0.5,
            weight_fraction=0.55,
        ),
    ]
    study_pio = [_adult_study(1), _child_study(2)]
    grade_input = _grade_indirectness_input(
        setting=setting,
        estimate=estimate,
        estimate_type="overall",
        meta_analysis_result=MetaAnalysisResultPackage(
            review_id="live-indirectness",
            analysis_settings=[setting],
            meta_analysis_data_rows=rows,
            overall_estimates=[estimate],
        ),
        question_pico=QuestionPICO(
            P=["Children aged 6 to 12 years with episodic migraine"],
            I=["CGRP monoclonal antibody"],
            C=["Placebo"],
            O=["Monthly migraine days at 12 weeks"],
        ),
        screening_criteria=ScreeningCriteria(
            inclusion_criteria=[
                "Randomized controlled trials in children aged 6 to 12 years"
            ],
            exclusion_criteria=["Adults-only study populations"],
        ),
        study_characteristics=study_pio,
    )

    result = Method().run(grade_input=grade_input)

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    assert result["domain"] == "indirectness"
    assert result["severity"] in {
        "not_serious",
        "serious",
        "very_serious",
        "unclear",
    }
    assert len(result["decision_features"]["classification"]["study_assessments"]) == 2
    assert result["decision_features"]["evidence_profile"]["weight_coverage"][
        "status"
    ] == "complete"
    assert result["decision_features"]["evidence_profile"]["threshold_requirement"][
        "needed"
    ] is True
    assert result["decision_features"]["evidence_profile"]["threshold_profile"][
        "status"
    ] in {"generated", "no_effect_only", "unavailable"}


def _data_row(
    *,
    index: int,
    setting: AnalysisSetting,
    effect: float,
    ci_lower: float,
    ci_upper: float,
    weight_fraction: float,
) -> MetaAnalysisDataRow:
    return MetaAnalysisDataRow(
        data_row_id=f"row-adult-{index}",
        setting_id=setting.setting_id,
        setting_family_id=setting.setting_family_id,
        study_id=f"adult-rct-{index}",
        data_type=DataType.CONTINUOUS,
        comparison=StudyResultComparison(
            experimental_arm="CGRP monoclonal antibody",
            control_arm="Placebo",
        ),
        outcome=StudyResultOutcome(
            label="Monthly migraine days",
            timepoint="12 weeks",
        ),
        subgroup=AnalysisSubgroup(),
        result_data=ContinuousResultData(
            experimental_mean=-4.0,
            experimental_sd=3.0,
            experimental_total=100,
            control_mean=-2.9,
            control_sd=3.0,
            control_total=100,
        ),
        source_candidate_ids=[f"candidate-{index}"],
        resolution_id=f"resolution-{index}",
        method_id="inverse-variance-random",
        estimate_id="estimate-migraine",
        estimate_scope="overall",
        analysis_status="included",
        participant_count=200,
        effect_measure="Mean Difference",
        analysis_model="random_effect",
        statistical_method="inverse_variance",
        analysis_effect=effect,
        analysis_scale="identity",
        effect_value=effect,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        variance=0.09,
        standard_error=0.3,
        weight=weight_fraction * 100,
        weight_fraction=weight_fraction,
    )


def _adult_study(index: int) -> StudyPIOCharacteristics:
    return StudyPIOCharacteristics(
        study_id=f"adult-rct-{index}",
        population=StudyPopulationCharacteristics(
            description="Adults aged 18 to 65 years with episodic migraine",
            eligibility_notes="People younger than 18 years were excluded.",
        ),
        interventions=[
            StudyInterventionCharacteristics(
                label="CGRP monoclonal antibody",
                description="Monthly subcutaneous administration",
            )
        ],
        comparators=[
            StudyComparatorCharacteristics(
                label="Placebo",
                description="Matched subcutaneous placebo",
            )
        ],
        outcomes=[
            StudyOutcomeCharacteristics(
                outcome_label="Monthly migraine days",
                measurement="Change from baseline in monthly migraine days",
                timepoints=["12 weeks"],
            )
        ],
    )


def _child_study(index: int) -> StudyPIOCharacteristics:
    return StudyPIOCharacteristics(
        study_id=f"adult-rct-{index}",
        population=StudyPopulationCharacteristics(
            description="Children aged 6 to 12 years with episodic migraine",
            eligibility_notes="Participants were 6 to 12 years old.",
        ),
        interventions=[
            StudyInterventionCharacteristics(
                label="CGRP monoclonal antibody",
                description="Monthly subcutaneous administration",
            )
        ],
        comparators=[
            StudyComparatorCharacteristics(
                label="Placebo",
                description="Matched subcutaneous placebo",
            )
        ],
        outcomes=[
            StudyOutcomeCharacteristics(
                outcome_label="Monthly migraine days",
                measurement="Change from baseline in monthly migraine days",
                timepoints=["12 weeks"],
            )
        ],
    )
