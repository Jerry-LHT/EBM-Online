"""Threshold normalization for GRADE imprecision."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.utils import as_float, as_list, norm_text


RATIO_IMPORTANT_BENEFIT = 0.75
RATIO_IMPORTANT_HARM = 1.25
DEFAULT_ABSOLUTE_THRESHOLD_PER_1000 = 25.0
DIRECT_THRESHOLD_TERMS = {
    "minimal important",
    "minimally important",
    "minimum important",
    "mid",
    "mcid",
    "clinically important difference",
    "clinical important difference",
    "important difference",
    "decision threshold",
    "non-inferiority",
    "noninferiority",
    "margin",
    "clinically meaningful",
    "guideline panel",
}
NON_THRESHOLD_TERMS = {
    "observed effect",
    "effect estimate",
    "summary of findings",
    "sof",
    "confidence interval",
    "event rate",
    "absolute effect",
    "risk in the control group",
    "disease definition",
    "diagnostic",
    "severity cutoff",
    "severity cut-off",
    "definition",
}


def normalize_threshold_result(result: dict[str, Any]) -> dict[str, Any]:
    confidence = str(result.get("source_confidence") or "none").strip().lower()
    if confidence not in {"high", "medium", "low", "none"}:
        confidence = "low"
    scale = str(result.get("threshold_scale") or "none").strip().lower()
    if scale not in {"absolute_risk_difference_per_1000", "ratio", "continuous_mid", "none"}:
        scale = "none"
    threshold_kind = _normalize_choice(
        result.get("threshold_kind"),
        allowed={"absolute_risk_difference", "ratio", "continuous_mid", "ois", "unavailable"},
        default=_threshold_kind_from_scale(scale),
    )
    derivation_type = _normalize_choice(
        result.get("derivation_type"),
        allowed={"direct_source", "derived_from_source", "llm_reasoned_fallback", "unavailable"},
        default="direct_source" if bool(result.get("threshold_found")) else "unavailable",
    )
    applicability = _normalize_choice(
        result.get("threshold_applicability"),
        allowed={"direct", "indirect", "general_grade_default", "not_applicable"},
        default="indirect" if bool(result.get("threshold_found")) else "not_applicable",
    )
    urls = [str(url) for url in as_list(result.get("source_urls")) if str(url).strip()]
    source_backed_derivation = derivation_type in {"direct_source", "derived_from_source"}
    validation_notes = threshold_evidence_validation_notes(result)
    source_evidence_ok = not any(note.startswith("rejected_") for note in validation_notes)
    threshold_found = bool(result.get("threshold_found")) and scale != "none" and bool(urls) and source_backed_derivation and source_evidence_ok
    threshold_source_type = "source_backed" if threshold_found else ""

    if not threshold_found:
        reasoned = _reasoned_fallback_from_result(result)
        if reasoned is not None:
            reasoned["threshold_evidence_grade"] = "llm_reasoned_fallback"
            reasoned["threshold_validation_notes"] = validation_notes
            return reasoned
        fallback = fallback_threshold("threshold_not_found")
        fallback["llm_raw_threshold"] = result
        fallback["threshold_validation_notes"] = validation_notes
        return fallback

    important_benefit = as_float(result.get("important_benefit"))
    important_harm = as_float(result.get("important_harm"))
    minimal_important_difference = as_float(result.get("minimal_important_difference"))
    outcome_direction = normalize_outcome_direction(result.get("outcome_direction"))
    if _is_generic_grade_ratio_default(scale=scale, important_benefit=important_benefit, important_harm=important_harm):
        if applicability == "direct":
            applicability = "general_grade_default"
        if "generic_grade_default_ratio_threshold" not in validation_notes:
            validation_notes.append("generic_grade_default_ratio_threshold")
    cache_eligible = threshold_found and bool(result.get("cache_eligible", True)) and applicability in {"direct", "indirect"}
    fallback_completed = False
    if scale == "absolute_risk_difference_per_1000" and minimal_important_difference is not None:
        if important_benefit is None:
            important_benefit, _ = directional_thresholds_from_mid(
                mid=minimal_important_difference,
                outcome_direction=outcome_direction,
            )
            fallback_completed = True
        if important_harm is None:
            _, important_harm = directional_thresholds_from_mid(
                mid=minimal_important_difference,
                outcome_direction=outcome_direction,
            )
            fallback_completed = True
    if scale == "ratio":
        if important_benefit is None:
            important_benefit, _ = directional_ratio_thresholds(outcome_direction=outcome_direction)
            fallback_completed = True
        if important_harm is None:
            _, important_harm = directional_ratio_thresholds(outcome_direction=outcome_direction)
            fallback_completed = True
    if scale == "continuous_mid" and minimal_important_difference is not None and outcome_direction != "unknown":
        if important_benefit is None or important_harm is None:
            important_benefit, important_harm = directional_thresholds_from_mid(
                mid=minimal_important_difference,
                outcome_direction=outcome_direction,
            )
            fallback_completed = True

    validation_error = threshold_validation_error(
        scale=scale,
        important_benefit=important_benefit,
        important_harm=important_harm,
    )
    corrected_from_mid = False
    if validation_error is not None and minimal_important_difference is not None and outcome_direction != "unknown":
        if scale in {"absolute_risk_difference_per_1000", "continuous_mid"}:
            important_benefit, important_harm = directional_thresholds_from_mid(
                mid=minimal_important_difference,
                outcome_direction=outcome_direction,
            )
            validation_error = threshold_validation_error(
                scale=scale,
                important_benefit=important_benefit,
                important_harm=important_harm,
            )
            corrected_from_mid = validation_error is None
    return {
        "threshold_found": True,
        "threshold_scale": scale,
        "important_benefit": important_benefit,
        "important_harm": important_harm,
        "minimal_important_difference": minimal_important_difference,
        "outcome_type": str(result.get("outcome_type") or ""),
        "scale_identified": bool(result.get("scale_identified")),
        "scale_name": _noneable_str(result.get("scale_name")),
        "scale_range": _noneable_str(result.get("scale_range")),
        "scale_direction": normalize_outcome_direction(result.get("scale_direction")),
        "threshold_kind": threshold_kind,
        "derivation_type": derivation_type,
        "threshold_applicability": applicability,
        "search_plan": _string_list(result.get("search_plan")),
        "research_workflow": result.get("research_workflow") if isinstance(result.get("research_workflow"), dict) else {},
        "accepted_candidates": _dict_list(result.get("accepted_candidates")),
        "rejected_materials": _dict_list(result.get("rejected_materials")),
        "source_values": result.get("source_values") if isinstance(result.get("source_values"), dict) else {},
        "threshold_derivation": str(result.get("threshold_derivation") or ""),
        "optimal_information_size_notes": str(result.get("optimal_information_size_notes") or ""),
        "source_urls": urls,
        "source_confidence": confidence,
        "outcome_direction": outcome_direction,
        "applicability_notes": str(result.get("applicability_notes") or ""),
        "threshold_source_type": threshold_source_type,
        "threshold_evidence_grade": threshold_evidence_grade(
            derivation_type=derivation_type,
            applicability=applicability,
            confidence=confidence,
            validation_notes=validation_notes,
        ),
        "threshold_validation_notes": validation_notes,
        "cache_eligible": cache_eligible,
        "fallback_used": False,
        "fallback_completed_missing_threshold_side": fallback_completed,
        "threshold_corrected_from_mid": corrected_from_mid,
        "threshold_valid": validation_error is None,
        "threshold_validation_error": validation_error,
    }


def fallback_threshold(reason: str) -> dict[str, Any]:
    return {
        "threshold_found": False,
        "threshold_scale": "fallback",
        "important_benefit": None,
        "important_harm": None,
        "minimal_important_difference": None,
        "threshold_kind": "unavailable",
        "derivation_type": "unavailable",
        "threshold_applicability": "not_applicable",
        "search_plan": [],
        "research_workflow": {},
        "accepted_candidates": [],
        "rejected_materials": [],
        "source_values": {},
        "threshold_derivation": "",
        "scale_identified": False,
        "scale_name": None,
        "scale_range": None,
        "scale_direction": "unknown",
        "optimal_information_size_notes": "",
        "source_urls": [],
        "source_confidence": "low",
        "outcome_direction": "unknown",
        "applicability_notes": reason,
        "threshold_source_type": "hardcoded_fallback",
        "threshold_evidence_grade": "unavailable",
        "threshold_validation_notes": [],
        "cache_eligible": False,
        "fallback_used": True,
        "fallback_reason": reason,
    }


def _reasoned_fallback_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
    derivation_type = _normalize_choice(
        result.get("derivation_type"),
        allowed={"direct_source", "derived_from_source", "llm_reasoned_fallback", "unavailable"},
        default="unavailable",
    )
    if not bool(result.get("reasoned_fallback")) and derivation_type != "llm_reasoned_fallback":
        return None
    scale = str(result.get("fallback_scale") or "none").strip().lower()
    if scale == "none":
        scale = str(result.get("threshold_scale") or "none").strip().lower()
    if scale not in {"absolute_risk_difference_per_1000", "ratio", "continuous_mid"}:
        return None
    important_benefit = as_float(result.get("fallback_benefit"))
    important_harm = as_float(result.get("fallback_harm"))
    fallback_mid = as_float(result.get("fallback_mid"))
    if fallback_mid is None:
        fallback_mid = as_float(result.get("minimal_important_difference"))
    outcome_direction = normalize_outcome_direction(result.get("outcome_direction"))
    if scale in {"absolute_risk_difference_per_1000", "continuous_mid"} and fallback_mid is not None:
        if important_benefit is None or important_harm is None:
            important_benefit, important_harm = directional_thresholds_from_mid(
                mid=fallback_mid,
                outcome_direction=outcome_direction,
            )
    if scale == "ratio":
        important_benefit, important_harm = directional_ratio_thresholds(outcome_direction=outcome_direction)
    validation_error = threshold_validation_error(
        scale=scale,
        important_benefit=important_benefit,
        important_harm=important_harm,
    )
    if validation_error is not None:
        return None
    return {
        "threshold_found": True,
        "threshold_scale": scale,
        "important_benefit": important_benefit,
        "important_harm": important_harm,
        "minimal_important_difference": fallback_mid,
        "outcome_type": str(result.get("outcome_type") or ""),
        "scale_identified": bool(result.get("scale_identified")),
        "scale_name": _noneable_str(result.get("scale_name")),
        "scale_range": _noneable_str(result.get("scale_range")),
        "scale_direction": normalize_outcome_direction(result.get("scale_direction")),
        "threshold_kind": _threshold_kind_from_scale(scale),
        "derivation_type": "llm_reasoned_fallback",
        "threshold_applicability": _normalize_choice(
            result.get("threshold_applicability"),
            allowed={"direct", "indirect", "general_grade_default", "not_applicable"},
            default="general_grade_default",
        ),
        "search_plan": _string_list(result.get("search_plan")),
        "research_workflow": result.get("research_workflow") if isinstance(result.get("research_workflow"), dict) else {},
        "accepted_candidates": _dict_list(result.get("accepted_candidates")),
        "rejected_materials": _dict_list(result.get("rejected_materials")),
        "source_values": result.get("source_values") if isinstance(result.get("source_values"), dict) else {},
        "threshold_derivation": str(result.get("threshold_derivation") or ""),
        "optimal_information_size_notes": str(result.get("optimal_information_size_notes") or ""),
        "source_urls": [str(url) for url in as_list(result.get("source_urls")) if str(url).strip()],
        "source_confidence": "low",
        "outcome_direction": outcome_direction,
        "applicability_notes": str(result.get("fallback_rationale") or result.get("applicability_notes") or ""),
        "threshold_source_type": "llm_reasoned_fallback",
        "threshold_evidence_grade": "llm_reasoned_fallback",
        "threshold_validation_notes": threshold_evidence_validation_notes(result),
        "cache_eligible": False,
        "fallback_used": True,
        "fallback_reason": "llm_reasoned_fallback",
        "threshold_valid": True,
        "threshold_validation_error": None,
        "llm_raw_threshold": result,
    }


def normalize_outcome_direction(value: Any) -> str:
    normalized = norm_text(value)
    aliases = {
        "higher_is_better": "higher_is_better",
        "higher_better": "higher_is_better",
        "lower_is_better": "lower_is_better",
        "lower_better": "lower_is_better",
        "higher_is_worse": "higher_is_worse",
        "higher_worse": "higher_is_worse",
        "lower_is_worse": "lower_is_worse",
        "lower_worse": "lower_is_worse",
    }
    return aliases.get(normalized, "unknown")


def continuous_thresholds_from_mid(*, mid: float) -> tuple[float, float]:
    magnitude = abs(mid)
    return -magnitude, magnitude


def directional_thresholds_from_mid(*, mid: float, outcome_direction: str) -> tuple[float, float]:
    magnitude = abs(mid)
    if outcome_direction in {"higher_is_better", "lower_is_worse"}:
        return magnitude, -magnitude
    return -magnitude, magnitude


def directional_ratio_thresholds(*, outcome_direction: str) -> tuple[float, float]:
    if outcome_direction in {"higher_is_better", "lower_is_worse"}:
        return RATIO_IMPORTANT_HARM, RATIO_IMPORTANT_BENEFIT
    return RATIO_IMPORTANT_BENEFIT, RATIO_IMPORTANT_HARM


def threshold_validation_error(
    *,
    scale: str,
    important_benefit: float | None,
    important_harm: float | None,
) -> str | None:
    if scale == "absolute_risk_difference_per_1000":
        if important_benefit is None or important_harm is None:
            return "missing_absolute_threshold_side"
        if not (min(important_benefit, important_harm) < 0 < max(important_benefit, important_harm)):
            return "absolute_threshold_must_straddle_zero"
    if scale == "ratio":
        if important_benefit is None or important_harm is None:
            return "missing_ratio_threshold_side"
        if not (min(important_benefit, important_harm) < 1 < max(important_benefit, important_harm)):
            return "ratio_threshold_must_straddle_one"
    if scale == "continuous_mid":
        if important_benefit is None or important_harm is None:
            return "missing_continuous_threshold_side"
        if not (min(important_benefit, important_harm) < 0 < max(important_benefit, important_harm)):
            return "continuous_threshold_must_straddle_zero"
    return None


def threshold_evidence_validation_notes(result: dict[str, Any]) -> list[str]:
    """Validate that source-backed numbers are decision thresholds, not observed results."""
    notes: list[str] = []
    derivation_type = _normalize_choice(
        result.get("derivation_type"),
        allowed={"direct_source", "derived_from_source", "llm_reasoned_fallback", "unavailable"},
        default="unavailable",
    )
    if derivation_type not in {"direct_source", "derived_from_source"}:
        return notes

    candidate_text = " ".join(
        [
            str(result.get("threshold_derivation") or ""),
            str(result.get("applicability_notes") or ""),
            " ".join(str(item.get("why_usable") or "") for item in _dict_list(result.get("accepted_candidates"))),
            " ".join(str(item.get("value_found") or "") for item in _dict_list(result.get("accepted_candidates"))),
        ]
    ).lower()
    candidate_types = {
        norm_text(item.get("candidate_type"))
        for item in _dict_list(result.get("accepted_candidates"))
        if item.get("candidate_type") is not None
    }
    rejected_reasons = {
        norm_text(item.get("rejection_reason"))
        for item in _dict_list(result.get("rejected_materials"))
        if item.get("rejection_reason") is not None
    }
    accepted_threshold_types = {"mid", "absolute_risk_difference", "ratio", "ois", "sample_size_assumption"}
    has_threshold_language = any(term in candidate_text for term in DIRECT_THRESHOLD_TERMS)
    has_non_threshold_language = any(term in candidate_text for term in NON_THRESHOLD_TERMS)
    has_accepted_threshold_type = bool(candidate_types & accepted_threshold_types)

    if derivation_type == "direct_source" and not (has_threshold_language or has_accepted_threshold_type):
        notes.append("rejected_direct_source_without_decision_threshold_signal")
    if derivation_type == "derived_from_source" and not (has_threshold_language or has_accepted_threshold_type):
        notes.append("rejected_derived_source_without_prespecified_important_difference_signal")
    if has_non_threshold_language and not has_threshold_language:
        notes.append("rejected_observed_or_descriptive_numeric_material")
    if "observed_effect" in candidate_types:
        notes.append("rejected_observed_effect_as_accepted_candidate")
    if "observed_effect" in rejected_reasons and not (has_threshold_language or has_accepted_threshold_type):
        notes.append("observed_effect_material_rejected")
    return notes


def threshold_evidence_grade(
    *,
    derivation_type: str,
    applicability: str,
    confidence: str,
    validation_notes: list[str],
) -> str:
    if any(note.startswith("rejected_") for note in validation_notes):
        return "unavailable"
    if derivation_type == "direct_source" and applicability == "direct" and confidence in {"high", "medium"}:
        return "source_backed_direct"
    if derivation_type == "derived_from_source" and applicability in {"direct", "indirect"} and confidence in {"high", "medium"}:
        return "source_backed_derived"
    if applicability == "general_grade_default":
        return "general_grade_default"
    if applicability == "indirect":
        return "source_backed_indirect"
    return "source_backed_low_confidence"


def _is_generic_grade_ratio_default(*, scale: str, important_benefit: float | None, important_harm: float | None) -> bool:
    if scale != "ratio" or important_benefit is None or important_harm is None:
        return False
    low = min(important_benefit, important_harm)
    high = max(important_benefit, important_harm)
    return abs(low - RATIO_IMPORTANT_BENEFIT) < 1e-9 and abs(high - RATIO_IMPORTANT_HARM) < 1e-9


def _threshold_kind_from_scale(scale: str) -> str:
    if scale == "absolute_risk_difference_per_1000":
        return "absolute_risk_difference"
    if scale == "ratio":
        return "ratio"
    if scale == "continuous_mid":
        return "continuous_mid"
    return "unavailable"


def _normalize_choice(value: Any, *, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def _noneable_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in as_list(value) if str(item).strip()]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in as_list(value) if isinstance(item, dict)]
