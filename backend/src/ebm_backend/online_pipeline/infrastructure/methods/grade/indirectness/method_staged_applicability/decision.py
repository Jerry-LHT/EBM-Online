"""Stable output assembly for staged GRADE indirectness judgements."""

from __future__ import annotations

from typing import Any


def unavailable_judgement(reason: str) -> dict[str, Any]:
    return {
        "domain": "indirectness",
        "assessment_status": "insufficient_evidence",
        "downgraded": "unclear",
        "severity": "unclear",
        "levels": "unclear",
        "level_evaluable": False,
        "rationale": reason,
        "decision_features": {"reason_group": "insufficient_applicability_evidence"},
    }


def judged_indirectness(
    *,
    judgement: dict[str, Any],
    classification: dict[str, Any],
    evidence_profile: dict[str, Any],
    execution_trace: dict[str, Any],
) -> dict[str, Any]:
    severity = _canonical_severity(judgement["severity"])
    normalized_judgement = {**judgement, "severity": severity}
    if severity == "unclear":
        return {
            "domain": "indirectness",
            "assessment_status": "insufficient_evidence",
            "downgraded": "unclear",
            "severity": "unclear",
            "levels": "unclear",
            "level_evaluable": False,
            "rationale": _rationale(
                judgement=normalized_judgement,
                evidence_profile=evidence_profile,
            ),
            "decision_features": {
                "reason_group": "bounded_applicability_judgement",
                "classification": classification,
                "evidence_profile": evidence_profile,
                "judge": judgement,
                "execution_trace": execution_trace,
            },
        }
    levels = {"not_serious": 0, "serious": 1, "very_serious": 2}[severity]
    return {
        "domain": "indirectness",
        "assessment_status": "assessed",
        "downgraded": "no" if levels == 0 else "yes",
        "severity": severity,
        "levels": levels,
        "level_evaluable": True,
        "rationale": _rationale(
            judgement=normalized_judgement,
            evidence_profile=evidence_profile,
        ),
        "decision_features": {
            "reason_group": "bounded_applicability_judgement",
            "classification": classification,
            "evidence_profile": evidence_profile,
            "judge": judgement,
            "execution_trace": execution_trace,
        },
    }


def _canonical_severity(value: str) -> str:
    return "not_serious" if value == "none" else value


def _rationale(
    *,
    judgement: dict[str, Any],
    evidence_profile: dict[str, Any],
) -> str:
    coverage = evidence_profile["coverage"]
    if judgement["severity"] == "unclear":
        return (
            "Indirectness could not be evaluated because applicability coverage "
            f"was incomplete: {len(coverage['missing_data_row_ids'])} missing DataRow(s), "
            f"{len(coverage['missing_study_pio_data_row_ids'])} DataRow(s) without "
            "Study PIO, and "
            f"{len(coverage['ambiguous_mapping_data_row_ids'])} ambiguous mapping(s)."
        )
    if judgement["severity"] == "not_serious":
        return (
            f"Across {evidence_profile['data_row_count']} contributing DataRow(s), "
            "the bounded judge found no target-versus-evidence difference with a "
            "credible mechanism likely to materially change applicability of the effect."
        )
    group_summaries = []
    for group in judgement["concern_groups"]:
        group_summaries.append(
            f"{group['impact']} {group['domain']}/{group['facet']} concern via "
            f"{group['mechanism']} supported by "
            f"{len(group['less_direct_data_row_ids'])} DataRow(s)"
        )
    return (
        f"The bounded judge identified {len(group_summaries)} independent applicability "
        f"concern group(s): {'; '.join(group_summaries)}. "
        f"Direct-comparison status was {evidence_profile['direct_comparison_status']}; "
        f"the final indirectness rating was {judgement['severity']}."
    )
