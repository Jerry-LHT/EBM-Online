"""Output normalization and debug shaping for the two-step indirectness method."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.common import as_list, first_dict, judgement


DOMAIN = "indirectness"
SEVERITY_LEVELS = {"none": 0, "serious": 1, "very_serious": 2}
DOMAINS = ("population", "intervention", "comparator", "direct_comparison", "outcome", "timepoint", "setting")


def _judgement_from_llm(
    *,
    raw: dict[str, Any],
    evidence_package: dict[str, Any],
    extraction: dict[str, Any] | None = None,
    threshold_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    severity = _severity(raw.get("severity"))
    downgraded = _downgraded(raw.get("downgraded"), severity)
    levels = _levels(raw.get("levels"), severity)
    if severity == "unclear" or downgraded == "unclear" or levels == "unclear":
        result = judgement(
            DOMAIN,
            downgraded="unclear",
            severity="unclear",
            levels="unclear",
            level_evaluable=False,
            rationale=str(raw.get("rationale") or "Indirectness could not be evaluated from the normalized input."),
        )
    else:
        result = judgement(
            DOMAIN,
            downgraded=downgraded,
            severity=severity,
            levels=levels,
            level_evaluable=True,
            rationale=str(raw.get("rationale") or ""),
        )
    result["debug"] = _debug(
        raw=raw,
        evidence_package=evidence_package,
        extraction=extraction,
        threshold_policy=threshold_policy,
        fallback_reason=None,
    )
    return result


def _unclear(*, evidence_package: dict[str, Any], fallback_reason: str) -> dict[str, Any]:
    result = judgement(
        DOMAIN,
        downgraded="unclear",
        severity="unclear",
        levels="unclear",
        level_evaluable=False,
        rationale="Indirectness could not be evaluated because the LLM adjudicator was unavailable.",
    )
    result["debug"] = _debug(
        raw={},
        evidence_package=evidence_package,
        extraction=None,
        threshold_policy=None,
        fallback_reason=fallback_reason,
    )
    return result


def _debug(
    *,
    raw: dict[str, Any],
    evidence_package: dict[str, Any],
    extraction: dict[str, Any] | None,
    threshold_policy: dict[str, Any] | None,
    fallback_reason: str | None,
) -> dict[str, Any]:
    evidence_found = first_dict(evidence_package.get("included_study_evidence"), evidence_package.get("evidence_found"))
    domain_comparisons = _domain_comparisons(raw.get("domain_comparisons"))
    extracted_profile = _extracted_profile(extraction)
    debug = {
        "method": "method_llm_twostep",
        "input_policy": evidence_package.get("input_policy"),
        "population_source": _population_source(evidence_package),
        "llm_used": fallback_reason is None,
        "study_level_pico_profile": extracted_profile,
        "dynamic_threshold_policy": _threshold_policy(threshold_policy),
        "evidence_profile": _evidence_profile(raw.get("evidence_profile")),
        "directness_ratings": _directness_ratings(raw.get("directness_ratings")),
        "applicability_gate": _applicability_gate(raw.get("applicability_gate")),
        "serious_limitation_check": _serious_limitation_check(raw.get("serious_limitation_check")),
        "indirectness_domains": _domains(raw.get("indirectness_domains")),
        "domain_assessments": _domain_assessments(raw.get("domain_assessments"), fallback=domain_comparisons),
        "domain_comparisons": domain_comparisons,
        "supporting_evidence": _string_list(raw.get("supporting_evidence")),
        "counter_evidence": _string_list(raw.get("counter_evidence")),
        "confidence": _confidence(raw.get("confidence")),
        "decision_features": {
            "study_count": evidence_found.get("study_count", evidence_package.get("study_count")),
            "result_row_count": len(as_list(evidence_found.get("study_result_rows", evidence_package.get("study_result_rows")))),
            "missing_study_characteristics_count": len(
                as_list(
                    evidence_found.get(
                        "study_characteristics_missing_study_ids",
                        evidence_package.get("study_characteristics_missing_study_ids"),
                    )
                )
            ),
            "extraction_candidate_count": len(extracted_profile.get("important_mismatch_candidates") or []),
            "extraction_candidate_domains": [
                item.get("domain")
                for item in extracted_profile.get("important_mismatch_candidates") or []
                if isinstance(item, dict) and item.get("domain")
            ],
        },
    }
    if fallback_reason:
        debug["fallback_reason"] = fallback_reason
    return debug


def _threshold_policy(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    domain_thresholds_source = source.get("domain_thresholds") if isinstance(source.get("domain_thresholds"), dict) else {}
    domain_thresholds = {}
    for domain in DOMAINS:
        item = domain_thresholds_source.get(domain) if isinstance(domain_thresholds_source.get(domain), dict) else {}
        domain_thresholds[domain] = {
            "threshold_posture": _threshold_posture(item.get("threshold_posture")),
            "downgrade_triggers": [_clip(text, limit=220) for text in _string_list(item.get("downgrade_triggers"))[:6]],
            "non_downgrade_patterns": [
                _clip(text, limit=220)
                for text in _string_list(item.get("non_downgrade_patterns"))[:6]
            ],
            "evidence_terms": [_clip(text, limit=180) for text in _string_list(item.get("evidence_terms"))[:6]],
            "rationale": _clip(item.get("rationale"), limit=360),
        }
    return {
        "policy_summary": _clip(source.get("policy_summary"), limit=500),
        "domain_thresholds": domain_thresholds,
        "cross_domain_integration": _clip(source.get("cross_domain_integration"), limit=500),
    }


def _threshold_posture(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"sensitive", "balanced", "conservative"}:
        return text
    return "balanced"


def _population_source(evidence_package: dict[str, Any]) -> Any:
    review_question = first_dict(evidence_package.get("review_question"))
    if review_question:
        return review_question.get("population_source")
    synthesis_target_pico = first_dict(evidence_package.get("synthesis_target_pico"))
    if synthesis_target_pico:
        population = first_dict(synthesis_target_pico.get("population"))
        return population.get("source")
    target_question = first_dict(evidence_package.get("target_question"))
    if target_question:
        population = first_dict(target_question.get("population"))
        return population.get("source")
    return (evidence_package.get("target") or {}).get("population_source")


def _severity(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"none", "serious", "very_serious"}:
        return text
    return "unclear"


def _downgraded(value: Any, severity: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"yes", "no", "unclear"}:
        return text
    if severity == "none":
        return "no"
    if severity in {"serious", "very_serious"}:
        return "yes"
    return "unclear"


def _levels(value: Any, severity: str) -> int | str:
    if severity in SEVERITY_LEVELS:
        return SEVERITY_LEVELS[severity]
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return "unclear"
    return parsed if parsed in {0, 1, 2} else "unclear"


def _domains(value: Any) -> list[str]:
    return [item for item in _string_list(value) if item in set(DOMAINS)]


def _domain_assessments(value: Any, *, fallback: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    assessments: dict[str, dict[str, Any]] = {}
    for domain in DOMAINS:
        fallback_item = fallback.get(domain) if isinstance(fallback, dict) and isinstance(fallback.get(domain), dict) else {}
        item = source.get(domain) if isinstance(source.get(domain), dict) else fallback_item
        assessments[domain] = {
            "concern_level": _concern_level(item.get("concern_level")),
            "supporting_evidence": _string_list(item.get("supporting_evidence")),
            "counter_evidence": _string_list(item.get("counter_evidence")),
            "applicability_impact": str(item.get("applicability_impact") or ""),
        }
    return assessments


def _evidence_profile(value: Any) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    sections = (
        "population_scope",
        "intervention_variants",
        "comparator_context",
        "outcome_measurement",
        "follow_up",
        "setting_era_context",
        "representativeness_limits",
    )
    profile: dict[str, dict[str, Any]] = {}
    for section in sections:
        item = source.get(section) if isinstance(source.get(section), dict) else {}
        profile[section] = {
            "summary": str(item.get("summary") or ""),
            "findings": _string_list(item.get("findings")),
            "limits": _string_list(item.get("limits")),
            "applicability_impact": str(item.get("applicability_impact") or ""),
        }
    return profile


def _extracted_profile(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    profile_source = source.get("study_level_pico_profile") if isinstance(source.get("study_level_pico_profile"), dict) else {}
    profile = {}
    for domain in DOMAINS:
        item = profile_source.get(domain) if isinstance(profile_source.get(domain), dict) else {}
        profile[domain] = {
            "evidence_coverage": [_clip(text, limit=220) for text in _string_list(item.get("evidence_coverage"))[:6]],
            "visible_differences": [_clip(text, limit=220) for text in _string_list(item.get("visible_differences"))[:6]],
            "within_scope_explanations": [
                _clip(text, limit=220)
                for text in _string_list(item.get("within_scope_explanations"))[:6]
            ],
            "effect_modification_plausible": _plausibility(item.get("effect_modification_plausible")),
            "possible_applicability_impact": _applicability_impact(item.get("possible_applicability_impact")),
            "rationale": _clip(item.get("rationale"), limit=360),
        }
    return {
        "target_summary": first_dict(source.get("target_summary")),
        "review_question_summary": first_dict(source.get("review_question_summary")),
        "synthesis_target_summary": first_dict(source.get("synthesis_target_summary")),
            "review_to_synthesis_alignment": [
            _extracted_alignment(item)
            for item in as_list(source.get("review_to_synthesis_alignment"))
            if isinstance(item, dict)
        ][:10],
        "study_level_pico_profile": profile,
        "applicability_gate": _applicability_gate(source.get("applicability_gate")),
        "important_mismatch_candidates": [
            _extracted_candidate(item)
            for item in as_list(source.get("important_mismatch_candidates"))
            if isinstance(item, dict)
        ][:12],
        "likely_within_scope_heterogeneity": [
            _extracted_within_scope(item)
            for item in as_list(source.get("likely_within_scope_heterogeneity"))
            if isinstance(item, dict)
        ][:12],
        "insufficient_information": [_clip(text, limit=180) for text in _string_list(source.get("insufficient_information"))[:10]],
    }


def _extracted_alignment(item: dict[str, Any]) -> dict[str, Any]:
    relation = str(item.get("relation") or "unclear").strip().lower()
    allowed_relations = {
        "reasonable_specification",
        "narrower_but_applicable",
        "package_or_cointervention_shift",
        "outcome_measurement_shift",
        "population_shift",
        "comparator_shift",
        "timepoint_shift",
        "setting_context_shift",
        "unclear",
    }
    return {
        "domain": _extracted_domain(item.get("domain")),
        "review_question": _clip(item.get("review_question"), limit=220),
        "synthesis_target": _clip(item.get("synthesis_target"), limit=220),
        "relation": relation if relation in allowed_relations else "unclear",
        "difference_detected": _bool_or_unclear(item.get("difference_detected")),
        "is_within_scope_variation": _bool_or_unclear(item.get("is_within_scope_variation")),
        "effect_modification_plausible": _plausibility(item.get("effect_modification_plausible")),
        "possible_applicability_impact": _applicability_impact(item.get("possible_applicability_impact")),
        "rationale": _clip(item.get("rationale"), limit=320),
    }


def _extracted_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": _extracted_domain(item.get("domain")),
        "candidate_difference": _clip(item.get("candidate_difference"), limit=260),
        "why_it_may_affect_effect": _clip(item.get("why_it_may_affect_effect"), limit=320),
        "evidence_terms": [_clip(text, limit=180) for text in _string_list(item.get("evidence_terms"))[:5]],
        "possible_applicability_impact": _applicability_impact(item.get("possible_applicability_impact")),
    }


def _extracted_within_scope(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": _extracted_domain(item.get("domain")),
        "difference": _clip(item.get("difference"), limit=260),
        "why_within_scope": _clip(item.get("why_within_scope"), limit=320),
    }


def _extracted_domain(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in set(DOMAINS) else "unclear"


def _applicability_impact(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"none", "minor", "potentially_important", "important", "major", "unclear"}:
        return text
    return "unclear"


def _applicability_gate(value: Any) -> list[dict[str, Any]]:
    rows = []
    for item in as_list(value):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "domain": _extracted_domain(item.get("domain")),
                "difference_detected": _bool_or_unclear(item.get("difference_detected")),
                "difference_type": _clip(item.get("difference_type"), limit=180),
                "is_within_scope_variation": _bool_or_unclear(item.get("is_within_scope_variation")),
                "effect_modification_plausible": _plausibility(item.get("effect_modification_plausible")),
                "applicability_impact": _applicability_impact(item.get("applicability_impact")),
                "downgrade_contribution": _downgrade_contribution(item.get("downgrade_contribution")),
                "rationale": _clip(item.get("rationale"), limit=320),
            }
        )
    return rows[:10]


def _serious_limitation_check(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "accepted_serious_limitations": [
            _accepted_serious_limitation(item)
            for item in as_list(source.get("accepted_serious_limitations"))
            if isinstance(item, dict)
        ][:8],
        "rejected_or_minor_candidates": [
            _rejected_or_minor_candidate(item)
            for item in as_list(source.get("rejected_or_minor_candidates"))
            if isinstance(item, dict)
        ][:12],
        "threshold_rationale": _clip(source.get("threshold_rationale"), limit=500),
    }


def _accepted_serious_limitation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": _extracted_domain(item.get("domain")),
        "limitation": _clip(item.get("limitation"), limit=260),
        "applicability_mechanism": _clip(item.get("applicability_mechanism"), limit=360),
        "supporting_evidence": [_clip(text, limit=180) for text in _string_list(item.get("supporting_evidence"))[:5]],
    }


def _rejected_or_minor_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": _extracted_domain(item.get("domain")),
        "candidate_difference": _clip(item.get("candidate_difference"), limit=260),
        "reason_rejected_or_minor": _clip(item.get("reason_rejected_or_minor"), limit=360),
        "supporting_evidence": [_clip(text, limit=180) for text in _string_list(item.get("supporting_evidence"))[:5]],
    }


def _bool_or_unclear(value: Any) -> bool | str:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return "unclear"


def _plausibility(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"yes", "probably_yes", "probably_no", "no", "unclear"}:
        return text
    return "unclear"


def _downgrade_contribution(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"none", "possible", "serious", "very_serious"}:
        return text
    return "possible" if text == "unclear" else "none"


def _directness_ratings(value: Any) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    ratings: dict[str, dict[str, Any]] = {}
    for domain in DOMAINS:
        item = source.get(domain) if isinstance(source.get(domain), dict) else {}
        ratings[domain] = {
            "rating": _directness_rating(item.get("rating")),
            "rationale": str(item.get("rationale") or ""),
            "applicability_concern": str(item.get("applicability_concern") or ""),
        }
    return ratings


def _domain_comparisons(value: Any) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    comparisons: dict[str, dict[str, Any]] = {}
    for domain in DOMAINS:
        item = source.get(domain) if isinstance(source.get(domain), dict) else {}
        comparisons[domain] = {
            "target": str(item.get("target") or ""),
            "evidence_found": str(item.get("evidence_found") or ""),
            "relation": _relation(item.get("relation")),
            "concern_level": _concern_level(item.get("concern_level")),
            "applicability_impact": str(item.get("applicability_impact") or ""),
            "supporting_evidence": _string_list(item.get("supporting_evidence")),
            "counter_evidence": _string_list(item.get("counter_evidence")),
        }
    return comparisons


def _concern_level(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"none", "minor", "serious", "very_serious", "unclear"}:
        return text
    return "unclear"


def _relation(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"same", "narrower_but_applicable", "broader_but_applicable", "partial_overlap", "different", "unclear"}:
        return text
    return "unclear"


def _directness_rating(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"yes", "probably_yes", "probably_no", "no", "unclear"}:
        return text
    return "unclear"


def _confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"low", "moderate", "high"} else "low"


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in as_list(value) if str(item).strip()]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clip(value: Any, *, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
