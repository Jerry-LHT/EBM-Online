"""Deterministic evidence-body construction for GRADE indirectness."""

from __future__ import annotations

import math
from typing import Any

from ebm_backend.online_pipeline.domain.grade import GRADEIndirectnessInput
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.classification import (
    PICO_DOMAINS,
    is_eligible_concern_factor,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.effect_ranges import (
    build_effect_range_profile,
)


MORE_DIRECT_RATINGS = {
    "sufficiently_direct",
    "probably_sufficiently_direct",
}
WEIGHT_SUM_TOLERANCE = 0.001


def build_weight_profile(
    grade_input: GRADEIndirectnessInput,
) -> dict[str, Any]:
    weights = [item.weight_fraction for item in grade_input.study_evidence]
    present_weights = [float(value) for value in weights if value is not None]
    total_weight = sum(present_weights) if present_weights else None
    if len(present_weights) != len(weights):
        status = "incomplete"
    elif total_weight is None or not math.isfinite(total_weight):
        status = "invalid"
    elif not math.isclose(
        total_weight,
        1.0,
        rel_tol=0.0,
        abs_tol=WEIGHT_SUM_TOLERANCE,
    ):
        status = "invalid"
    else:
        status = "complete"
    return {
        "status": status,
        "data_row_count": len(weights),
        "weighted_data_row_count": len(present_weights),
        "total_weight": (
            round(total_weight, 6)
            if total_weight is not None and math.isfinite(total_weight)
            else None
        ),
        "expected_total_weight": 1.0,
        "tolerance": WEIGHT_SUM_TOLERANCE,
    }


def build_concern_groups(
    *,
    grade_input: GRADEIndirectnessInput,
    classification: dict[str, Any],
    weight_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    assessments = classification["study_assessments"]
    group_rows: dict[tuple[str, str, str], list[tuple[str, dict[str, Any]]]] = {}
    for assessment in assessments:
        for domain in PICO_DOMAINS:
            for factor in assessment["domains"][domain]["factors"]:
                if is_eligible_concern_factor(factor):
                    key = (domain, factor["facet"], factor["mechanism"])
                    group_rows.setdefault(key, []).append(
                        (assessment["data_row_id"], factor)
                    )

    groups: list[dict[str, Any]] = []
    for (domain, facet, mechanism), entries in group_rows.items():
        less_ids = [row_id for row_id, _ in entries]
        more_ids = [
            assessment["data_row_id"]
            for assessment in assessments
            if assessment["data_row_id"] not in less_ids
            and assessment["domains"][domain]["information_status"] == "sufficient"
            and assessment["domains"][domain]["overall_directness"]
            in MORE_DIRECT_RATINGS
        ]
        groups.append(
            {
                "group_id": _group_id(domain, facet, mechanism),
                "domain": domain,
                "facet": facet,
                "mechanism": mechanism,
                "less_direct_data_row_ids": less_ids,
                "more_direct_data_row_ids": more_ids,
                "effect_difference_likelihoods": sorted(
                    {factor["effect_difference_likelihood"] for _, factor in entries}
                ),
                "difference_summaries": [
                    factor["difference_summary"] for _, factor in entries
                ],
                "less_direct_weight": _group_weight(
                    grade_input=grade_input,
                    data_row_ids=less_ids,
                    weight_profile=weight_profile,
                ),
                "more_direct_weight": _group_weight(
                    grade_input=grade_input,
                    data_row_ids=more_ids,
                    weight_profile=weight_profile,
                ),
            }
        )
    if grade_input.direct_comparison_status == "indirect_or_network":
        row_ids = [item.data_row_id for item in grade_input.study_evidence]
        groups.append(
            {
                "group_id": "direct-comparison-pathway",
                "domain": "direct_comparison",
                "facet": "comparison_pathway",
                "mechanism": "comparison_pathway",
                "less_direct_data_row_ids": row_ids,
                "more_direct_data_row_ids": [],
                "effect_difference_likelihoods": ["possible"],
                "difference_summaries": [
                    "The target contrast is informed through an indirect or network pathway."
                ],
                "less_direct_weight": _group_weight(
                    grade_input=grade_input,
                    data_row_ids=row_ids,
                    weight_profile=weight_profile,
                ),
                "more_direct_weight": None,
            }
        )
    return groups


def build_evidence_profile(
    *,
    grade_input: GRADEIndirectnessInput,
    classification: dict[str, Any],
    concern_groups: list[dict[str, Any]],
    threshold_requirement: dict[str, Any],
    threshold_profile: dict[str, Any],
    weight_profile: dict[str, Any],
) -> dict[str, Any]:
    assessment_by_id = {
        item["data_row_id"]: item for item in classification["study_assessments"]
    }
    return {
        "setting_id": grade_input.setting.setting_id,
        "estimate_id": grade_input.estimate.estimate_id,
        "study_count": grade_input.estimate.study_count,
        "data_row_count": len(grade_input.study_evidence),
        "direct_comparison_status": grade_input.direct_comparison_status,
        "coverage": to_jsonable(grade_input.coverage),
        "classification_coverage": _classification_coverage(classification),
        "weight_coverage": weight_profile,
        "concern_groups": concern_groups,
        "threshold_requirement": threshold_requirement,
        "threshold_profile": threshold_profile,
        "effect_range_profile": build_effect_range_profile(
            grade_input=grade_input,
            threshold_profile=threshold_profile,
            concern_groups=concern_groups,
            use_weights=weight_profile["status"] == "complete",
        ),
        "row_evidence": [
            {
                "data_row_id": item.data_row_id,
                "study_id": item.study_id,
                "effect_value": item.effect_value,
                "ci_lower": item.ci_lower,
                "ci_upper": item.ci_upper,
                "weight_fraction": (
                    item.weight_fraction
                    if weight_profile["status"] == "complete"
                    else None
                ),
                "observed_control_risk": item.control_baseline_risk,
                "classification": assessment_by_id[item.data_row_id],
            }
            for item in grade_input.study_evidence
        ],
        "subgroup_evidence": {
            "estimates": [to_jsonable(item) for item in grade_input.subgroup_estimates],
            "difference_tests": [
                to_jsonable(item) for item in grade_input.subgroup_difference_tests
            ],
        },
        "baseline_risk": {
            "target_baseline_risk_source": threshold_profile[
                "baseline_risk_plan"
            ]["status"],
            "model_scenario": {
                "low": threshold_profile["baseline_risk_plan"]["low"],
                "high": threshold_profile["baseline_risk_plan"]["high"],
            },
            "observed_study_control_risks": [
                {
                    "data_row_id": item.data_row_id,
                    "study_id": item.study_id,
                    "control_baseline_risk": item.control_baseline_risk,
                }
                for item in grade_input.study_evidence
                if item.control_baseline_risk is not None
            ],
            "model_scenario_is_observed_study_risk": False,
        },
    }


def _classification_coverage(classification: dict[str, Any]) -> dict[str, Any]:
    assessments = classification["study_assessments"]
    return {
        domain: {
            "sufficient_data_row_ids": [
                item["data_row_id"]
                for item in assessments
                if item["domains"][domain]["information_status"] == "sufficient"
            ],
            "insufficient_data_row_ids": [
                item["data_row_id"]
                for item in assessments
                if item["domains"][domain]["information_status"]
                == "study_information_insufficient"
            ],
        }
        for domain in PICO_DOMAINS
    }


def _group_weight(
    *,
    grade_input: GRADEIndirectnessInput,
    data_row_ids: list[str],
    weight_profile: dict[str, Any],
) -> float | None:
    if not data_row_ids or weight_profile["status"] != "complete":
        return None
    weights = {
        item.data_row_id: item.weight_fraction for item in grade_input.study_evidence
    }
    if any(weights[row_id] is None for row_id in data_row_ids):
        return None
    return round(sum(float(weights[row_id]) for row_id in data_row_ids), 6)


def _group_id(domain: str, facet: str, mechanism: str) -> str:
    return f"{domain}-{facet}-{mechanism}".replace("_", "-")
