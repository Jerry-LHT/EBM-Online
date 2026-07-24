"""Evidence extraction for GRADE imprecision methods."""

from __future__ import annotations

import re
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.utils import as_float, as_int, as_list, first_dict


CONTEXTUALIZATION_MODE_SYSTEMATIC_REVIEW = "systematic_review_minimally_contextualized"


def build_setting_context(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    setting = first_dict(domain_evidence.get("analysis_setting"), evidence_body.get("analysis_setting"))
    estimate = first_dict(domain_evidence.get("effect_estimate"), evidence_body.get("effect_estimate"))
    outcome = first_dict(setting.get("outcome"))
    comparison = first_dict(setting.get("comparison"))
    timepoint = first_dict(setting.get("timepoint"))
    population_scope = first_dict(setting.get("population_scope"))
    return {
        "population": population_scope.get("label"),
        "comparison": comparison.get("text") or _join_nonempty(comparison.get("experimental"), comparison.get("comparator")),
        "outcome": outcome.get("label"),
        "timepoint": timepoint.get("label") or timepoint.get("window"),
        "data_type": domain_evidence.get("data_type") or estimate.get("data_type") or setting.get("data_type"),
        "effect_measure": domain_evidence.get("effect_measure") or estimate.get("effect_measure") or setting.get("effect_measure"),
        "contextualization_mode": CONTEXTUALIZATION_MODE_SYSTEMATIC_REVIEW,
        "input_policy": "analysis_setting_and_meta_analysis_only",
        "sof_context_used": False,
        "question_text_used": False,
        "question_pico_used": False,
    }


def build_threshold_research_context(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    """Build the context used for external threshold research.

    This intentionally excludes SoF judgement text, gold rationales, review title/question text,
    and the current effect estimate or confidence interval. When a structured SoF population
    field is supplied by the caller, it is preferred as clinical condition context; question P
    is only a fallback for methods that receive it as part of already-normalized evidence.
    """

    pieces = _threshold_context_pieces(domain_evidence=domain_evidence, evidence_body=evidence_body)
    context = {
        "condition_context": pieces["condition_context"],
        "outcome_concept": pieces["outcome_concept"],
        "outcome_measure_name": pieces["outcome_measure_name"],
        "outcome_scale_range": pieces["outcome_scale_range"],
        "outcome_direction": pieces["outcome_direction"],
        "timepoint_window": pieces["timepoint_window"],
        "outcome_type": pieces["outcome_type"],
        "threshold_scale_context": pieces["threshold_scale_context"],
        "clinical_setting_context": pieces["clinical_setting_context"],
        "intervention_context": pieces["intervention_context"],
        "comparator_context": pieces["comparator_context"],
        "contextualization_mode": pieces["contextualization_mode"],
        "threshold_context_variant": pieces["threshold_context_variant"],
    }
    context["threshold_research_key"] = threshold_research_key(context)
    return context


def build_threshold_audit_context(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    pieces = _threshold_context_pieces(domain_evidence=domain_evidence, evidence_body=evidence_body)
    return {
        "condition_context_source": pieces["condition_context_source"],
        "contextualization_mode": pieces["contextualization_mode"],
        "contextualization_mode_source": "method_default",
        "input_policy": "analysis_setting_plus_question_population_or_sof_population_no_question_text_no_effect_estimate",
        "sof_context_used": pieces["sof_population_used"],
        "sof_population_text_used_for_threshold_research": pieces["sof_population_used"],
        "question_population_used_for_threshold_research": pieces["question_population_used"],
        "question_text_used_for_threshold_research": False,
        "question_pico_used_for_threshold_research": pieces["question_population_used"],
        "effect_estimate_used_for_threshold_research": False,
        "threshold_research_overrides_used": bool(pieces["threshold_research_override_keys"]),
        "threshold_research_override_keys": pieces["threshold_research_override_keys"],
    }


def threshold_research_key(context: dict[str, Any]) -> str:
    parts = [
        ("condition", context.get("condition_context")),
        ("outcome", context.get("outcome_concept")),
        ("timepoint", context.get("timepoint_window")),
        ("scale", context.get("threshold_scale_context")),
    ]
    if context.get("threshold_context_variant"):
        parts.extend(
            [
                ("variant", context.get("threshold_context_variant")),
                ("setting", context.get("clinical_setting_context")),
                ("intervention", context.get("intervention_context")),
                ("comparator", context.get("comparator_context")),
            ]
        )
    return "||".join(f"{name}:{_key_text(value)}" for name, value in parts)


def threshold_scale_context(*, data_type: Any, outcome_measure: Any = None) -> str:
    data_type_text = _key_text(data_type)
    measure_text = _key_text(outcome_measure)
    if "continuous" in data_type_text:
        return _join_key_parts("continuous", measure_text)
    if "dichotomous" in data_type_text or "binary" in data_type_text:
        return "dichotomous_absolute_risk"
    if "time_to_event" in data_type_text or "survival" in data_type_text:
        return "time_to_event"
    return _join_key_parts(data_type_text or "unknown", measure_text)


def _threshold_context_pieces(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    setting = first_dict(domain_evidence.get("analysis_setting"), evidence_body.get("analysis_setting"))
    sof_context = first_dict(domain_evidence.get("sof_context"), evidence_body.get("sof_context"))
    question_pico = first_dict(domain_evidence.get("question_pico"), evidence_body.get("question_pico"), evidence_body.get("target_pico"))
    overrides = first_dict(domain_evidence.get("threshold_research_overrides"), evidence_body.get("threshold_research_overrides"))
    outcome = first_dict(setting.get("outcome"))
    comparison = first_dict(setting.get("comparison"))
    timepoint = first_dict(setting.get("timepoint"))
    population_scope = first_dict(setting.get("population_scope"))
    data_type = domain_evidence.get("data_type") or setting.get("data_type")
    question_population = _informative_population(_question_population_text(question_pico))
    analysis_population = _informative_population(population_scope.get("label"))
    sof_population = _informative_population(sof_context.get("population_text"))
    condition_context = sof_population or question_population or analysis_population
    if sof_population is not None:
        condition_context_source = "sof_context.population_text"
    elif question_population is not None:
        condition_context_source = "question_pico.population"
    elif analysis_population is not None:
        condition_context_source = "analysis_setting.population_scope"
    else:
        condition_context_source = "none"
    pieces = {
        "condition_context": condition_context,
        "condition_context_source": condition_context_source,
        "sof_population_used": condition_context_source == "sof_context.population_text",
        "question_population_used": condition_context_source == "question_pico.population",
        "outcome_concept": outcome.get("label") or _analysis_name_without_timepoint(setting.get("analysis_name")),
        "outcome_measure_name": outcome.get("measure"),
        "outcome_scale_range": _outcome_scale_range(outcome.get("measure")),
        "outcome_direction": outcome.get("benefit_direction"),
        "timepoint_window": timepoint.get("window") or timepoint.get("label"),
        "outcome_type": data_type,
        "threshold_scale_context": threshold_scale_context(data_type=data_type, outcome_measure=outcome.get("measure")),
        "clinical_setting_context": None,
        "intervention_context": comparison.get("experimental"),
        "comparator_context": comparison.get("comparator"),
        "contextualization_mode": CONTEXTUALIZATION_MODE_SYSTEMATIC_REVIEW,
        "threshold_context_variant": None,
        "threshold_research_override_keys": [],
    }
    override_keys = _apply_threshold_research_overrides(pieces, overrides)
    if "condition_context" in override_keys:
        pieces["condition_context_source"] = "threshold_research_overrides.condition_context"
        pieces["sof_population_used"] = False
        pieces["question_population_used"] = False
    pieces["threshold_research_override_keys"] = override_keys
    return pieces


def extract_numeric_features(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    estimate = first_dict(domain_evidence.get("effect_estimate"), evidence_body.get("effect_estimate"))
    study_rows = as_list(domain_evidence.get("meta_analysis_data_rows") or evidence_body.get("meta_analysis_data_rows"))
    effect_measure = str(domain_evidence.get("effect_measure") or estimate.get("effect_measure") or "")
    data_type = str(domain_evidence.get("data_type") or estimate.get("data_type") or "")
    effect = _first_float(estimate.get("effect_value"), estimate.get("effect"))
    lower = as_float(estimate.get("ci_lower"))
    upper = as_float(estimate.get("ci_upper"))
    participants = _first_int(domain_evidence.get("participant_count"), estimate.get("participant_count"))
    study_count = _first_int(domain_evidence.get("study_count"), estimate.get("study_count"))
    events = _dichotomous_summary(study_rows)
    features = {
        "data_type": data_type,
        "effect_measure": effect_measure,
        "effect": effect,
        "ci_lower": lower,
        "ci_upper": upper,
        "no_effect": no_effect_line(effect_measure),
        "participant_count": participants,
        "study_count": study_count,
        **events,
    }
    if is_ratio_measure(effect_measure) and lower is not None and upper is not None and events.get("control_event_rate") is not None:
        cer = float(events["control_event_rate"])
        features["absolute_ci_lower_per_1000"] = cer * (lower - 1.0) * 1000.0
        features["absolute_ci_upper_per_1000"] = cer * (upper - 1.0) * 1000.0
        if effect is not None:
            features["absolute_effect_per_1000"] = cer * (effect - 1.0) * 1000.0
    return features


def no_effect_line(effect_measure: str) -> float:
    return 1.0 if is_ratio_measure(effect_measure) else 0.0


def is_ratio_measure(effect_measure: str) -> bool:
    text = effect_measure.lower()
    return any(token in text for token in ("risk ratio", "odds ratio", "hazard ratio", "rate ratio", "ratio", "rr", "or", "hr"))


def _dichotomous_summary(study_rows: list[Any]) -> dict[str, Any]:
    exp_events = exp_total = ctrl_events = ctrl_total = 0
    found = False
    for row in study_rows:
        if not isinstance(row, dict):
            continue
        data = _row_result_data(row)
        values = {
            "experimental_events": as_int(data.get("experimental_events")),
            "experimental_total": as_int(data.get("experimental_total")),
            "control_events": as_int(data.get("control_events")),
            "control_total": as_int(data.get("control_total")),
        }
        if all(value is not None for value in values.values()):
            exp_events += int(values["experimental_events"])
            exp_total += int(values["experimental_total"])
            ctrl_events += int(values["control_events"])
            ctrl_total += int(values["control_total"])
            found = True
    if not found:
        return {
            "total_events": None,
            "experimental_events": None,
            "experimental_total": None,
            "control_events": None,
            "control_total": None,
            "control_event_rate": None,
        }
    return {
        "total_events": exp_events + ctrl_events,
        "experimental_events": exp_events,
        "experimental_total": exp_total,
        "control_events": ctrl_events,
        "control_total": ctrl_total,
        "control_event_rate": (ctrl_events / ctrl_total) if ctrl_total else None,
    }


def _row_result_data(row: dict[str, Any]) -> dict[str, Any]:
    items = as_list(row.get("result_items") or row.get("candidate_results"))
    ready = [
        item
        for item in items
        if isinstance(item, dict)
        and str(item.get("analysis_disposition") or "").strip().lower() == "ready_for_estimate"
        and isinstance(item.get("result_data"), dict)
    ]
    if ready:
        return ready[0]["result_data"]
    for item in items:
        if isinstance(item, dict) and item.get("include_in_estimate") is True and isinstance(item.get("result_data"), dict):
            return item["result_data"]
    return first_dict(row.get("result_data"))


def _first_float(*values: Any) -> float | None:
    for value in values:
        number = as_float(value)
        if number is not None:
            return number
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        number = as_int(value)
        if number is not None:
            return number
    return None


def _join_nonempty(*values: Any) -> str:
    return " versus ".join(str(value) for value in values if value)


def _informative_population(value: Any) -> str | None:
    text = _clean_population_text(value)
    if not text:
        return None
    generic = {"review population", "overall population", "population", "participants", "all participants"}
    return None if text.lower() in generic else text


def _clean_population_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n:;,-")
    text = re.sub(r"\b(were|was|are|is)?\s*included in this review\.?$", "", text, flags=re.IGNORECASE).strip()
    return text.strip(" \t\r\n:;,-")


def _question_population_text(question_pico: dict[str, Any]) -> str | None:
    population = question_pico.get("population")
    if population is None:
        population = question_pico.get("P")
    if isinstance(population, list):
        return ", ".join(str(item).strip() for item in population if str(item).strip())
    if population:
        return str(population)
    return None


def _analysis_name_without_timepoint(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.split("(", 1)[0].strip() or text


def _outcome_scale_range(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"\b\d+(?:\.\d+)?\s*(?:to|-)\s*\d+(?:\.\d+)?\b", text, flags=re.IGNORECASE)
    return match.group(0) if match else None


def _apply_threshold_research_overrides(pieces: dict[str, Any], overrides: dict[str, Any]) -> list[str]:
    allowed = {
        "condition_context",
        "outcome_concept",
        "outcome_measure_name",
        "outcome_scale_range",
        "outcome_direction",
        "timepoint_window",
        "clinical_setting_context",
        "intervention_context",
        "comparator_context",
        "threshold_context_variant",
    }
    used: list[str] = []
    for key in sorted(allowed):
        value = _clean_context_value(overrides.get(key))
        if value is None:
            continue
        pieces[key] = value
        used.append(key)
    return used


def _clean_context_value(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n:;,-")
    return text or None


def _key_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _join_key_parts(*values: str) -> str:
    return "_".join(value.replace(" ", "_") for value in values if value)
