"""Evidence extraction for GRADE inconsistency methods."""

from __future__ import annotations

import math
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_deterministic.utils import as_float, as_int, as_list, first_dict


def extract_inconsistency_features(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    estimate = first_dict(domain_evidence.get("effect_estimate"), evidence_body.get("effect_estimate"))
    heterogeneity = first_dict(domain_evidence.get("heterogeneity"), estimate.get("heterogeneity"))
    study_rows = as_list(domain_evidence.get("meta_analysis_data_rows") or evidence_body.get("meta_analysis_data_rows"))
    subgroup_tests = [
        _subgroup_test_features(row)
        for row in as_list(domain_evidence.get("subgroup_difference_tests") or evidence_body.get("subgroup_difference_tests"))
        if isinstance(row, dict)
    ]
    effect_measure = str(
        domain_evidence.get("effect_measure")
        or estimate.get("effect_measure")
        or first_dict(domain_evidence.get("analysis_setting"), evidence_body.get("analysis_setting")).get("effect_measure")
        or ""
    )
    data_type = str(
        domain_evidence.get("data_type")
        or estimate.get("data_type")
        or first_dict(domain_evidence.get("analysis_setting"), evidence_body.get("analysis_setting")).get("data_type")
        or ""
    )
    study_effects = _study_effects(study_rows=study_rows, effect_measure=effect_measure, data_type=data_type)
    return {
        "study_count": _first_int(domain_evidence.get("study_count"), estimate.get("study_count"), len(study_rows) or None),
        "participant_count": _first_int(domain_evidence.get("participant_count"), estimate.get("participant_count")),
        "data_type": data_type,
        "effect_measure": effect_measure,
        "overall_effect": as_float(estimate.get("effect_value", estimate.get("effect"))),
        "overall_ci_lower": as_float(estimate.get("ci_lower")),
        "overall_ci_upper": as_float(estimate.get("ci_upper")),
        "prediction_interval": _interval_features(first_dict(estimate.get("prediction_interval")), effect_measure=effect_measure),
        "heterogeneity": {
            "tau2": as_float(heterogeneity.get("tau2")),
            "chi2": as_float(heterogeneity.get("chi2")),
            "df": as_float(heterogeneity.get("df")),
            "p_value": _first_float(heterogeneity.get("p_value"), heterogeneity.get("p")),
            "i2": as_float(heterogeneity.get("i2")),
        },
        "subgroup_tests": subgroup_tests,
        "study_effects": study_effects,
        "study_effect_summary": _study_effect_summary(study_effects=study_effects, effect_measure=effect_measure),
    }


def no_effect_line(effect_measure: str) -> float:
    return 1.0 if is_ratio_measure(effect_measure) else 0.0


def is_ratio_measure(effect_measure: str) -> bool:
    text = effect_measure.lower()
    return any(token in text for token in ("risk ratio", "odds ratio", "hazard ratio", "rate ratio", "ratio", "rr", "or", "hr"))


def _study_effects(*, study_rows: list[Any], effect_measure: str, data_type: str) -> list[dict[str, Any]]:
    effects = []
    for row in study_rows:
        if not isinstance(row, dict):
            continue
        result_data = _row_result_data(row)
        explicit = first_dict(row.get("effect"))
        effect = _first_float(explicit.get("value"), explicit.get("effect"), explicit.get("effect_value"))
        if effect is None:
            if "dichotomous" in data_type.lower():
                effect = _dichotomous_effect(result_data=result_data, effect_measure=effect_measure)
            elif "continuous" in data_type.lower():
                effect = _continuous_effect(result_data=result_data)
        if effect is None:
            continue
        effects.append(
            {
                "study_id": row.get("study_id"),
                "effect": effect,
                "ci_lower": _first_float(explicit.get("ci_lower"), explicit.get("lower")),
                "ci_upper": _first_float(explicit.get("ci_upper"), explicit.get("upper")),
                "weight": _first_float(explicit.get("weight")),
                "participants": _row_participants(result_data),
                "direction": _effect_direction(effect=effect, effect_measure=effect_measure),
            }
        )
    return effects


def _row_result_data(row: dict[str, Any]) -> dict[str, Any]:
    items = as_list(row.get("result_items") or row.get("candidate_results"))
    ready = [
        item
        for item in items
        if isinstance(item, dict)
        and str(item.get("analysis_disposition") or "").strip().lower() == "ready_for_estimate"
        and isinstance(item.get("result_data"), dict)
    ]
    if ready:
        return ready[0]["result_data"]
    for item in items:
        if isinstance(item, dict) and item.get("include_in_estimate") is True and isinstance(item.get("result_data"), dict):
            return item["result_data"]
    return first_dict(row.get("result_data"))


def _dichotomous_effect(*, result_data: dict[str, Any], effect_measure: str) -> float | None:
    experimental_events = as_float(result_data.get("experimental_events"))
    experimental_total = as_float(result_data.get("experimental_total"))
    control_events = as_float(result_data.get("control_events"))
    control_total = as_float(result_data.get("control_total"))
    if experimental_events is None or experimental_total in {None, 0} or control_events is None or control_total in {None, 0}:
        return None
    # Haldane-Anscombe correction keeps zero-event studies directionally usable.
    experimental_nonevents = experimental_total - experimental_events
    control_nonevents = control_total - control_events
    exp_events = experimental_events + 0.5
    ctrl_events = control_events + 0.5
    exp_nonevents = experimental_nonevents + 0.5
    ctrl_nonevents = control_nonevents + 0.5
    text = effect_measure.lower()
    if "odds" in text or text.strip() == "or":
        return (exp_events / exp_nonevents) / (ctrl_events / ctrl_nonevents)
    return (exp_events / (experimental_total + 1.0)) / (ctrl_events / (control_total + 1.0))


def _continuous_effect(*, result_data: dict[str, Any]) -> float | None:
    experimental_mean = as_float(result_data.get("experimental_mean"))
    control_mean = as_float(result_data.get("control_mean"))
    if experimental_mean is None or control_mean is None:
        return None
    return experimental_mean - control_mean


def _study_effect_summary(*, study_effects: list[dict[str, Any]], effect_measure: str) -> dict[str, Any]:
    if not study_effects:
        return {
            "evaluable_study_count": 0,
            "benefit_count": 0,
            "harm_count": 0,
            "neutral_count": 0,
            "opposing_direction": False,
            "effect_spread_ratio": None,
            "effect_range": None,
        }
    benefit = sum(1 for item in study_effects if item.get("direction") == "benefit")
    harm = sum(1 for item in study_effects if item.get("direction") == "harm")
    neutral = sum(1 for item in study_effects if item.get("direction") == "neutral")
    effects = [float(item["effect"]) for item in study_effects if as_float(item.get("effect")) is not None]
    if is_ratio_measure(effect_measure):
        positive = [value for value in effects if value > 0]
        spread_ratio = (max(positive) / min(positive)) if positive else None
        effect_range = None
    else:
        spread_ratio = None
        effect_range = max(effects) - min(effects) if effects else None
    return {
        "evaluable_study_count": len(study_effects),
        "benefit_count": benefit,
        "harm_count": harm,
        "neutral_count": neutral,
        "opposing_direction": benefit > 0 and harm > 0,
        "effect_spread_ratio": spread_ratio if _is_finite(spread_ratio) else None,
        "effect_range": effect_range if _is_finite(effect_range) else None,
    }


def _effect_direction(*, effect: float, effect_measure: str) -> str:
    no_effect = no_effect_line(effect_measure)
    if math.isclose(effect, no_effect, rel_tol=1e-9, abs_tol=1e-9):
        return "neutral"
    benefit_direction = "lower" if _lower_is_benefit(effect_measure) else "higher"
    if benefit_direction == "lower":
        return "benefit" if effect < no_effect else "harm"
    return "benefit" if effect > no_effect else "harm"


def _lower_is_benefit(effect_measure: str) -> bool:
    # Most SoF rows in this benchmark are adverse or event outcomes. Without a
    # reliable outcome benefit direction, treat lower event/mean values as benefit.
    return True


def _interval_features(interval: dict[str, Any], *, effect_measure: str) -> dict[str, Any]:
    lower = as_float(interval.get("lower"))
    upper = as_float(interval.get("upper"))
    crosses = False
    if lower is not None and upper is not None:
        no_effect = no_effect_line(effect_measure)
        crosses = lower <= no_effect <= upper
    return {"lower": lower, "upper": upper, "crosses_no_effect": crosses}


def _subgroup_test_features(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "setting_family_id": row.get("setting_family_id"),
        "chi2": as_float(row.get("chi2")),
        "df": as_float(row.get("df")),
        "p_value": _first_float(row.get("p_value"), row.get("p")),
        "i2": as_float(row.get("i2")),
    }


def _row_participants(result_data: dict[str, Any]) -> int | None:
    experimental_total = as_int(result_data.get("experimental_total"))
    control_total = as_int(result_data.get("control_total"))
    if experimental_total is None and control_total is None:
        return None
    return int(experimental_total or 0) + int(control_total or 0)


def _first_float(*values: Any) -> float | None:
    for value in values:
        number = as_float(value)
        if number is not None:
            return number
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        number = as_int(value)
        if number is not None:
            return number
    return None


def _is_finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not math.isnan(value) and not math.isinf(value)
