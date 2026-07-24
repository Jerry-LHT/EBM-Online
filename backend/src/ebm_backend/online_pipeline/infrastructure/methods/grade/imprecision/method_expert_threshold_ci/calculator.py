"""Deterministic evidence transformations for GRADE imprecision."""

from __future__ import annotations

import math
from typing import Any, Callable

from ebm_backend.online_pipeline.domain.common import DataType
from ebm_backend.online_pipeline.domain.grade import GRADEImprecisionInput
from ebm_backend.online_pipeline.domain.meta_analysis import (
    ContinuousResultData,
    DichotomousResultData,
    GenericInverseVarianceResultData,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.threshold import (
    expected_effect_direction_convention,
)


def build_numeric_profile(grade_input: GRADEImprecisionInput) -> dict[str, Any]:
    estimate = grade_input.estimate
    if estimate.estimation_status != "computed":
        return _unavailable("effect_estimate_not_computed")
    if not _is_95_percent_ci(estimate.ci_level):
        return _unavailable("unsupported_ci_level")
    effect = _finite(estimate.pooled_effect)
    lower = _finite(estimate.ci_lower)
    upper = _finite(estimate.ci_upper)
    if effect is None or lower is None or upper is None:
        return _unavailable("effect_or_ci_unavailable")
    if lower > upper:
        return _unavailable("invalid_ci_order")
    if not lower <= effect <= upper:
        return _unavailable("effect_outside_confidence_interval")

    expected_convention = expected_effect_direction_convention(
        estimate.effect_measure
    )
    if expected_convention is None:
        return _unavailable("unsupported_effect_measure")
    if estimate.effect_direction_convention != expected_convention:
        return _unavailable(
            "effect_direction_convention_unavailable",
            {"expected_effect_direction_convention": expected_convention},
        )
    if grade_input.coverage.missing_data_row_ids:
        return _unavailable(
            "contributing_data_rows_incomplete",
            {
                "missing_data_row_ids": list(
                    grade_input.coverage.missing_data_row_ids
                )
            },
        )
    if not grade_input.contributing_data_rows:
        return _unavailable("contributing_data_rows_unavailable")
    row_participant_count = _row_participant_count(grade_input)
    if row_participant_count is None:
        return _unavailable("contributing_data_rows_invalid")
    if row_participant_count != estimate.participant_count:
        return _unavailable(
            "participant_count_mismatch",
            {
                "estimate_participant_count": estimate.participant_count,
                "data_row_participant_count": row_participant_count,
            },
        )

    measure = estimate.effect_measure
    baseline = _binary_summary(grade_input)
    pooled_sd = _pooled_continuous_sd(grade_input)
    common = {
        "status": "usable",
        "reason": "",
        "data_type": estimate.data_type.value,
        "effect_measure": measure,
        "participant_count": row_participant_count,
        "pooled_effect": effect,
        "reported_ci_lower": lower,
        "reported_ci_upper": upper,
        "decision_no_effect": 0.0,
        "control_baseline_risk": baseline.get("control_baseline_risk"),
        "control_events": baseline.get("control_events"),
        "control_total": baseline.get("control_total"),
        "total_events": baseline.get("total_events"),
        "pooled_sd": pooled_sd,
        "coverage_complete": not grade_input.coverage.missing_data_row_ids,
    }

    if measure == "Risk Difference":
        return {
            **common,
            "decision_scale": "absolute_risk_difference_per_1000",
            "decision_effect": effect * 1000.0,
            "decision_ci_lower": lower * 1000.0,
            "decision_ci_upper": upper * 1000.0,
        }
    if measure in {"Risk Ratio", "Odds Ratio"}:
        if lower <= 0 or effect <= 0:
            return _unavailable("invalid_ratio_estimate", common)
        p0 = baseline.get("control_baseline_risk")
        if p0 is None or grade_input.coverage.missing_data_row_ids:
            return _unavailable("control_baseline_risk_unavailable", common)
        transform: Callable[[float, float], float | None] = (
            _risk_ratio_difference
            if measure == "Risk Ratio"
            else _odds_ratio_difference
        )
        converted = [transform(value, p0) for value in (effect, lower, upper)]
        if any(value is None for value in converted):
            return _unavailable("absolute_effect_conversion_invalid", common)
        point, converted_lower, converted_upper = converted
        return {
            **common,
            "decision_scale": "absolute_risk_difference_per_1000",
            "decision_effect": point,
            "decision_ci_lower": converted_lower,
            "decision_ci_upper": converted_upper,
        }
    if measure == "Mean Difference":
        return {
            **common,
            "decision_scale": "mean_difference",
            "decision_effect": effect,
            "decision_ci_lower": lower,
            "decision_ci_upper": upper,
        }
    if measure == "Std. Mean Difference":
        return {
            **common,
            "decision_scale": "standardized_mean_difference",
            "decision_effect": effect,
            "decision_ci_lower": lower,
            "decision_ci_upper": upper,
        }
    return _unavailable("unsupported_effect_measure", common)


def _binary_summary(grade_input: GRADEImprecisionInput) -> dict[str, Any]:
    if grade_input.setting.data_type != DataType.DICHOTOMOUS:
        return {}
    control_events = control_total = experimental_events = experimental_total = 0
    for row in grade_input.contributing_data_rows:
        data = row.result_data
        if not isinstance(data, DichotomousResultData) or not _valid_binary(data):
            return {}
        control_events += data.control_events
        control_total += data.control_total
        experimental_events += data.experimental_events
        experimental_total += data.experimental_total
    if control_total <= 0 or experimental_total <= 0:
        return {}
    risk = control_events / control_total
    if not 0 < risk < 1:
        return {
            "control_events": control_events,
            "control_total": control_total,
            "total_events": control_events + experimental_events,
        }
    return {
        "control_baseline_risk": risk,
        "control_events": control_events,
        "control_total": control_total,
        "experimental_events": experimental_events,
        "experimental_total": experimental_total,
        "total_events": control_events + experimental_events,
    }


def _pooled_continuous_sd(grade_input: GRADEImprecisionInput) -> float | None:
    if grade_input.setting.data_type != DataType.CONTINUOUS:
        return None
    sum_squares = 0.0
    degrees_freedom = 0
    for row in grade_input.contributing_data_rows:
        data = row.result_data
        if not isinstance(data, ContinuousResultData) or not _valid_continuous(data):
            return None
        sum_squares += (data.experimental_total - 1) * data.experimental_sd**2
        sum_squares += (data.control_total - 1) * data.control_sd**2
        degrees_freedom += data.experimental_total + data.control_total - 2
    if degrees_freedom <= 0:
        return None
    variance = sum_squares / degrees_freedom
    return math.sqrt(variance) if variance > 0 else None


def _row_participant_count(
    grade_input: GRADEImprecisionInput,
) -> int | None:
    total = 0
    for row in grade_input.contributing_data_rows:
        data = row.result_data
        if isinstance(data, DichotomousResultData):
            if not _valid_binary(data):
                return None
        elif isinstance(data, ContinuousResultData):
            if not _valid_continuous(data):
                return None
            total += data.experimental_total + data.control_total
            continue
        elif isinstance(data, GenericInverseVarianceResultData):
            if data.participant_count is None:
                return None
            total += data.participant_count
            continue
        else:
            return None
        total += data.experimental_total + data.control_total
    return total if total > 0 else None


def _risk_ratio_difference(ratio: float, baseline: float) -> float | None:
    treated_risk = baseline * ratio
    if not 0 <= treated_risk <= 1:
        return None
    return (treated_risk - baseline) * 1000.0


def _odds_ratio_difference(ratio: float, baseline: float) -> float | None:
    denominator = 1.0 - baseline + ratio * baseline
    if denominator <= 0:
        return None
    treated_risk = ratio * baseline / denominator
    if not 0 <= treated_risk <= 1:
        return None
    return (treated_risk - baseline) * 1000.0


def _valid_binary(data: DichotomousResultData) -> bool:
    return (
        data.experimental_total > 0
        and data.control_total > 0
        and 0 <= data.experimental_events <= data.experimental_total
        and 0 <= data.control_events <= data.control_total
    )


def _valid_continuous(data: ContinuousResultData) -> bool:
    return (
        data.experimental_total > 1
        and data.control_total > 1
        and math.isfinite(data.experimental_sd)
        and math.isfinite(data.control_sd)
        and data.experimental_sd >= 0
        and data.control_sd >= 0
    )


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _is_95_percent_ci(value: str) -> bool:
    normalized = value.strip().lower().replace("confidence interval", "").strip()
    return normalized in {"95", "95%", "0.95"}


def _unavailable(
    reason: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {**(existing or {}), "status": "unavailable", "reason": reason}
