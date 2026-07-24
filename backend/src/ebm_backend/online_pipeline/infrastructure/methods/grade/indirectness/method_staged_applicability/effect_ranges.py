"""Deterministic mapping of study effects to a frozen clinical threshold policy."""

from __future__ import annotations

import math
from typing import Any

from ebm_backend.online_pipeline.domain.grade import GRADEIndirectnessInput


EFFECT_MEASURE_ALIASES = {
    "mean difference": "mean_difference",
    "md": "mean_difference",
    "standardized mean difference": "standardized_mean_difference",
    "standardised mean difference": "standardized_mean_difference",
    "std mean difference": "standardized_mean_difference",
    "smd": "standardized_mean_difference",
    "risk difference": "risk_difference",
    "rd": "risk_difference",
    "risk ratio": "risk_ratio",
    "relative risk": "risk_ratio",
    "rr": "risk_ratio",
    "odds ratio": "odds_ratio",
    "or": "odds_ratio",
}
NO_EFFECT_VALUES = {
    "mean_difference": 0.0,
    "standardized_mean_difference": 0.0,
    "risk_difference": 0.0,
    "risk_ratio": 1.0,
    "odds_ratio": 1.0,
}


def normalize_effect_measure(value: str) -> str | None:
    normalized = " ".join(
        value.strip().lower().replace("_", " ").replace("-", " ").split()
    )
    return EFFECT_MEASURE_ALIASES.get(normalized)


def threshold_scale_for(effect_measure: str) -> str | None:
    normalized = normalize_effect_measure(effect_measure)
    if normalized in {"risk_ratio", "odds_ratio", "risk_difference"}:
        return "risk_difference"
    if normalized in {"mean_difference", "standardized_mean_difference"}:
        return normalized
    return None


def no_effect_value_for(effect_measure: str) -> float | None:
    normalized = normalize_effect_measure(effect_measure)
    return NO_EFFECT_VALUES.get(normalized) if normalized else None


def build_effect_range_profile(
    *,
    grade_input: GRADEIndirectnessInput,
    threshold_profile: dict[str, Any],
    concern_groups: list[dict[str, Any]],
    use_weights: bool,
) -> dict[str, Any]:
    effect_measure = normalize_effect_measure(grade_input.setting.effect_measure)
    rows = [
        _row_range(
            effect_measure=effect_measure,
            effect_value=item.effect_value,
            observed_baseline=item.control_baseline_risk,
            threshold_profile=threshold_profile,
            data_row_id=item.data_row_id,
            study_id=item.study_id,
            weight_fraction=item.weight_fraction,
        )
        for item in grade_input.study_evidence
    ]
    by_id = {item["data_row_id"]: item for item in rows}
    numeric_warnings = [
        {
            "data_row_id": row["data_row_id"],
            "reason": row["unclassifiable_reason"],
            "observed_control_risk_reason": row[
                "observed_control_risk_reason"
            ],
        }
        for row in rows
        if row["numeric_status"] == "unclassifiable"
        or row["observed_control_risk_reason"] is not None
    ]
    return {
        "effect_measure": effect_measure or "unsupported",
        "no_effect_value": (
            NO_EFFECT_VALUES.get(effect_measure) if effect_measure else None
        ),
        "weights_used": use_weights,
        "numeric_warnings": numeric_warnings,
        "row_ranges": rows,
        "concern_concordance": [
            _group_concordance(
                group=group,
                rows_by_id=by_id,
                use_weights=use_weights,
            )
            for group in concern_groups
        ],
    }


def _row_range(
    *,
    effect_measure: str | None,
    effect_value: float | None,
    observed_baseline: float | None,
    threshold_profile: dict[str, Any],
    data_row_id: str,
    study_id: str,
    weight_fraction: float | None,
) -> dict[str, Any]:
    result = {
        "data_row_id": data_row_id,
        "study_id": study_id,
        "effect_value": effect_value,
        "weight_fraction": weight_fraction,
        "numeric_status": "not_applicable",
        "unclassifiable_reason": None,
        "target_scenario_effect": None,
        "target_scenario_range": "unclassified",
        "target_baseline_range_sensitivity": "unavailable",
        "target_baseline_evaluations": [],
        "observed_control_risk": observed_baseline,
        "observed_control_risk_effect": None,
        "observed_control_risk_range": "unclassified",
        "observed_control_risk_reason": None,
    }
    validation_error = _validate_effect_value(
        effect_measure=effect_measure,
        effect_value=effect_value,
    )
    if validation_error is not None:
        result["numeric_status"] = "unclassifiable"
        result["unclassifiable_reason"] = validation_error
        return result

    assert effect_measure is not None
    assert effect_value is not None
    value = float(effect_value)
    status = threshold_profile["status"]
    direction = threshold_profile.get("benefit_direction", "unclear")
    if status == "no_effect_only":
        result["numeric_status"] = "classified"
        result["target_scenario_range"] = _no_effect_side(
            value,
            no_effect=NO_EFFECT_VALUES[effect_measure],
            direction=direction,
        )
        return result
    if status != "generated":
        return result

    if effect_measure not in {"risk_ratio", "odds_ratio"}:
        result["numeric_status"] = "classified"
        result["target_scenario_effect"] = value
        result["target_scenario_range"] = _important_range(
            value, threshold_profile
        )
        return result

    baseline_plan = threshold_profile["baseline_risk_plan"]
    if baseline_plan["status"] != "model_scenario":
        result["numeric_status"] = "unclassifiable"
        result["unclassifiable_reason"] = "target_baseline_scenario_unavailable"
        return result

    low = float(baseline_plan["low"])
    high = float(baseline_plan["high"])
    midpoint = (low + high) / 2.0
    evaluations = []
    for label, baseline_risk in _baseline_evaluation_points(
        effect_measure=effect_measure,
        effect_value=value,
        low=low,
        high=high,
    ):
        try:
            absolute_effect = _absolute_risk_difference(
                effect_measure=effect_measure,
                effect_value=value,
                baseline_risk=baseline_risk,
            )
        except ValueError as exc:
            evaluations.append(
                {
                    "point": label,
                    "baseline_risk": baseline_risk,
                    "risk_difference": None,
                    "clinical_range": "unclassified",
                    "status": "unclassifiable",
                    "reason": str(exc),
                }
            )
        else:
            evaluations.append(
                {
                    "point": label,
                    "baseline_risk": baseline_risk,
                    "risk_difference": absolute_effect,
                    "clinical_range": _important_range(
                        absolute_effect, threshold_profile
                    ),
                    "status": "classified",
                    "reason": None,
                }
            )
    result["target_baseline_evaluations"] = evaluations
    if any(item["status"] != "classified" for item in evaluations):
        result["numeric_status"] = "unclassifiable"
        result["unclassifiable_reason"] = (
            "target_baseline_scenario_contains_impossible_risk"
        )
    else:
        midpoint_result = min(
            evaluations,
            key=lambda item: abs(item["baseline_risk"] - midpoint),
        )
        scenario_ranges = {
            item["clinical_range"] for item in evaluations
        }
        result["numeric_status"] = "classified"
        result["target_scenario_effect"] = midpoint_result["risk_difference"]
        result["target_scenario_range"] = midpoint_result["clinical_range"]
        result["target_baseline_range_sensitivity"] = (
            "stable" if len(scenario_ranges) == 1 else "sensitive"
        )

    if observed_baseline is not None:
        try:
            observed_value = _absolute_risk_difference(
                effect_measure=effect_measure,
                effect_value=value,
                baseline_risk=float(observed_baseline),
            )
        except ValueError as exc:
            result["observed_control_risk_reason"] = str(exc)
        else:
            result["observed_control_risk_effect"] = observed_value
            result["observed_control_risk_range"] = _important_range(
                observed_value, threshold_profile
            )
    return result


def _validate_effect_value(
    *, effect_measure: str | None, effect_value: float | None
) -> str | None:
    if effect_measure is None:
        return "unsupported_effect_measure"
    if effect_value is None:
        return "effect_value_unavailable"
    if isinstance(effect_value, bool):
        return "effect_value_must_be_numeric"
    value = float(effect_value)
    if not math.isfinite(value):
        return "effect_value_not_finite"
    if effect_measure in {"risk_ratio", "odds_ratio"} and value <= 0.0:
        return "ratio_effect_must_be_greater_than_zero"
    if effect_measure == "risk_difference" and not -1.0 <= value <= 1.0:
        return "risk_difference_must_be_between_minus_one_and_one"
    return None


def _baseline_evaluation_points(
    *, effect_measure: str, effect_value: float, low: float, high: float
) -> list[tuple[str, float]]:
    midpoint = (low + high) / 2.0
    candidates = [("low", low), ("midpoint", midpoint), ("high", high)]
    if effect_measure == "odds_ratio":
        critical = 1.0 / (math.sqrt(effect_value) + 1.0)
        if low <= critical <= high:
            candidates.append(("odds_ratio_extremum", critical))
    points: list[tuple[str, float]] = []
    for label, value in sorted(candidates, key=lambda item: item[1]):
        if any(
            math.isclose(value, existing, rel_tol=0.0, abs_tol=1e-12)
            for _, existing in points
        ):
            continue
        points.append((label, value))
    return points


def _absolute_risk_difference(
    *, effect_measure: str, effect_value: float, baseline_risk: float
) -> float:
    if not math.isfinite(effect_value) or effect_value <= 0.0:
        raise ValueError("ratio_effect_must_be_finite_and_greater_than_zero")
    if not math.isfinite(baseline_risk) or not 0.0 <= baseline_risk <= 1.0:
        raise ValueError("baseline_risk_must_be_a_probability")
    if effect_measure == "risk_ratio":
        treated_risk = baseline_risk * effect_value
        if treated_risk > 1.0 + 1e-12:
            raise ValueError("risk_ratio_implies_treated_risk_above_one")
        treated_risk = min(treated_risk, 1.0)
        return treated_risk - baseline_risk
    denominator = 1.0 - baseline_risk + (effect_value * baseline_risk)
    if denominator <= 0.0 or not math.isfinite(denominator):
        raise ValueError("odds_ratio_conversion_denominator_is_invalid")
    treated_risk = (effect_value * baseline_risk) / denominator
    if not math.isfinite(treated_risk) or not 0.0 <= treated_risk <= 1.0:
        raise ValueError("odds_ratio_implies_invalid_treated_risk")
    return treated_risk - baseline_risk


def _important_range(value: float, threshold_profile: dict[str, Any]) -> str:
    benefit = threshold_profile["important_benefit_threshold"]
    harm = threshold_profile["important_harm_threshold"]
    if threshold_profile["benefit_direction"] == "lower_is_better":
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


def _no_effect_side(value: float, *, no_effect: float, direction: str) -> str:
    if math.isclose(value, no_effect, rel_tol=0.0, abs_tol=1e-12):
        return "no_effect"
    if direction == "unclear":
        return "unclassified"
    benefit = value < no_effect if direction == "lower_is_better" else value > no_effect
    return "benefit_side" if benefit else "harm_side"


def _group_concordance(
    *,
    group: dict[str, Any],
    rows_by_id: dict[str, dict[str, Any]],
    use_weights: bool,
) -> dict[str, Any]:
    less = [rows_by_id[row_id] for row_id in group["less_direct_data_row_ids"]]
    more = [rows_by_id[row_id] for row_id in group["more_direct_data_row_ids"]]
    less_ranges = _usable_ranges(less)
    more_ranges = _usable_ranges(more)
    if not less_ranges or not more_ranges:
        concordance = "unavailable"
    elif less_ranges == more_ranges and len(less_ranges) == 1:
        concordance = "same_clinical_range"
    elif less_ranges.isdisjoint(more_ranges):
        concordance = "different_clinical_ranges"
    else:
        concordance = "mixed_or_overlapping_ranges"
    sensitivities = {
        row["target_baseline_range_sensitivity"]
        for row in [*less, *more]
        if row["target_baseline_range_sensitivity"] != "unavailable"
    }
    return {
        "group_id": group["group_id"],
        "less_direct_ranges": sorted(less_ranges),
        "more_direct_ranges": sorted(more_ranges),
        "range_concordance": concordance,
        "less_direct_count_by_range": _count_by_range(less),
        "more_direct_count_by_range": _count_by_range(more),
        "less_direct_weight_by_range": _weight_by_range(
            less, use_weights=use_weights
        ),
        "more_direct_weight_by_range": _weight_by_range(
            more, use_weights=use_weights
        ),
        "less_direct_weight": _weight(less, use_weights=use_weights),
        "more_direct_weight": _weight(more, use_weights=use_weights),
        "target_baseline_sensitivity": (
            "sensitive"
            if "sensitive" in sensitivities
            else ("stable" if sensitivities else "unavailable")
        ),
    }


def _usable_ranges(rows: list[dict[str, Any]]) -> set[str]:
    return {
        row["target_scenario_range"]
        for row in rows
        if row["target_scenario_range"] not in {"unclassified", "no_effect"}
    }


def _count_by_range(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        clinical_range = row["target_scenario_range"]
        counts[clinical_range] = counts.get(clinical_range, 0) + 1
    return dict(sorted(counts.items()))


def _weight_by_range(
    rows: list[dict[str, Any]], *, use_weights: bool
) -> dict[str, float] | None:
    if not use_weights:
        return None
    weights: dict[str, float] = {}
    for row in rows:
        clinical_range = row["target_scenario_range"]
        weights[clinical_range] = weights.get(clinical_range, 0.0) + float(
            row["weight_fraction"]
        )
    return {
        key: round(value, 6) for key, value in sorted(weights.items())
    }


def _weight(rows: list[dict[str, Any]], *, use_weights: bool) -> float | None:
    if not rows or not use_weights:
        return None
    return round(sum(float(row["weight_fraction"]) for row in rows), 6)
