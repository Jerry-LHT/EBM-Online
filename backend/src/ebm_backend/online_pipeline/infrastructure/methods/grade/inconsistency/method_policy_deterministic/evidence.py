"""Deterministic evidence profile for bounded GRADE inconsistency judgement."""

from __future__ import annotations

from dataclasses import asdict
from itertools import combinations
import math
from typing import Any

from ebm_backend.online_pipeline.domain.grade import GRADEInconsistencyInput
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.policy import (
    InconsistencyPolicy,
)


def build_evidence_profile(
    *,
    grade_input: GRADEInconsistencyInput,
    policy: InconsistencyPolicy,
) -> dict[str, Any]:
    categories = [
        effect_range(item.effect_value, policy=policy)
        for item in grade_input.study_effects
    ]
    study_effects = [
        {
            "data_row_id": item.data_row_id,
            "study_id": item.study_id,
            "effect_value": item.effect_value,
            "ci_lower": item.ci_lower,
            "ci_upper": item.ci_upper,
            "weight_fraction": item.weight_fraction,
            "range": category,
            "ci_ranges": _ci_ranges(
                lower=item.ci_lower,
                upper=item.ci_upper,
                policy=policy,
            ),
        }
        for item, category in zip(grade_input.study_effects, categories)
    ]
    distribution = _range_distribution(study_effects)
    observed_ranges = list(distribution)
    target_range = (
        effect_range(grade_input.estimate.pooled_effect, policy=policy)
        if grade_input.estimate.pooled_effect is not None
        else None
    )
    pooled_ci_ranges = _ci_ranges(
        lower=grade_input.estimate.ci_lower,
        upper=grade_input.estimate.ci_upper,
        policy=policy,
    )
    return {
        "setting_id": grade_input.setting.setting_id,
        "estimate_id": grade_input.estimate.estimate_id,
        "estimate_type": grade_input.estimate.estimate_type,
        "effect_measure": grade_input.estimate.effect_measure,
        "analysis_model": grade_input.estimate.analysis_model,
        "target_range": target_range,
        "observed_ranges": observed_ranges,
        "threshold_span": _threshold_span(
            observed_ranges,
            has_clinical_boundaries=(
                policy.effect_range_policy.important_benefit_boundary is not None
            ),
        ),
        "study_effects": study_effects,
        "range_distribution": distribution,
        "pooled_estimate": {
            "effect_value": grade_input.estimate.pooled_effect,
            "ci_lower": grade_input.estimate.ci_lower,
            "ci_upper": grade_input.estimate.ci_upper,
            "point_range": target_range,
            "ci_ranges": pooled_ci_ranges,
            "ci_crosses_frozen_threshold": len(pooled_ci_ranges) > 1,
            "prediction_interval": to_jsonable(
                grade_input.estimate.prediction_interval
            ),
        },
        "heterogeneity": to_jsonable(grade_input.estimate.heterogeneity),
        "confidence_interval_overlap": {
            "any_nonoverlapping_pair": _has_nonoverlapping_confidence_intervals(
                grade_input
            ),
            "missing_ci_data_row_ids": list(
                grade_input.coverage.missing_ci_data_row_ids
            ),
        },
        "subgroup_evidence": _subgroup_evidence(grade_input),
        "result_blind_effect_modifiers": [
            asdict(item) for item in policy.plausible_effect_modifiers
        ],
        "weight_coverage": {
            "complete": all(
                item.weight_fraction is not None
                for item in grade_input.study_effects
            ),
            "missing_weight_data_row_ids": list(
                grade_input.coverage.missing_weight_data_row_ids
            ),
        },
    }


def effect_range(value: float, *, policy: InconsistencyPolicy) -> str:
    effect_policy = policy.effect_range_policy
    benefit = effect_policy.important_benefit_boundary
    harm = effect_policy.important_harm_boundary
    if benefit is None or harm is None:
        if math.isclose(
            value,
            effect_policy.no_effect_value,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            return "at_no_effect"
        return (
            "below_no_effect"
            if value < effect_policy.no_effect_value
            else "above_no_effect"
        )
    if effect_policy.benefit_direction == "lower":
        if value <= benefit:
            return "important_benefit"
        if value >= harm:
            return "important_harm"
    else:
        if value >= benefit:
            return "important_benefit"
        if value <= harm:
            return "important_harm"
    return "no_important_effect"


def _ci_ranges(
    *,
    lower: float | None,
    upper: float | None,
    policy: InconsistencyPolicy,
) -> list[str]:
    if lower is None or upper is None:
        return []
    candidates = {effect_range(lower, policy=policy), effect_range(upper, policy=policy)}
    effect_policy = policy.effect_range_policy
    for boundary in (
        effect_policy.important_benefit_boundary,
        effect_policy.no_effect_value,
        effect_policy.important_harm_boundary,
    ):
        if boundary is not None and lower <= boundary <= upper:
            candidates.add(effect_range(boundary, policy=policy))
            epsilon = max(abs(boundary) * 1e-9, 1e-9)
            if lower <= boundary - epsilon:
                candidates.add(effect_range(boundary - epsilon, policy=policy))
            if boundary + epsilon <= upper:
                candidates.add(effect_range(boundary + epsilon, policy=policy))
    return sorted(candidates)


def _range_distribution(
    study_effects: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    complete_weights = bool(study_effects) and all(
        item["weight_fraction"] is not None for item in study_effects
    )
    for item in study_effects:
        category = str(item["range"])
        entry = result.setdefault(
            category,
            {
                "study_count": 0,
                "weight_fraction": 0.0 if complete_weights else None,
                "data_row_ids": [],
                "study_ids": [],
            },
        )
        entry["study_count"] += 1
        entry["data_row_ids"].append(item["data_row_id"])
        entry["study_ids"].append(item["study_id"])
        if complete_weights:
            entry["weight_fraction"] += float(item["weight_fraction"])
    if complete_weights:
        for entry in result.values():
            entry["weight_fraction"] = round(entry["weight_fraction"], 6)
    return result


def _threshold_span(
    observed_ranges: list[str],
    *,
    has_clinical_boundaries: bool,
) -> int:
    if len(observed_ranges) <= 1:
        return 0
    if not has_clinical_boundaries:
        return 1
    positions = {
        "important_harm": 0,
        "no_important_effect": 1,
        "important_benefit": 2,
    }
    present = [positions[item] for item in observed_ranges if item in positions]
    return max(present) - min(present) if present else 0


def _has_nonoverlapping_confidence_intervals(
    grade_input: GRADEInconsistencyInput,
) -> bool:
    intervals = [
        (item.ci_lower, item.ci_upper)
        for item in grade_input.study_effects
        if item.ci_lower is not None and item.ci_upper is not None
    ]
    return any(
        upper_a < lower_b or upper_b < lower_a
        for (lower_a, upper_a), (lower_b, upper_b) in combinations(intervals, 2)
    )


def _subgroup_evidence(
    grade_input: GRADEInconsistencyInput,
) -> list[dict[str, Any]]:
    estimates_by_id = {
        item.subgroup_estimate_id: item for item in grade_input.subgroup_estimates
    }
    return [
        {
            "test_id": test.test_id,
            "subgroup_factor": test.subgroup_factor,
            "test_status": test.test_status,
            "p_value": _float_or_original(test.p_value),
            "chi2": _float_or_original(test.chi2),
            "i2_between_subgroups": _float_or_original(
                test.i2_between_subgroups
            ),
            "compared_subgroups": [
                {
                    "subgroup_estimate_id": estimate.subgroup_estimate_id,
                    "factor": estimate.subgroup.factor,
                    "level": estimate.subgroup.level,
                    "study_count": estimate.study_count,
                    "effect_value": _float_or_original(estimate.effect_value),
                    "ci_lower": _float_or_original(estimate.ci_lower),
                    "ci_upper": _float_or_original(estimate.ci_upper),
                    "heterogeneity": to_jsonable(estimate.heterogeneity),
                }
                for estimate_id in test.compared_subgroup_estimate_ids
                if (estimate := estimates_by_id.get(estimate_id)) is not None
            ],
        }
        for test in grade_input.subgroup_difference_tests
    ]


def _float_or_original(value: Any) -> Any:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value
