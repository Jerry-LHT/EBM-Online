from __future__ import annotations

from dataclasses import replace
import json

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_grade import (
    _dataclass_judgement,
    _grade_imprecision_input,
)
from ebm_backend.online_pipeline.domain.common import (
    DataType,
    EstimationStatus,
    GradeDomainName,
)
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
    AnalysisSetting,
    AnalysisSubgroup,
    AnalysisTimepoint,
    ContinuousResultData,
    DichotomousResultData,
    GenericInverseVarianceResultData,
    MetaAnalysisDataRow,
    MetaAnalysisResultPackage,
    OverallEstimate,
    StudyResultComparison,
    StudyResultOutcome,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.calculator import (
    build_numeric_profile,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.errors import (
    GRADEImprecisionInvocationError,
    GRADEImprecisionThresholdError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.method import (
    Method,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMAPIError


CONFIG = {
    "api_key": "test-key",
    "base_url": "https://example.test/v1",
    "model": "test-model",
    "api_mode": "responses",
}


def test_result_blind_threshold_and_absolute_ci_produce_serious_judgement() -> None:
    seen: dict[str, object] = {}

    def caller(**kwargs):
        seen.update(kwargs)
        payload = json.loads(kwargs["prompt"])
        assert set(payload) == {
            "analysis_effect_direction_convention",
            "certainty_target",
            "required_threshold_scale",
            "result_blinding",
            "setting",
            "task",
            "threshold_value_contract",
        }
        assert all(
            value is False for value in payload["result_blinding"].values()
        )
        assert "estimate" not in payload
        assert "data_rows" not in payload
        return _threshold(
            scale="absolute_risk_difference_per_1000",
            benefit=-20.0,
            harm=20.0,
            unit="events per 1000",
            direction="event_is_harmful",
        )

    result = Method(config=CONFIG, caller=caller).run(
        grade_input=_binary_input(
            effect_measure="Risk Ratio",
            effect=0.80,
            lower=0.60,
            upper=1.05,
            participants=2000,
            result_data=DichotomousResultData(
                experimental_events=80,
                experimental_total=1000,
                control_events=100,
                control_total=1000,
            ),
        )
    )

    assert result["severity"] == "serious"
    assert result["levels"] == 1
    assert result["debug"]["numeric_profile"]["decision_ci_lower"] == pytest.approx(-40.0)
    assert result["debug"]["numeric_profile"]["decision_ci_upper"] == pytest.approx(5.0)
    assert "-40" in result["rationale"]
    assert "-20" in result["rationale"]
    assert "expert_judgement" in result["rationale"]
    public_judgement = _dataclass_judgement(
        result,
        GradeDomainName.IMPRECISION,
    )
    assert "-40" in public_judgement.rationale
    assert "-20" in public_judgement.rationale
    assert seen["tools"] == [{"type": "web_search"}]
    assert seen["config"]["sdk_max_retries"] == 0
    assert seen["config"]["json_marker_retry_enabled"] is False


def test_chat_mode_omits_responses_only_web_search_tool() -> None:
    seen: dict[str, object] = {}

    def caller(**kwargs):
        seen.update(kwargs)
        return _threshold(
            scale="absolute_risk_difference_per_1000",
            benefit=-20.0,
            harm=20.0,
            unit="events per 1000",
            direction="event_is_harmful",
        )

    Method(
        config={**CONFIG, "api_mode": "chat"},
        caller=caller,
    ).run(
        grade_input=_binary_input(
            effect_measure="Risk Ratio",
            effect=0.80,
            lower=0.60,
            upper=1.05,
            participants=2000,
            result_data=DichotomousResultData(
                experimental_events=80,
                experimental_total=1000,
                control_events=100,
                control_total=1000,
            ),
        )
    )

    assert seen["tools"] is None


def test_odds_ratio_uses_odds_to_risk_conversion() -> None:
    profile = build_numeric_profile(
        _binary_input(
            effect_measure="Odds Ratio",
            effect=2.0,
            lower=1.5,
            upper=2.5,
            participants=2000,
            result_data=DichotomousResultData(
                experimental_events=600,
                experimental_total=1000,
                control_events=500,
                control_total=1000,
            ),
        )
    )

    assert profile["decision_effect"] == pytest.approx(166.6666667)
    assert profile["decision_ci_lower"] == pytest.approx(100.0)
    assert profile["decision_ci_upper"] == pytest.approx(214.2857143)


def test_narrow_continuous_ci_is_downgraded_when_ois_is_not_met() -> None:
    result = Method(
        config=CONFIG,
        caller=lambda **_: _threshold(
            scale="mean_difference",
            benefit=-1.0,
            harm=1.0,
            unit="scale points",
            direction="lower_is_better",
        ),
    ).run(
        grade_input=_continuous_input(
            effect=0.0,
            lower=-0.1,
            upper=0.1,
            participants=100,
        )
    )

    assert result["severity"] == "serious"
    assert result["levels"] == 1
    assert result["debug"]["ois"]["reason"] == "ois_not_met"
    assert result["debug"]["ois"]["used_for_decision"] is True


def test_narrow_continuous_ci_is_not_downgraded_when_ois_is_met() -> None:
    result = Method(
        config=CONFIG,
        caller=lambda **_: _threshold(
            scale="mean_difference",
            benefit=-1.0,
            harm=1.0,
            unit="scale points",
            direction="lower_is_better",
        ),
    ).run(
        grade_input=_continuous_input(
            effect=0.0,
            lower=-0.1,
            upper=0.1,
            participants=4000,
        )
    )

    assert result["severity"] == "not_serious"
    assert result["assessment_status"] == "assessed"
    assert result["levels"] == 0
    assert result["debug"]["ois"]["reason"] == "ois_met"


def test_ci_crossing_benefit_and_harm_is_very_serious() -> None:
    result = Method(
        config=CONFIG,
        caller=lambda **_: _threshold(
            scale="mean_difference",
            benefit=-1.0,
            harm=1.0,
            unit="scale points",
            direction="lower_is_better",
        ),
    ).run(
        grade_input=_continuous_input(
            effect=0.0,
            lower=-2.0,
            upper=2.0,
            participants=500,
        )
    )

    assert result["severity"] == "very_serious"
    assert result["levels"] == 2


def test_binary_effect_uses_clinical_threshold_ois_when_ci_does_not_cross() -> None:
    result = Method(
        config=CONFIG,
        caller=lambda **_: _threshold(
            scale="absolute_risk_difference_per_1000",
            benefit=-20.0,
            harm=20.0,
            unit="events per 1000",
            direction="event_is_harmful",
        ),
    ).run(
        grade_input=_binary_input(
            effect_measure="Risk Ratio",
            effect=0.50,
            lower=0.40,
            upper=0.60,
            participants=100,
            result_data=DichotomousResultData(
                experimental_events=5,
                experimental_total=50,
                control_events=10,
                control_total=50,
            ),
        )
    )

    assert result["severity"] == "serious"
    assert result["debug"]["decision_reason"] == "ois_not_met"
    assert result["debug"]["ois"]["used_for_decision"] is True
    assert result["debug"]["ois"]["concern"] is True


def test_unavailable_threshold_returns_unclear() -> None:
    result = Method(config=CONFIG, caller=lambda **_: _unavailable_threshold()).run(
        grade_input=_continuous_input(
            effect=-0.5,
            lower=-0.8,
            upper=-0.2,
            participants=300,
        )
    )

    assert result["severity"] == "unclear"
    assert result["levels"] == "unclear"
    assert result["level_evaluable"] is False


def test_missing_exact_rows_for_ratio_returns_unclear_without_llm_call() -> None:
    grade_input = _binary_input(
        effect_measure="Risk Ratio",
        effect=0.8,
        lower=0.6,
        upper=1.0,
        participants=200,
        result_data=DichotomousResultData(
            experimental_events=10,
            experimental_total=100,
            control_events=20,
            control_total=100,
        ),
    )
    grade_input = GRADEImprecisionInput(
        setting=grade_input.setting,
        estimate=grade_input.estimate,
        contributing_data_rows=[],
        coverage=GRADEImprecisionCoverage(
            expected_data_row_ids=["row-1"],
            available_data_row_ids=[],
            missing_data_row_ids=["row-1"],
        ),
    )

    def caller(**_):
        raise AssertionError("LLM must not be called when numeric evidence is unusable")

    result = Method(config=CONFIG, caller=caller).run(grade_input=grade_input)

    assert result["severity"] == "unclear"
    assert result["debug"]["decision_reason"] == "contributing_data_rows_incomplete"


def test_invalid_threshold_is_retried_once() -> None:
    calls = 0

    def caller(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _threshold(
                scale="mean_difference",
                benefit=-1.0,
                harm=-0.5,
                unit="scale points",
                direction="lower_is_better",
                invalid_magnitude=True,
            )
        return _threshold(
            scale="mean_difference",
            benefit=-1.0,
            harm=1.0,
            unit="scale points",
            direction="lower_is_better",
        )

    result = Method(config=CONFIG, caller=caller).run(
        grade_input=_continuous_input(
            effect=0.0,
            lower=-0.1,
            upper=0.1,
            participants=4000,
        )
    )

    assert calls == 2
    assert result["severity"] == "not_serious"


def test_invalid_threshold_after_retry_has_stable_method_error() -> None:
    calls = 0

    def caller(**_):
        nonlocal calls
        calls += 1
        return _threshold(
            scale="mean_difference",
            benefit=-1.0,
            harm=-0.5,
            unit="scale points",
            direction="lower_is_better",
            invalid_magnitude=True,
        )

    with pytest.raises(GRADEImprecisionThresholdError) as raised:
        Method(config=CONFIG, caller=caller).run(
            grade_input=_continuous_input(
                effect=0.0,
                lower=-0.1,
                upper=0.1,
                participants=500,
            )
        )

    assert calls == 2
    assert raised.value.attempts == 2


def test_smd_threshold_is_mapped_to_positive_favors_experimental_convention() -> None:
    def caller(**kwargs):
        payload = json.loads(kwargs["prompt"])
        assert payload["analysis_effect_direction_convention"] == (
            "positive_favors_experimental"
        )
        return _threshold(
            scale="standardized_mean_difference",
            benefit=0.5,
            harm=0.5,
            unit="standard deviation units",
            direction="lower_is_better",
        )

    result = Method(config=CONFIG, caller=caller).run(
        grade_input=_smd_input(
            effect=0.3,
            lower=0.1,
            upper=0.7,
            participants=500,
        )
    )

    assert result["severity"] == "serious"
    assert result["debug"]["threshold"]["important_benefit"] == 0.5
    assert result["debug"]["threshold"]["important_harm"] == -0.5
    assert result["debug"]["decision_reason"] == "ci_crosses_benefit_threshold"


def test_low_confidence_expert_threshold_returns_unclear() -> None:
    result = Method(
        config=CONFIG,
        caller=lambda **_: _threshold(
            scale="mean_difference",
            benefit=1.0,
            harm=1.0,
            unit="scale points",
            direction="lower_is_better",
            confidence="low",
        ),
    ).run(
        grade_input=_continuous_input(
            effect=0.0,
            lower=-0.1,
            upper=0.1,
            participants=4000,
        )
    )

    assert result["severity"] == "unclear"
    assert result["debug"]["decision_reason"] == "threshold_low_confidence"


def test_incomplete_continuous_rows_return_unclear_without_llm_call() -> None:
    grade_input = _continuous_input(
        effect=0.0,
        lower=-0.1,
        upper=0.1,
        participants=200,
    )
    grade_input = replace(
        grade_input,
        contributing_data_rows=[],
        coverage=GRADEImprecisionCoverage(
            expected_data_row_ids=["row-continuous"],
            available_data_row_ids=[],
            missing_data_row_ids=["row-continuous"],
        ),
    )

    def caller(**_):
        raise AssertionError("LLM must not be called for incomplete DataRows")

    result = Method(config=CONFIG, caller=caller).run(grade_input=grade_input)

    assert result["severity"] == "unclear"
    assert result["debug"]["decision_reason"] == "contributing_data_rows_incomplete"


def test_participant_count_mismatch_returns_unclear_without_llm_call() -> None:
    grade_input = _continuous_input(
        effect=0.0,
        lower=-0.1,
        upper=0.1,
        participants=200,
    )
    grade_input = replace(
        grade_input,
        estimate=replace(grade_input.estimate, participant_count=201),
    )

    def caller(**_):
        raise AssertionError("LLM must not be called for inconsistent participants")

    result = Method(config=CONFIG, caller=caller).run(grade_input=grade_input)

    assert result["severity"] == "unclear"
    assert result["debug"]["decision_reason"] == "participant_count_mismatch"


def test_direct_effect_row_supplies_participant_count_to_imprecision() -> None:
    grade_input = _continuous_input(
        effect=-0.77,
        lower=-1.20,
        upper=-0.34,
        participants=50,
    )
    grade_input = replace(
        grade_input,
        contributing_data_rows=[
            GRADEImprecisionDataRow(
                data_row_id="row-continuous",
                study_id="study-continuous",
                data_type=DataType.CONTINUOUS,
                result_data=GenericInverseVarianceResultData(
                    effect_value=-0.77,
                    standard_error=0.21939179,
                    effect_measure="Mean Difference",
                    participant_count=50,
                ),
            )
        ],
    )

    profile = build_numeric_profile(grade_input)

    assert profile["status"] == "usable"
    assert profile["participant_count"] == 50
    assert profile["pooled_sd"] is None


def test_effect_outside_confidence_interval_is_unclear_without_llm_call() -> None:
    def caller(**_):
        raise AssertionError("LLM must not be called for inconsistent numeric evidence")

    result = Method(config=CONFIG, caller=caller).run(
        grade_input=_continuous_input(
            effect=2.0,
            lower=-0.5,
            upper=0.5,
            participants=500,
        )
    )

    assert result["severity"] == "unclear"
    assert result["debug"]["decision_reason"] == (
        "effect_outside_confidence_interval"
    )


def test_retryable_provider_error_is_retried_once() -> None:
    calls = 0

    def caller(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _llm_error(retryable=True)
        return _threshold(
            scale="mean_difference",
            benefit=1.0,
            harm=1.0,
            unit="scale points",
            direction="lower_is_better",
        )

    result = Method(config=CONFIG, caller=caller).run(
        grade_input=_continuous_input(
            effect=0.0,
            lower=-0.1,
            upper=0.1,
            participants=4000,
        )
    )

    assert calls == 2
    assert result["severity"] == "not_serious"


def test_non_retryable_provider_error_fails_after_one_call() -> None:
    calls = 0

    def caller(**_):
        nonlocal calls
        calls += 1
        raise _llm_error(retryable=False)

    with pytest.raises(GRADEImprecisionInvocationError) as raised:
        Method(config=CONFIG, caller=caller).run(
            grade_input=_continuous_input(
                effect=0.0,
                lower=-0.1,
                upper=0.1,
                participants=4000,
            )
        )

    assert calls == 1
    assert raised.value.attempts == 1
    assert raised.value.retry_exhausted is False


def test_unknown_program_error_is_not_retried_or_wrapped() -> None:
    calls = 0

    def caller(**_):
        nonlocal calls
        calls += 1
        raise RuntimeError("programming defect")

    with pytest.raises(RuntimeError, match="programming defect"):
        Method(config=CONFIG, caller=caller).run(
            grade_input=_continuous_input(
                effect=0.0,
                lower=-0.1,
                upper=0.1,
                participants=4000,
            )
        )

    assert calls == 1


def test_application_builder_uses_exact_estimate_data_row_ids() -> None:
    setting = _analysis_setting(data_type=DataType.DICHOTOMOUS)
    estimate = OverallEstimate(
        overall_estimate_id="estimate-1",
        setting_id=setting.setting_id,
        setting_family_id=setting.setting_family_id,
        method_id="method-1",
        included_study_ids=["study-1"],
        included_data_row_ids=["row-1"],
        study_count=1,
        participant_count=200,
        data_type=DataType.DICHOTOMOUS,
        effect_measure="Risk Ratio",
        analysis_model="common_effect",
        statistical_method="Mantel-Haenszel",
        ci_level="95%",
        estimation_status=EstimationStatus.COMPUTED,
        effect_value=0.8,
        ci_lower=0.6,
        ci_upper=1.0,
        effect_direction_convention="experimental_relative_to_control",
    )
    result_data = DichotomousResultData(
        experimental_events=10,
        experimental_total=100,
        control_events=20,
        control_total=100,
    )
    package = MetaAnalysisResultPackage(
        review_id="review-1",
        meta_analysis_data_rows=[
            _meta_row("row-1", "estimate-1", result_data),
            _meta_row("wrong-row", "estimate-1", result_data),
            _meta_row("row-1", "other-estimate", result_data),
        ],
    )

    grade_input = _grade_imprecision_input(
        setting=setting,
        estimate=estimate,
        estimate_type="overall",
        meta_analysis_result=package,
    )

    assert [row.data_row_id for row in grade_input.contributing_data_rows] == [
        "row-1"
    ]
    assert grade_input.coverage.missing_data_row_ids == []
    assert not hasattr(grade_input, "study_characteristics")
    assert not hasattr(grade_input, "risk_of_bias")


def _binary_input(
    *,
    effect_measure: str,
    effect: float,
    lower: float,
    upper: float,
    participants: int,
    result_data: DichotomousResultData,
) -> GRADEImprecisionInput:
    setting = GRADEImprecisionSetting(
        setting_id="setting-1",
        setting_family_id="family-1",
        population="adults at high cardiovascular risk",
        comparison=AnalysisComparison(
            experimental="intensive treatment",
            comparator="usual treatment",
        ),
        outcome=AnalysisOutcome(label="stroke within one year"),
        timepoint=AnalysisTimepoint(label="1 year"),
        subgroup=AnalysisSubgroup(),
        data_type=DataType.DICHOTOMOUS,
        effect_measure=effect_measure,
    )
    row = GRADEImprecisionDataRow(
        data_row_id="row-1",
        study_id="study-1",
        data_type=DataType.DICHOTOMOUS,
        result_data=result_data,
    )
    return GRADEImprecisionInput(
        setting=setting,
        estimate=GRADEImprecisionEstimate(
            estimate_type="overall",
            estimate_id="estimate-1",
            estimation_status="computed",
            included_study_ids=["study-1"],
            included_data_row_ids=["row-1"],
            participant_count=participants,
            data_type=DataType.DICHOTOMOUS,
            effect_measure=effect_measure,
            ci_level="95%",
            pooled_effect=effect,
            ci_lower=lower,
            ci_upper=upper,
            effect_direction_convention="experimental_relative_to_control",
        ),
        contributing_data_rows=[row],
        coverage=GRADEImprecisionCoverage(
            expected_data_row_ids=["row-1"],
            available_data_row_ids=["row-1"],
            missing_data_row_ids=[],
        ),
    )


def _continuous_input(
    *,
    effect: float,
    lower: float,
    upper: float,
    participants: int,
) -> GRADEImprecisionInput:
    setting = GRADEImprecisionSetting(
        setting_id="setting-continuous",
        setting_family_id="family-continuous",
        population="adults with hypertension",
        comparison=AnalysisComparison(
            experimental="exercise",
            comparator="usual care",
        ),
        outcome=AnalysisOutcome(
            label="systolic blood pressure",
            measure="mmHg",
        ),
        timepoint=AnalysisTimepoint(label="12 weeks"),
        subgroup=AnalysisSubgroup(),
        data_type=DataType.CONTINUOUS,
        effect_measure="Mean Difference",
    )
    row = GRADEImprecisionDataRow(
        data_row_id="row-continuous",
        study_id="study-continuous",
        data_type=DataType.CONTINUOUS,
        result_data=ContinuousResultData(
            experimental_mean=120.0,
            experimental_sd=10.0,
            experimental_total=participants // 2,
            control_mean=121.0,
            control_sd=10.0,
            control_total=participants - participants // 2,
        ),
    )
    return GRADEImprecisionInput(
        setting=setting,
        estimate=GRADEImprecisionEstimate(
            estimate_type="overall",
            estimate_id="estimate-continuous",
            estimation_status="computed",
            included_study_ids=["study-continuous"],
            included_data_row_ids=["row-continuous"],
            participant_count=participants,
            data_type=DataType.CONTINUOUS,
            effect_measure="Mean Difference",
            ci_level="95%",
            pooled_effect=effect,
            ci_lower=lower,
            ci_upper=upper,
            effect_direction_convention="original_measure_direction",
        ),
        contributing_data_rows=[row],
        coverage=GRADEImprecisionCoverage(
            expected_data_row_ids=["row-continuous"],
            available_data_row_ids=["row-continuous"],
            missing_data_row_ids=[],
        ),
    )


def _smd_input(
    *,
    effect: float,
    lower: float,
    upper: float,
    participants: int,
) -> GRADEImprecisionInput:
    grade_input = _continuous_input(
        effect=effect,
        lower=lower,
        upper=upper,
        participants=participants,
    )
    return replace(
        grade_input,
        setting=replace(
            grade_input.setting,
            outcome=AnalysisOutcome(
                label="depressive symptom severity",
                measure="validated scales; lower scores are better",
            ),
            effect_measure="Std. Mean Difference",
        ),
        estimate=replace(
            grade_input.estimate,
            effect_measure="Std. Mean Difference",
            effect_direction_convention="positive_favors_experimental",
        ),
    )


def _threshold(
    *,
    scale: str,
    benefit: float,
    harm: float,
    unit: str,
    direction: str,
    confidence: str = "medium",
    invalid_magnitude: bool = False,
) -> dict[str, object]:
    return {
        "status": "usable",
        "threshold_scale": scale,
        "important_benefit_magnitude": (
            -abs(benefit) if invalid_magnitude else abs(benefit)
        ),
        "important_harm_magnitude": abs(harm),
        "unit": unit,
        "outcome_direction": direction,
        "basis": "expert_judgement",
        "source_urls": [],
        "source_summary": "No directly applicable MID was identified.",
        "rationale": "A conservative clinical threshold was selected prospectively.",
        "confidence": confidence,
    }


def _unavailable_threshold() -> dict[str, object]:
    return {
        "status": "unavailable",
        "threshold_scale": "unavailable",
        "important_benefit_magnitude": None,
        "important_harm_magnitude": None,
        "unit": "",
        "outcome_direction": "unclear",
        "basis": "unavailable",
        "source_urls": [],
        "source_summary": "",
        "rationale": "No defensible clinical threshold could be established.",
        "confidence": "none",
    }


def _llm_error(*, retryable: bool) -> LLMAPIError:
    return LLMAPIError(
        "provider failed",
        status_code=429 if retryable else 400,
        request_id="request-1",
        retry_after_seconds=None,
        retryable=retryable,
        provider_message="provider failed",
    )


def _analysis_setting(*, data_type: DataType) -> AnalysisSetting:
    return AnalysisSetting(
        setting_id="setting-1",
        setting_family_id="family-1",
        population_scope="adults",
        comparison=AnalysisComparison(
            experimental="treatment",
            comparator="control",
        ),
        outcome=AnalysisOutcome(label="stroke"),
        timepoint=AnalysisTimepoint(label="1 year"),
        subgroup=AnalysisSubgroup(),
        data_type=data_type,
    )


def _meta_row(
    data_row_id: str,
    estimate_id: str,
    result_data: DichotomousResultData,
) -> MetaAnalysisDataRow:
    return MetaAnalysisDataRow(
        data_row_id=data_row_id,
        setting_id="setting-1",
        setting_family_id="family-1",
        study_id="study-1",
        data_type=DataType.DICHOTOMOUS,
        comparison=StudyResultComparison(
            experimental_arm="treatment",
            control_arm="control",
        ),
        outcome=StudyResultOutcome(label="stroke", timepoint="1 year"),
        subgroup=AnalysisSubgroup(),
        result_data=result_data,
        source_candidate_ids=["candidate-1"],
        resolution_id="resolution-1",
        estimate_id=estimate_id,
        estimate_scope="overall",
        analysis_status="included",
        participant_count=200,
        effect_measure="Risk Ratio",
        analysis_model="common_effect",
        statistical_method="Mantel-Haenszel",
        analysis_effect=-0.2231435513,
        analysis_scale="log",
        effect_value=0.8,
        ci_lower=0.6,
        ci_upper=1.0,
        variance=0.01,
        standard_error=0.1,
        weight=100.0,
        weight_fraction=1.0,
    )
