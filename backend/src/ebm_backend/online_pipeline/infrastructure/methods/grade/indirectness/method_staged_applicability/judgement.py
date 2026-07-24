"""Strict bounded evidence-body judgement for GRADE indirectness."""

from __future__ import annotations

from typing import Any


SEVERITIES = {"none", "serious", "very_serious", "unclear"}
IMPACTS = {"no_concern", "meaningful", "major"}
BASELINE_RISK_ASSESSMENTS = {
    "unavailable",
    "no_concern",
    "sensitivity_only",
    "concern",
}


def judgement_schema(*, evidence_profile: dict[str, Any]) -> dict[str, Any]:
    group_ids = [
        group["group_id"] for group in evidence_profile["concern_groups"]
    ]
    coverage_limited = _coverage_limited(evidence_profile)
    if group_ids:
        severities = set(SEVERITIES)
        if not coverage_limited:
            severities.remove("unclear")
    else:
        severities = {"none", "unclear"} if coverage_limited else {"none"}

    baseline_plan_status = evidence_profile["threshold_profile"][
        "baseline_risk_plan"
    ]["status"]
    if baseline_plan_status == "model_scenario":
        baseline_assessments = {
            "unavailable",
            "no_concern",
            "sensitivity_only",
        }
        if any(
            group["domain"] == "population"
            and group["mechanism"]
            in {"baseline_risk", "effect_modification_and_baseline_risk"}
            for group in evidence_profile["concern_groups"]
        ):
            baseline_assessments.add("concern")
    else:
        baseline_assessments = {"unavailable"}

    group_id_schema: dict[str, Any] = {"type": "string"}
    if group_ids:
        group_id_schema["enum"] = group_ids
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "assessment_status",
            "severity",
            "coverage_affects_judgement",
            "group_judgements",
            "baseline_risk_assessment",
        ],
        "properties": {
            "assessment_status": {"type": "string", "enum": ["completed"]},
            "severity": {"type": "string", "enum": sorted(severities)},
            "coverage_affects_judgement": (
                {"type": "boolean"}
                if coverage_limited
                else {"type": "boolean", "enum": [False]}
            ),
            "group_judgements": {
                "type": "array",
                "minItems": len(group_ids),
                "maxItems": len(group_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["group_id", "impact"],
                    "properties": {
                        "group_id": group_id_schema,
                        "impact": {"type": "string", "enum": sorted(IMPACTS)},
                    },
                },
            },
            "baseline_risk_assessment": {
                "type": "string",
                "enum": sorted(baseline_assessments),
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
        "coverage_affects_judgement",
        "group_judgements",
        "baseline_risk_assessment",
    }
    _require_keys(payload, expected, "judgement")
    if payload["assessment_status"] != "completed":
        raise ValueError("assessment_status must be completed")
    severity = _enum(payload["severity"], SEVERITIES, "severity")
    coverage_affects = _boolean(
        payload["coverage_affects_judgement"], "coverage_affects_judgement"
    )
    baseline_assessment = _enum(
        payload["baseline_risk_assessment"],
        BASELINE_RISK_ASSESSMENTS,
        "baseline_risk_assessment",
    )
    groups_by_id = {
        group["group_id"]: group for group in evidence_profile["concern_groups"]
    }
    raw_group_judgements = payload["group_judgements"]
    if not isinstance(raw_group_judgements, list):
        raise ValueError("group_judgements must be an array")
    group_judgements = [
        _parse_group_judgement(raw) for raw in raw_group_judgements
    ]
    returned_ids = [item["group_id"] for item in group_judgements]
    if len(set(returned_ids)) != len(returned_ids):
        raise ValueError("group_judgements must contain unique group IDs")
    if set(returned_ids) != set(groups_by_id):
        raise ValueError(
            "group_judgements must assess every frozen concern group exactly once"
        )
    ordered_judgements = {
        item["group_id"]: item for item in group_judgements
    }
    selected_groups = [
        {
            **group,
            "impact": ordered_judgements[group["group_id"]]["impact"],
        }
        for group in evidence_profile["concern_groups"]
        if ordered_judgements[group["group_id"]]["impact"] != "no_concern"
    ]
    _validate_baseline_assessment(
        baseline_assessment=baseline_assessment,
        selected_groups=selected_groups,
        evidence_profile=evidence_profile,
    )
    _validate_overall_semantics(
        severity=severity,
        coverage_affects=coverage_affects,
        selected_groups=selected_groups,
        evidence_profile=evidence_profile,
    )
    primary_domains = []
    for group in selected_groups:
        if group["domain"] not in primary_domains:
            primary_domains.append(group["domain"])
    return {
        "assessment_status": "completed",
        "severity": severity,
        "decision_basis": _decision_basis(severity=severity),
        "coverage_affects_judgement": coverage_affects,
        "primary_domains": primary_domains,
        "concern_groups": selected_groups,
        "group_judgements": [
            ordered_judgements[group["group_id"]]
            for group in evidence_profile["concern_groups"]
        ],
        "baseline_risk_assessment": baseline_assessment,
    }


def _parse_group_judgement(raw: Any) -> dict[str, str]:
    item = _object(raw, "group judgement")
    _require_keys(item, {"group_id", "impact"}, "group judgement")
    return {
        "group_id": _text(item["group_id"], "group_id"),
        "impact": _enum(item["impact"], IMPACTS, "impact"),
    }


def _validate_baseline_assessment(
    *,
    baseline_assessment: str,
    selected_groups: list[dict[str, Any]],
    evidence_profile: dict[str, Any],
) -> None:
    scenario_status = evidence_profile["threshold_profile"]["baseline_risk_plan"][
        "status"
    ]
    if scenario_status != "model_scenario" and baseline_assessment != "unavailable":
        raise ValueError(
            "baseline risk cannot be assessed without a target model scenario"
        )
    if baseline_assessment == "concern" and not any(
        group["domain"] == "population"
        and group["mechanism"]
        in {"baseline_risk", "effect_modification_and_baseline_risk"}
        for group in selected_groups
    ):
        raise ValueError(
            "baseline risk cannot trigger concern without a selected population concern"
        )


def _validate_overall_semantics(
    *,
    severity: str,
    coverage_affects: bool,
    selected_groups: list[dict[str, Any]],
    evidence_profile: dict[str, Any],
) -> None:
    coverage_limited = _coverage_limited(evidence_profile)
    if severity == "unclear":
        if not coverage_affects or not coverage_limited:
            raise ValueError("unclear indirectness requires an actual coverage limitation")
        if selected_groups:
            raise ValueError("unclear judgement must not assert a downgrade concern")
        return
    if coverage_affects:
        raise ValueError("an evaluable judgement cannot claim coverage prevents judgement")
    if severity == "none" and selected_groups:
        raise ValueError("not-serious indirectness must not select concern groups")
    if severity in {"serious", "very_serious"} and not selected_groups:
        raise ValueError("downgraded indirectness requires a frozen concern group")
    if severity == "very_serious" and not any(
        group["impact"] == "major" for group in selected_groups
    ):
        raise ValueError("very serious indirectness requires a major applicability limit")


def _coverage_limited(evidence_profile: dict[str, Any]) -> bool:
    coverage = evidence_profile["coverage"]
    if (
        coverage["missing_data_row_ids"]
        or coverage["missing_study_pio_data_row_ids"]
        or coverage["ambiguous_mapping_data_row_ids"]
    ):
        return True
    return any(
        values["insufficient_data_row_ids"]
        for values in evidence_profile["classification_coverage"].values()
    )


def _decision_basis(*, severity: str) -> str:
    return {
        "none": "no_meaningful_indirectness",
        "serious": "meaningful_applicability_limitation",
        "very_serious": "major_applicability_limitation",
        "unclear": "insufficient_applicability_evidence",
    }[severity]


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


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value
