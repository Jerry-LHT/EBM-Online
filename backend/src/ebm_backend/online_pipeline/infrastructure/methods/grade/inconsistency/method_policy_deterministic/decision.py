"""Stable output assembly for GRADE inconsistency judgements."""

from __future__ import annotations

from typing import Any


def single_study_judgement() -> dict[str, Any]:
    return _judgement(
        severity="not_serious",
        levels=0,
        rationale=(
            "Only one study contributes to this outcome, so between-study "
            "inconsistency cannot be estimated. Under the GRADE reporting "
            "convention, no inconsistency concern is recorded."
        ),
        assessment_status="single_study_not_estimable",
        decision_features={"reason_group": "single_study"},
    )


def unavailable_judgement(reason: str) -> dict[str, Any]:
    return {
        "domain": "inconsistency",
        "assessment_status": "insufficient_evidence",
        "downgraded": "unclear",
        "severity": "unclear",
        "levels": "unclear",
        "level_evaluable": False,
        "rationale": reason,
        "decision_features": {"reason_group": "insufficient_study_effect_coverage"},
    }


def same_range_judgement(
    *,
    policy: dict[str, Any],
    evidence_profile: dict[str, Any],
) -> dict[str, Any]:
    return _judgement(
        severity="not_serious",
        levels=0,
        rationale=(
            "All contributing study point estimates fall in the same frozen "
            "effect range; statistical heterogeneity alone does not establish "
            "clinically important inconsistency."
        ),
        decision_features={
            "reason_group": "same_frozen_effect_range",
            "generated_policy": policy,
            "evidence_profile": evidence_profile,
            "judge": None,
        },
    )


def judged_inconsistency(
    *,
    judge_output: dict[str, Any],
    policy: dict[str, Any],
    evidence_profile: dict[str, Any],
) -> dict[str, Any]:
    severity = _canonical_severity(str(judge_output["severity"]))
    levels = {"not_serious": 0, "serious": 1, "very_serious": 2}[severity]
    return _judgement(
        severity=severity,
        levels=levels,
        rationale=_factual_rationale(
            judge_output=judge_output,
            evidence_profile=evidence_profile,
        ),
        decision_features={
            "reason_group": "bounded_grade_judgement",
            "generated_policy": policy,
            "evidence_profile": evidence_profile,
            "judge": judge_output,
        },
    )


def _factual_rationale(
    *,
    judge_output: dict[str, Any],
    evidence_profile: dict[str, Any],
) -> str:
    pooled = evidence_profile["pooled_estimate"]
    point_range = pooled["point_range"] or "unavailable"
    ci_ranges = pooled["ci_ranges"]
    ci_summary = ", ".join(ci_ranges) if ci_ranges else "unavailable"
    distribution_parts: list[str] = []
    for range_name, entry in evidence_profile["range_distribution"].items():
        part = f"{range_name}: {entry['study_count']} study/studies"
        if entry["weight_fraction"] is not None:
            part += f" ({float(entry['weight_fraction']):.1%} weight)"
        distribution_parts.append(part)
    span = evidence_profile["threshold_span"]
    rationale = (
        f"The pooled point estimate is in {point_range}; its confidence interval "
        f"spans: {ci_summary}. Study point estimates are distributed as "
        f"{'; '.join(distribution_parts)}, spanning {span} frozen threshold(s). "
    )
    basis = judge_output["decision_basis"]
    if basis == "meaningful_unexplained_inconsistency":
        rationale += (
            "The bounded judge classified this cross-threshold distribution as "
            "clinically meaningful and unexplained."
        )
    elif basis == "inconsistency_explained":
        rationale += (
            "The bounded judge classified the variation as explained by the frozen "
            f"effect modifier '{judge_output['effect_modifier_factor']}' using subgroup "
            f"test '{judge_output['subgroup_test_id']}'."
        )
    elif basis == "likely_imprecision":
        rationale += (
            "The bounded judge did not classify the distribution as meaningful "
            "inconsistency and identified likely overlap with imprecision."
        )
    else:
        rationale += (
            "The bounded judge did not classify the observed distribution as "
            "clinically meaningful inconsistency."
        )
    if judge_output["imprecision_overlap_risk"] and basis != "likely_imprecision":
        rationale += " Potential overlap with imprecision was identified."
    return rationale


def _judgement(
    *,
    severity: str,
    levels: int,
    rationale: str,
    assessment_status: str = "assessed",
    decision_features: dict[str, Any],
) -> dict[str, Any]:
    return {
        "domain": "inconsistency",
        "assessment_status": assessment_status,
        "downgraded": "no" if levels == 0 else "yes",
        "severity": severity,
        "levels": levels,
        "level_evaluable": True,
        "rationale": rationale,
        "decision_features": decision_features,
    }


def _canonical_severity(value: str) -> str:
    return "not_serious" if value == "none" else value
