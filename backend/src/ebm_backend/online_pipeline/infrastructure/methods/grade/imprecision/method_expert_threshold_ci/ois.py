"""Bounded optimal-information-size calculation for the secondary path."""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.threshold import (
    ThresholdProfile,
)


ALPHA = 0.05
POWER = 0.80


def assess_ois(
    *,
    numeric_profile: dict[str, Any],
    threshold: ThresholdProfile,
) -> dict[str, Any]:
    participants = int(numeric_profile.get("participant_count") or 0)
    if participants <= 0:
        return _not_evaluated("participant_count_unavailable")

    if numeric_profile.get("data_type") == "Dichotomous":
        return _assess_binary(
            numeric_profile=numeric_profile,
            participants=participants,
            threshold=threshold,
        )
    if numeric_profile.get("data_type") == "Continuous":
        required = _continuous_ois(
            numeric_profile=numeric_profile,
            threshold=threshold,
        )
        if required is None:
            return _not_evaluated("continuous_ois_inputs_unavailable")
        return _evaluated(required=required, participants=participants)
    return _not_evaluated("unsupported_data_type")


def _assess_binary(
    *,
    numeric_profile: dict[str, Any],
    participants: int,
    threshold: ThresholdProfile,
) -> dict[str, Any]:
    baseline = numeric_profile.get("control_baseline_risk")
    if baseline is None or not 0 < baseline < 1:
        return _not_evaluated("binary_ois_inputs_unavailable")
    boundaries = [threshold.important_benefit, threshold.important_harm]
    target_risks = [
        baseline + float(boundary) / 1000.0
        for boundary in boundaries
        if boundary is not None
        and 0 < baseline + float(boundary) / 1000.0 < 1
    ]
    required_values = [
        value
        for target in target_risks
        if (value := _two_proportion_ois(baseline=baseline, target=target))
        is not None
    ]
    if not required_values:
        return _not_evaluated("binary_ois_calculation_unavailable")
    required = max(required_values)
    result = _evaluated(required=required, participants=participants)
    return {
        **result,
        "baseline_risk": baseline,
        "target_risks": target_risks,
        "threshold_basis": "clinical_absolute_effect_boundaries",
    }


def _two_proportion_ois(*, baseline: float, target: float) -> int | None:
    if not 0 < baseline < 1 or not 0 < target < 1 or baseline == target:
        return None
    z_alpha = NormalDist().inv_cdf(1.0 - ALPHA / 2.0)
    z_beta = NormalDist().inv_cdf(POWER)
    mean_risk = (baseline + target) / 2.0
    numerator = (
        z_alpha * math.sqrt(2.0 * mean_risk * (1.0 - mean_risk))
        + z_beta
        * math.sqrt(
            baseline * (1.0 - baseline) + target * (1.0 - target)
        )
    ) ** 2
    per_group = numerator / (baseline - target) ** 2
    return max(2, 2 * math.ceil(per_group))


def _continuous_ois(
    *,
    numeric_profile: dict[str, Any],
    threshold: ThresholdProfile,
) -> int | None:
    if threshold.important_benefit is None or threshold.important_harm is None:
        return None
    mid = min(abs(threshold.important_benefit), abs(threshold.important_harm))
    if mid <= 0:
        return None
    if threshold.threshold_scale == "standardized_mean_difference":
        standardized_mid = mid
    elif threshold.threshold_scale == "mean_difference":
        pooled_sd = numeric_profile.get("pooled_sd")
        if pooled_sd is None or pooled_sd <= 0:
            return None
        standardized_mid = mid / pooled_sd
    else:
        return None
    z_alpha = NormalDist().inv_cdf(1.0 - ALPHA / 2.0)
    z_beta = NormalDist().inv_cdf(POWER)
    per_group = 2.0 * (z_alpha + z_beta) ** 2 / standardized_mid**2
    return max(2, 2 * math.ceil(per_group))


def _not_evaluated(reason: str) -> dict[str, Any]:
    return {
        "evaluated": False,
        "used_for_decision": False,
        "concern": False,
        "reason": reason,
        "required_information_size": None,
        "actual_information_size": None,
        "actual_to_required_ratio": None,
        "alpha": ALPHA,
        "power": POWER,
    }


def _evaluated(*, required: int, participants: int) -> dict[str, Any]:
    concern = participants < required
    return {
        "evaluated": True,
        "used_for_decision": True,
        "concern": concern,
        "reason": "ois_not_met" if concern else "ois_met",
        "required_information_size": required,
        "actual_information_size": participants,
        "actual_to_required_ratio": participants / required,
        "alpha": ALPHA,
        "power": POWER,
    }
