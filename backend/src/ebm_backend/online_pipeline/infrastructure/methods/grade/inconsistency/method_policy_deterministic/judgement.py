"""Strict contract for the bounded GRADE inconsistency judge."""

from __future__ import annotations

from typing import Any


SEVERITIES = {"none", "serious", "very_serious"}
DECISION_BASES = {
    "inconsistency_explained",
    "likely_imprecision",
    "meaningful_unexplained_inconsistency",
    "no_meaningful_inconsistency",
}


def judgement_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "assessment_status",
            "severity",
            "target_range",
            "pooled_ci_ranges",
            "distribution_is_meaningful",
            "inconsistency_explained",
            "effect_modifier_factor",
            "subgroup_test_id",
            "imprecision_overlap_risk",
            "decision_basis",
            "supporting_evidence",
        ],
        "properties": {
            "assessment_status": {"type": "string", "enum": ["completed"]},
            "severity": {"type": "string", "enum": sorted(SEVERITIES)},
            "target_range": {"type": ["string", "null"]},
            "pooled_ci_ranges": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "distribution_is_meaningful": {"type": "boolean"},
            "inconsistency_explained": {"type": "boolean"},
            "effect_modifier_factor": {"type": ["string", "null"]},
            "subgroup_test_id": {"type": ["string", "null"]},
            "imprecision_overlap_risk": {"type": "boolean"},
            "decision_basis": {
                "type": "string",
                "enum": sorted(DECISION_BASES),
            },
            "supporting_evidence": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["range", "data_row_ids"],
                    "properties": {
                        "range": {"type": "string", "minLength": 1},
                        "data_row_ids": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        },
    }


def parse_judgement(
    payload: dict[str, Any],
    *,
    evidence_profile: dict[str, Any],
) -> dict[str, Any]:
    expected = {
        "assessment_status",
        "severity",
        "target_range",
        "pooled_ci_ranges",
        "distribution_is_meaningful",
        "inconsistency_explained",
        "effect_modifier_factor",
        "subgroup_test_id",
        "imprecision_overlap_risk",
        "decision_basis",
        "supporting_evidence",
    }
    _require_keys(payload, expected, "judgement")
    if payload["assessment_status"] != "completed":
        raise ValueError("assessment_status must be completed")
    severity = _enum(payload["severity"], SEVERITIES, "severity")
    target_range = payload["target_range"]
    if target_range is not None and not isinstance(target_range, str):
        raise ValueError("target_range must be a string or null")
    if target_range != evidence_profile["target_range"]:
        raise ValueError("judge target_range must match the frozen evidence profile")
    pooled_ci_ranges = payload["pooled_ci_ranges"]
    expected_ci_ranges = evidence_profile["pooled_estimate"]["ci_ranges"]
    if not isinstance(pooled_ci_ranges, list) or any(
        not isinstance(item, str) for item in pooled_ci_ranges
    ):
        raise ValueError("pooled_ci_ranges must be an array of strings")
    if pooled_ci_ranges != expected_ci_ranges:
        raise ValueError(
            "judge pooled_ci_ranges must match the deterministic evidence profile"
        )
    meaningful = _boolean(
        payload["distribution_is_meaningful"], "distribution_is_meaningful"
    )
    explained = _boolean(
        payload["inconsistency_explained"], "inconsistency_explained"
    )
    imprecision_overlap = _boolean(
        payload["imprecision_overlap_risk"], "imprecision_overlap_risk"
    )
    decision_basis = _enum(
        payload["decision_basis"], DECISION_BASES, "decision_basis"
    )
    factor = _optional_text(payload["effect_modifier_factor"], "effect_modifier_factor")
    test_id = _optional_text(payload["subgroup_test_id"], "subgroup_test_id")
    subgroup_tests = {
        item["test_id"]: item for item in evidence_profile["subgroup_evidence"]
    }
    policy_factors = {
        item["factor"] for item in evidence_profile["result_blind_effect_modifiers"]
    }
    if explained:
        if factor not in policy_factors or test_id not in subgroup_tests:
            raise ValueError(
                "explained inconsistency must reference a frozen modifier and subgroup test"
            )
        if severity != "none":
            raise ValueError("explained inconsistency cannot be downgraded")
        if decision_basis != "inconsistency_explained":
            raise ValueError(
                "explained inconsistency requires inconsistency_explained decision_basis"
            )
    elif factor is not None or test_id is not None:
        raise ValueError(
            "unexplained inconsistency must not reference an explanatory modifier or test"
        )
    elif decision_basis == "inconsistency_explained":
        raise ValueError(
            "inconsistency_explained decision_basis requires explanatory evidence"
        )
    if severity == "serious" and evidence_profile["threshold_span"] < 1:
        raise ValueError("serious inconsistency requires effects across a threshold")
    if severity == "very_serious" and evidence_profile["threshold_span"] < 2:
        raise ValueError(
            "very serious inconsistency requires effects separated by multiple thresholds"
        )
    if severity != "none" and not meaningful:
        raise ValueError("downgrading requires a meaningful effect distribution")
    if severity != "none" and decision_basis != "meaningful_unexplained_inconsistency":
        raise ValueError(
            "downgrading requires meaningful_unexplained_inconsistency decision_basis"
        )
    if explained and not meaningful:
        raise ValueError("explained inconsistency requires a meaningful distribution")
    if severity == "none" and not explained:
        expected_bases = {"no_meaningful_inconsistency"}
        if imprecision_overlap:
            expected_bases.add("likely_imprecision")
        if decision_basis not in expected_bases:
            raise ValueError("non-downgraded judgement has an incompatible decision_basis")
        if meaningful:
            raise ValueError(
                "a meaningful unexplained distribution cannot be rated not serious"
            )
    if decision_basis == "likely_imprecision" and not imprecision_overlap:
        raise ValueError("likely_imprecision requires imprecision_overlap_risk")

    effects_by_id = {
        item["data_row_id"]: item for item in evidence_profile["study_effects"]
    }
    raw_evidence = payload["supporting_evidence"]
    if not isinstance(raw_evidence, list) or not raw_evidence:
        raise ValueError("supporting_evidence must be a non-empty array")
    seen_ids: set[str] = set()
    supporting_evidence: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_evidence):
        if not isinstance(raw, dict):
            raise ValueError(f"supporting_evidence[{index}] must be an object")
        _require_keys(raw, {"range", "data_row_ids"}, f"supporting_evidence[{index}]")
        range_name = _text(raw["range"], "supporting range")
        row_ids = raw["data_row_ids"]
        if not isinstance(row_ids, list) or not row_ids:
            raise ValueError("supporting data_row_ids must be a non-empty array")
        checked_ids: list[str] = []
        for value in row_ids:
            row_id = _text(value, "supporting data_row_id")
            if row_id in seen_ids:
                raise ValueError("supporting DataRow references must be unique")
            effect = effects_by_id.get(row_id)
            if effect is None:
                raise ValueError(f"unknown supporting DataRow ID: {row_id}")
            if effect["range"] != range_name:
                raise ValueError(
                    f"supporting DataRow {row_id} does not belong to range {range_name}"
                )
            seen_ids.add(row_id)
            checked_ids.append(row_id)
        supporting_evidence.append(
            {"range": range_name, "data_row_ids": checked_ids}
        )
    return {
        "assessment_status": "completed",
        "severity": severity,
        "target_range": target_range,
        "pooled_ci_ranges": list(pooled_ci_ranges),
        "distribution_is_meaningful": meaningful,
        "inconsistency_explained": explained,
        "effect_modifier_factor": factor,
        "subgroup_test_id": test_id,
        "imprecision_overlap_risk": imprecision_overlap,
        "decision_basis": decision_basis,
        "supporting_evidence": supporting_evidence,
    }


def _require_keys(payload: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{context} keys must exactly match schema; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _enum(value: Any, allowed: set[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()
