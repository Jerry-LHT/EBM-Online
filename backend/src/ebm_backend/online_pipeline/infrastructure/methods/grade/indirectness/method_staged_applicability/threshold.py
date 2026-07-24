"""Conditional result-blind clinical-threshold generation contract."""

from __future__ import annotations

import math
from typing import Any

from ebm_backend.online_pipeline.domain.grade import GRADEIndirectnessInput
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.effect_ranges import (
    no_effect_value_for,
    normalize_effect_measure,
    threshold_scale_for,
)


THRESHOLD_STATUSES = {"generated", "no_effect_only", "unavailable"}
BENEFIT_DIRECTIONS = {"lower_is_better", "higher_is_better", "unclear"}
THRESHOLD_BASES = {
    "input_explicit",
    "model_expert_assumption",
    "no_effect_only",
    "unavailable",
}
BASELINE_STATUSES = {"not_required", "model_scenario", "unavailable"}
CONFIDENCES = {"low", "moderate", "high"}
NON_NUMERIC_FACETS = {"construct", "patient_importance", "surrogate"}
NON_NUMERIC_MECHANISMS = {"surrogate_or_proxy", "comparison_pathway"}


def threshold_requirement(
    *,
    grade_input: GRADEIndirectnessInput,
    concern_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    effect_measure = normalize_effect_measure(grade_input.setting.effect_measure)
    scale = threshold_scale_for(grade_input.setting.effect_measure)
    analysis_no_effect = no_effect_value_for(grade_input.setting.effect_measure)
    no_effect = 0.0 if scale in {
        "risk_difference",
        "mean_difference",
        "standardized_mean_difference",
    } else analysis_no_effect
    if not concern_groups:
        return _not_required("no_eligible_applicability_concern", effect_measure, scale, no_effect)
    if len(grade_input.study_evidence) < 2:
        return _not_required("single_study_evidence_body", effect_measure, scale, no_effect)
    if effect_measure is None or scale is None:
        return _not_required("unsupported_effect_measure", effect_measure, scale, no_effect)

    numeric_groups = [
        group
        for group in concern_groups
        if group["domain"] != "direct_comparison"
        and group["facet"] not in NON_NUMERIC_FACETS
        and group["mechanism"] not in NON_NUMERIC_MECHANISMS
    ]
    baseline_groups = [
        group
        for group in numeric_groups
        if group["domain"] == "population"
        and group["mechanism"]
        in {"baseline_risk", "effect_modification_and_baseline_risk"}
        and effect_measure in {"risk_ratio", "odds_ratio"}
    ]
    comparative_groups = [
        group
        for group in numeric_groups
        if group["less_direct_data_row_ids"] and group["more_direct_data_row_ids"]
    ]
    selected = {group["group_id"]: group for group in [*baseline_groups, *comparative_groups]}
    if not selected:
        reason = (
            "non_numeric_applicability_concern"
            if numeric_groups == []
            else "no_more_direct_and_less_direct_comparison"
        )
        return _not_required(reason, effect_measure, scale, no_effect)
    if not all(item.effect_value is not None for item in grade_input.study_evidence):
        return _not_required("study_effects_unavailable", effect_measure, scale, no_effect)
    purposes = []
    if comparative_groups:
        purposes.append("effect_range_concordance")
    if baseline_groups:
        purposes.append("baseline_risk_sensitivity")
    return {
        "needed": True,
        "reason": "quantitative_applicability_assessment_is_informative",
        "purposes": purposes,
        "candidate_group_ids": list(selected),
        "effect_measure": effect_measure,
        "threshold_scale": scale,
        "no_effect_value": no_effect,
        "requires_baseline_scenario": effect_measure in {"risk_ratio", "odds_ratio"},
    }


def not_needed_threshold(requirement: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "not_needed",
        "effect_scale": requirement["threshold_scale"],
        "unit": None,
        "benefit_direction": "unclear",
        "important_benefit_threshold": None,
        "important_harm_threshold": None,
        "basis": "not_needed",
        "rationale": requirement["reason"],
        "applicability": "not_needed_for_this_evidence_body",
        "confidence": "not_applicable",
        "baseline_risk_plan": {
            "status": "not_required",
            "low": None,
            "high": None,
            "basis": "not_required",
            "rationale": "No target baseline-risk scenario is required.",
        },
    }


def threshold_schema(*, effect_scale: str) -> dict[str, Any]:
    nullable_number = {"type": ["number", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "status",
            "effect_scale",
            "unit",
            "benefit_direction",
            "important_benefit_threshold",
            "important_harm_threshold",
            "basis",
            "rationale",
            "applicability",
            "confidence",
            "baseline_risk_plan",
        ],
        "properties": {
            "status": {"type": "string", "enum": sorted(THRESHOLD_STATUSES)},
            "effect_scale": {"type": "string", "enum": [effect_scale]},
            "unit": {"type": ["string", "null"]},
            "benefit_direction": {
                "type": "string",
                "enum": sorted(BENEFIT_DIRECTIONS),
            },
            "important_benefit_threshold": nullable_number,
            "important_harm_threshold": nullable_number,
            "basis": {"type": "string", "enum": sorted(THRESHOLD_BASES)},
            "rationale": {"type": "string", "minLength": 1},
            "applicability": {"type": "string", "minLength": 1},
            "confidence": {"type": "string", "enum": sorted(CONFIDENCES)},
            "baseline_risk_plan": {
                "type": "object",
                "additionalProperties": False,
                "required": ["status", "low", "high", "basis", "rationale"],
                "properties": {
                    "status": {"type": "string", "enum": sorted(BASELINE_STATUSES)},
                    "low": nullable_number,
                    "high": nullable_number,
                    "basis": {"type": "string", "minLength": 1},
                    "rationale": {"type": "string", "minLength": 1},
                },
            },
        },
    }


def parse_threshold(
    payload: dict[str, Any], *, requirement: dict[str, Any]
) -> dict[str, Any]:
    expected = {
        "status",
        "effect_scale",
        "unit",
        "benefit_direction",
        "important_benefit_threshold",
        "important_harm_threshold",
        "basis",
        "rationale",
        "applicability",
        "confidence",
        "baseline_risk_plan",
    }
    _require_keys(payload, expected, "threshold")
    status = _enum(payload["status"], THRESHOLD_STATUSES, "status")
    effect_scale = _text(payload["effect_scale"], "effect_scale")
    if effect_scale != requirement["threshold_scale"]:
        raise ValueError("threshold effect_scale must match the engineered scale")
    direction = _enum(
        payload["benefit_direction"], BENEFIT_DIRECTIONS, "benefit_direction"
    )
    benefit = _number_or_none(
        payload["important_benefit_threshold"], "important_benefit_threshold"
    )
    harm = _number_or_none(
        payload["important_harm_threshold"], "important_harm_threshold"
    )
    basis = _enum(payload["basis"], THRESHOLD_BASES, "basis")
    baseline = _parse_baseline(payload["baseline_risk_plan"])
    no_effect = requirement["no_effect_value"]
    if status == "generated":
        if direction == "unclear" or benefit is None or harm is None:
            raise ValueError("generated thresholds require direction and both boundaries")
        if basis not in {"input_explicit", "model_expert_assumption"}:
            raise ValueError("generated thresholds require an explicit or expert basis")
        if direction == "lower_is_better" and not (benefit < no_effect < harm):
            raise ValueError("lower-is-better threshold ordering is invalid")
        if direction == "higher_is_better" and not (harm < no_effect < benefit):
            raise ValueError("higher-is-better threshold ordering is invalid")
        if effect_scale == "risk_difference" and not (
            -1.0 <= benefit <= 1.0 and -1.0 <= harm <= 1.0
        ):
            raise ValueError("risk-difference thresholds must be between -1 and 1")
        if requirement["requires_baseline_scenario"] and baseline["status"] != "model_scenario":
            raise ValueError("ratio measures require a target baseline-risk scenario")
    elif benefit is not None or harm is not None:
        raise ValueError("non-generated threshold output must not contain boundaries")
    elif status == "no_effect_only" and basis != "no_effect_only":
        raise ValueError("no_effect_only status requires no_effect_only basis")
    elif status == "unavailable" and basis != "unavailable":
        raise ValueError("unavailable status requires unavailable basis")
    if not requirement["requires_baseline_scenario"] and baseline["status"] == "model_scenario":
        raise ValueError("this effect measure does not require a baseline-risk scenario")
    return {
        "status": status,
        "effect_scale": effect_scale,
        "unit": _optional_text(payload["unit"], "unit"),
        "benefit_direction": direction,
        "important_benefit_threshold": benefit,
        "important_harm_threshold": harm,
        "basis": basis,
        "rationale": _text(payload["rationale"], "rationale"),
        "applicability": _text(payload["applicability"], "applicability"),
        "confidence": _enum(payload["confidence"], CONFIDENCES, "confidence"),
        "baseline_risk_plan": baseline,
    }


def _parse_baseline(raw: Any) -> dict[str, Any]:
    item = _object(raw, "baseline_risk_plan")
    _require_keys(item, {"status", "low", "high", "basis", "rationale"}, "baseline_risk_plan")
    status = _enum(item["status"], BASELINE_STATUSES, "baseline_risk_plan.status")
    low = _number_or_none(item["low"], "baseline_risk_plan.low")
    high = _number_or_none(item["high"], "baseline_risk_plan.high")
    if status == "model_scenario":
        if low is None or high is None or not (0.0 <= low <= high <= 1.0):
            raise ValueError("model baseline-risk scenario must be a probability range")
    elif low is not None or high is not None:
        raise ValueError("non-scenario baseline plan must not contain values")
    return {
        "status": status,
        "low": low,
        "high": high,
        "basis": _text(item["basis"], "baseline_risk_plan.basis"),
        "rationale": _text(item["rationale"], "baseline_risk_plan.rationale"),
    }


def _not_required(
    reason: str,
    effect_measure: str | None,
    scale: str | None,
    no_effect: float | None,
) -> dict[str, Any]:
    return {
        "needed": False,
        "reason": reason,
        "purposes": [],
        "candidate_group_ids": [],
        "effect_measure": effect_measure or "unsupported",
        "threshold_scale": scale,
        "no_effect_value": no_effect,
        "requires_baseline_scenario": False,
    }


def _require_keys(payload: dict[str, Any], expected: set[str], context: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"{context} must be an object")
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{context} keys must exactly match schema; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _enum(value: Any, allowed: set[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _number_or_none(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number or null")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number
