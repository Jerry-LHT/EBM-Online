"""Deterministic imprecision GRADE domain method."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_deterministic.utils import (
    as_float,
    as_int,
    ci_crosses_line_of_no_effect,
    ci_ratio,
    first_dict,
    join_text,
    norm_text,
    not_serious,
    serious,
    unclear,
    very_serious,
)


DOMAIN = "imprecision"


class Method:
    domain = DOMAIN

    def run(self, *, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
        return predict(domain_evidence=domain_evidence, evidence_body=evidence_body)


def predict(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    estimate = first_dict(domain_evidence.get("effect_estimate"), evidence_body.get("effect_estimate"))
    sof_context = first_dict(evidence_body.get("sof_context"), domain_evidence.get("sof_context"))
    data_type = str(domain_evidence.get("data_type") or estimate.get("data_type") or "")
    effect_measure = str(domain_evidence.get("effect_measure") or estimate.get("effect_measure") or "")
    effect = as_float(estimate.get("effect_value"))
    lower = as_float(estimate.get("ci_lower"))
    upper = as_float(estimate.get("ci_upper"))
    participants = as_int(domain_evidence.get("participant_count")) or as_int(estimate.get("participant_count"))
    study_count = as_int(domain_evidence.get("study_count")) or as_int(estimate.get("study_count"))
    sof_text = norm_text(join_text(sof_context.get("relative_effect_text"), sof_context.get("participants_text"), sof_context.get("footnote_texts")))

    if "very_wide" in sof_text or "extremely_wide" in sof_text:
        return very_serious(DOMAIN, "SoF text describes very wide confidence intervals.")
    if lower is None or upper is None:
        return unclear(DOMAIN, "Confidence interval is unavailable.")
    if ci_crosses_line_of_no_effect(lower, upper, effect_measure):
        if ci_ratio(lower, upper) >= 10 or (participants is not None and participants < 100):
            return very_serious(DOMAIN, "Confidence interval crosses no effect and is very wide or based on a small sample.")
        return serious(DOMAIN, "Confidence interval crosses the line of no effect.")
    if data_type == "Dichotomous" and ci_ratio(lower, upper) >= 5:
        return serious(DOMAIN, "Dichotomous confidence interval is wide.")
    if effect is not None and abs(upper - lower) > max(abs(effect) * 2, 1.0) and (study_count is not None and study_count <= 1):
        return serious(DOMAIN, "Single-study estimate has a wide confidence interval.")
    if participants is not None and participants < 200 and study_count is not None and study_count <= 1:
        return serious(DOMAIN, "Evidence body has a small sample and one contributing study.")
    return not_serious(DOMAIN, "Confidence interval and information size do not trigger the deterministic imprecision rules.")


def build_method() -> Method:
    return Method()
