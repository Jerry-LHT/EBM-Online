"""Strict result-blind policy contract for GRADE inconsistency."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


BENEFIT_DIRECTIONS = {"lower", "higher", "unknown"}
THRESHOLD_BASES = {"llm_contextual", "no_effect_only"}
MODIFIER_DOMAINS = {
    "population",
    "intervention",
    "comparator",
    "outcome",
    "timepoint",
    "methodology",
}
PLAUSIBILITY_VALUES = {"credible", "possible", "not_credible"}
HYPOTHESIS_BASES = {"workflow_prespecified", "result_blind_generated"}


@dataclass(frozen=True)
class EffectRangePolicy:
    no_effect_value: float
    benefit_direction: str
    important_benefit_boundary: float | None
    important_harm_boundary: float | None
    threshold_basis: str
    rationale: str


@dataclass(frozen=True)
class PlausibleEffectModifier:
    domain: str
    factor: str
    categories: list[str]
    plausibility: str
    hypothesis_basis: str
    rationale: str


@dataclass(frozen=True)
class InconsistencyPolicy:
    effect_range_policy: EffectRangePolicy
    plausible_effect_modifiers: list[PlausibleEffectModifier]
    limitations: list[str]
    rationale: str


def policy_schema() -> dict[str, Any]:
    nullable_number = {"type": ["number", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "assessment_status",
            "effect_range_policy",
            "plausible_effect_modifiers",
            "limitations",
            "rationale",
        ],
        "properties": {
            "assessment_status": {"type": "string", "enum": ["completed"]},
            "effect_range_policy": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "no_effect_value",
                    "benefit_direction",
                    "important_benefit_boundary",
                    "important_harm_boundary",
                    "threshold_basis",
                    "rationale",
                ],
                "properties": {
                    "no_effect_value": {"type": "number"},
                    "benefit_direction": {
                        "type": "string",
                        "enum": sorted(BENEFIT_DIRECTIONS),
                    },
                    "important_benefit_boundary": nullable_number,
                    "important_harm_boundary": nullable_number,
                    "threshold_basis": {
                        "type": "string",
                        "enum": sorted(THRESHOLD_BASES),
                    },
                    "rationale": {"type": "string", "minLength": 1},
                },
            },
            "plausible_effect_modifiers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "domain",
                        "factor",
                        "categories",
                        "plausibility",
                        "hypothesis_basis",
                        "rationale",
                    ],
                    "properties": {
                        "domain": {
                            "type": "string",
                            "enum": sorted(MODIFIER_DOMAINS),
                        },
                        "factor": {"type": "string", "minLength": 1},
                        "categories": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                        "plausibility": {
                            "type": "string",
                            "enum": sorted(PLAUSIBILITY_VALUES),
                        },
                        "hypothesis_basis": {
                            "type": "string",
                            "enum": sorted(HYPOTHESIS_BASES),
                        },
                        "rationale": {"type": "string", "minLength": 1},
                    },
                },
            },
            "limitations": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "rationale": {"type": "string", "minLength": 1},
        },
    }


def parse_policy(
    payload: dict[str, Any],
    *,
    expected_no_effect: float,
) -> InconsistencyPolicy:
    _require_keys(
        payload,
        {
            "assessment_status",
            "effect_range_policy",
            "plausible_effect_modifiers",
            "limitations",
            "rationale",
        },
        "policy",
    )
    if payload["assessment_status"] != "completed":
        raise ValueError("assessment_status must be completed")
    raw_range = _object(payload["effect_range_policy"], "effect_range_policy")
    _require_keys(
        raw_range,
        {
            "no_effect_value",
            "benefit_direction",
            "important_benefit_boundary",
            "important_harm_boundary",
            "threshold_basis",
            "rationale",
        },
        "effect_range_policy",
    )
    no_effect = _number(raw_range["no_effect_value"], "no_effect_value")
    if not math.isclose(no_effect, expected_no_effect, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(
            f"no_effect_value must be {expected_no_effect:g} for this effect measure"
        )
    direction = _enum(
        raw_range["benefit_direction"], BENEFIT_DIRECTIONS, "benefit_direction"
    )
    benefit = _optional_number(
        raw_range["important_benefit_boundary"], "important_benefit_boundary"
    )
    harm = _optional_number(
        raw_range["important_harm_boundary"], "important_harm_boundary"
    )
    basis = _enum(raw_range["threshold_basis"], THRESHOLD_BASES, "threshold_basis")
    if (benefit is None) != (harm is None):
        raise ValueError("important benefit and harm boundaries must be supplied together")
    if benefit is None:
        if direction != "unknown" or basis != "no_effect_only":
            raise ValueError(
                "missing clinical boundaries require unknown direction and no_effect_only basis"
            )
    else:
        if direction == "unknown" or basis != "llm_contextual":
            raise ValueError(
                "clinical boundaries require a known direction and llm_contextual basis"
            )
        ordered = (
            benefit < no_effect < harm
            if direction == "lower"
            else harm < no_effect < benefit
        )
        if not ordered:
            raise ValueError("clinical boundaries are inconsistent with benefit_direction")
    range_policy = EffectRangePolicy(
        no_effect_value=no_effect,
        benefit_direction=direction,
        important_benefit_boundary=benefit,
        important_harm_boundary=harm,
        threshold_basis=basis,
        rationale=_text(raw_range["rationale"], "effect_range_policy.rationale"),
    )

    raw_modifiers = _list(payload["plausible_effect_modifiers"], "plausible_effect_modifiers")
    modifiers: list[PlausibleEffectModifier] = []
    for index, raw in enumerate(raw_modifiers):
        item = _object(raw, f"plausible_effect_modifiers[{index}]")
        _require_keys(
            item,
            {
                "domain",
                "factor",
                "categories",
                "plausibility",
                "hypothesis_basis",
                "rationale",
            },
            f"plausible_effect_modifiers[{index}]",
        )
        categories = [
            _text(value, f"plausible_effect_modifiers[{index}].categories")
            for value in _list(item["categories"], "categories")
        ]
        if len(set(categories)) != len(categories):
            raise ValueError("effect modifier categories must be unique")
        modifiers.append(
            PlausibleEffectModifier(
                domain=_enum(item["domain"], MODIFIER_DOMAINS, "domain"),
                factor=_text(item["factor"], "factor"),
                categories=categories,
                plausibility=_enum(
                    item["plausibility"], PLAUSIBILITY_VALUES, "plausibility"
                ),
                hypothesis_basis=_enum(
                    item["hypothesis_basis"], HYPOTHESIS_BASES, "hypothesis_basis"
                ),
                rationale=_text(item["rationale"], "modifier rationale"),
            )
        )
    limitations = [
        _text(value, "limitation")
        for value in _list(payload["limitations"], "limitations")
    ]
    return InconsistencyPolicy(
        effect_range_policy=range_policy,
        plausible_effect_modifiers=modifiers,
        limitations=limitations,
        rationale=_text(payload["rationale"], "policy rationale"),
    )


def no_effect_value(effect_measure: str) -> float:
    normalized = " ".join(effect_measure.casefold().replace("_", " ").split())
    if normalized in {"rr", "or", "hr", "irr", "rom"}:
        return 1.0
    ratio_markers = (
        "ratio",
        "odds ratio",
        "risk ratio",
        "rate ratio",
        "hazard ratio",
        "relative risk",
    )
    return 1.0 if any(marker in normalized for marker in ratio_markers) else 0.0


def _require_keys(payload: dict[str, Any], expected: set[str], context: str) -> None:
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


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _optional_number(value: Any, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _enum(value: Any, allowed: set[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()
