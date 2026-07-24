from __future__ import annotations

import json
import os

import pytest

from ebm_backend.online_pipeline.domain.common import DataType
from ebm_backend.online_pipeline.domain.grade import (
    GRADEImprecisionCoverage,
    GRADEImprecisionDataRow,
    GRADEImprecisionEstimate,
    GRADEImprecisionInput,
    GRADEImprecisionSetting,
)
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSubgroup,
    AnalysisTimepoint,
    ContinuousResultData,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.method import (
    Method,
)


RUN_LIVE_LLM_TESTS = os.getenv("RUN_LIVE_LLM_TESTS") == "1"


@pytest.mark.skipif(
    not RUN_LIVE_LLM_TESTS,
    reason="Set RUN_LIVE_LLM_TESTS=1 to run live GRADE imprecision assessment.",
)
def test_live_systolic_blood_pressure_mean_difference() -> None:
    grade_input = _systolic_blood_pressure_input()

    result = Method().run(grade_input=grade_input)

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    assert result["domain"] == "imprecision"
    assert result["severity"] in {
        "not_serious",
        "serious",
        "very_serious",
        "unclear",
    }
    assert result["levels"] in {0, 1, 2, "unclear"}
    assert result["debug"]["numeric_profile"]["decision_scale"] == (
        "mean_difference"
    )
    threshold = result["debug"]["threshold"]
    assert threshold["status"] in {"usable", "unavailable"}
    if threshold["status"] == "usable":
        assert threshold["threshold_scale"] == "mean_difference"
        assert threshold["important_benefit"] < 0 < threshold["important_harm"]


def _systolic_blood_pressure_input() -> GRADEImprecisionInput:
    rows = [
        GRADEImprecisionDataRow(
            data_row_id=f"row-{index}",
            study_id=f"study-{index}",
            data_type=DataType.CONTINUOUS,
            result_data=ContinuousResultData(
                experimental_mean=132.0,
                experimental_sd=12.0,
                experimental_total=100,
                control_mean=136.0,
                control_sd=12.0,
                control_total=100,
            ),
        )
        for index in (1, 2)
    ]
    return GRADEImprecisionInput(
        setting=GRADEImprecisionSetting(
            setting_id="live-sbp-setting",
            setting_family_id="live-sbp-family",
            population="Adults with uncomplicated primary hypertension",
            comparison=AnalysisComparison(
                experimental="Structured aerobic exercise programme",
                comparator="Usual care without structured exercise",
            ),
            outcome=AnalysisOutcome(
                label="Change in office systolic blood pressure",
                measure="mmHg",
            ),
            timepoint=AnalysisTimepoint(label="12 weeks"),
            subgroup=AnalysisSubgroup(),
            data_type=DataType.CONTINUOUS,
            effect_measure="Mean Difference",
        ),
        estimate=GRADEImprecisionEstimate(
            estimate_type="overall",
            estimate_id="live-sbp-estimate",
            estimation_status="computed",
            included_study_ids=["study-1", "study-2"],
            included_data_row_ids=["row-1", "row-2"],
            participant_count=400,
            data_type=DataType.CONTINUOUS,
            effect_measure="Mean Difference",
            ci_level="95%",
            pooled_effect=-4.0,
            ci_lower=-6.5,
            ci_upper=-1.5,
            effect_direction_convention="original_measure_direction",
        ),
        contributing_data_rows=rows,
        coverage=GRADEImprecisionCoverage(
            expected_data_row_ids=["row-1", "row-2"],
            available_data_row_ids=["row-1", "row-2"],
            missing_data_row_ids=[],
        ),
    )
