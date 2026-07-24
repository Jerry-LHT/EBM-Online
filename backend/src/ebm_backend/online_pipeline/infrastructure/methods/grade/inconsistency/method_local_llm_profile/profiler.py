"""Clinical and methodological heterogeneity profiling for inconsistency."""

from __future__ import annotations

import re
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_local_llm_profile.utils import as_list, first_dict, join_text, norm_text


DIRECT = "direct"
MINOR = "minor_concern"
SERIOUS = "serious_concern"
UNCLEAR = "unclear"

PROFILE_DOMAINS = (
    "population_variability",
    "intervention_variability",
    "comparator_variability",
    "outcome_definition_variability",
    "measurement_tool_variability",
    "timepoint_variability",
    "methodological_variability",
)


def build_clinical_profile(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    context = _profile_context(domain_evidence=domain_evidence, evidence_body=evidence_body)
    study_rows = [row for row in as_list(domain_evidence.get("meta_analysis_data_rows") or evidence_body.get("meta_analysis_data_rows")) if isinstance(row, dict)]
    study_characteristics = [
        row for row in as_list(domain_evidence.get("study_characteristics") or evidence_body.get("study_characteristics")) if isinstance(row, dict)
    ]
    body_signals = _body_signals(context=context, study_rows=study_rows, study_characteristics=study_characteristics)
    profile = {
        "context": context,
        "study_count": len(study_rows),
        "study_profile_count": len(study_characteristics),
        "body_signals": body_signals,
        "domain_ratings": _domain_ratings(body_signals),
        "input_policy": "clean_local_evidence_no_sof_no_web",
    }
    return profile


def clinical_supports_inconsistency(profile: dict[str, Any]) -> bool:
    ratings = first_dict(profile.get("domain_ratings"))
    return any(ratings.get(domain) == SERIOUS for domain in PROFILE_DOMAINS)


def _profile_context(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    setting = first_dict(domain_evidence.get("analysis_setting"), evidence_body.get("analysis_setting"))
    comparison = first_dict(setting.get("comparison"))
    outcome = first_dict(setting.get("outcome"))
    timepoint = first_dict(setting.get("timepoint"))
    population_context = first_dict(domain_evidence.get("population_context"), evidence_body.get("population_context"))
    return {
        "population_context": population_context,
        "comparison": comparison,
        "outcome": outcome,
        "timepoint": timepoint,
        "subgroup": first_dict(setting.get("subgroup")),
        "data_type": domain_evidence.get("data_type") or setting.get("data_type"),
        "effect_measure": domain_evidence.get("effect_measure") or setting.get("effect_measure"),
    }


def _body_signals(*, context: dict[str, Any], study_rows: list[dict[str, Any]], study_characteristics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals = []
    row_outcomes = [_nested_text(row.get("outcome")) for row in study_rows]
    row_timepoints = [_nested_text(first_dict(row.get("outcome")).get("timepoint")) for row in study_rows]
    row_comparisons = [_nested_text(row.get("comparison")) for row in study_rows]
    row_subgroups = [_nested_text(row.get("subgroup")) for row in study_rows]
    target_outcome = str(first_dict(context.get("outcome")).get("label") or "")
    target_timepoint = join_text(*first_dict(context.get("timepoint")).values())
    if _meaningful_variability(row_outcomes, target=target_outcome):
        signals.append(_signal("outcome_definition_variability", "serious", "Study result rows use materially variable outcome labels."))
    if _meaningful_variability(row_timepoints, target=target_timepoint):
        signals.append(_signal("timepoint_variability", "serious", "Study result rows use materially variable follow-up times."))
    if _meaningful_variability(row_comparisons, target=_nested_text(context.get("comparison"))):
        signals.append(_signal("intervention_variability", "serious", "Study result rows use materially variable intervention or comparator labels."))
    if _meaningful_variability(row_subgroups, target=_nested_text(context.get("subgroup"))):
        signals.append(_signal("population_variability", "serious", "Study result rows represent materially variable subgroup levels."))
    characteristics_text = join_text(
        *(join_text(item.get("population"), item.get("intervention_comparator"), item.get("outcomes"), item.get("methods"), item.get("notes")) for item in study_characteristics)
    )
    if _contains_any(characteristics_text, ("different validated instruments", "different scales", "varied instruments", "varied between studies", "assessment tools")):
        signals.append(_signal("measurement_tool_variability", "serious", "Study characteristics indicate variable measurement tools or scales."))
    if _contains_any(characteristics_text, ("different protocols", "protocols for stopping", "different doses", "dose varied", "route varied", "open-label and blinded")):
        signals.append(_signal("methodological_variability", "serious", "Study characteristics indicate protocol or design variability that may explain heterogeneous effects."))
    if _contains_any(characteristics_text, ("children and adults", "adult and child", "severity varied", "prior treatment", "treatment failure", "different populations")):
        signals.append(_signal("population_variability", "serious", "Study characteristics indicate population differences that may modify effects."))
    return _dedupe_signals(signals)


def _domain_ratings(signals: list[dict[str, Any]]) -> dict[str, str]:
    ratings = {domain: DIRECT for domain in PROFILE_DOMAINS}
    for signal in signals:
        domain = str(signal.get("domain") or "")
        severity = str(signal.get("severity") or "")
        if domain in ratings and severity == "serious":
            ratings[domain] = SERIOUS
    return ratings


def _meaningful_variability(values: list[str], *, target: str) -> bool:
    cleaned = [_key_text(value) for value in values if _key_text(value)]
    unique = sorted(set(cleaned))
    if len(unique) <= 1:
        return False
    target_tokens = _tokens(target)
    if target_tokens and all(target_tokens & _tokens(value) for value in unique):
        return False
    return len(unique) >= 2 and any(_tokens(unique[0]) ^ _tokens(value) for value in unique[1:])


def _signal(domain: str, severity: str, rationale: str) -> dict[str, str]:
    return {"domain": domain, "severity": severity, "rationale": rationale}


def _dedupe_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result = []
    for signal in signals:
        key = (str(signal.get("domain") or ""), str(signal.get("rationale") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(signal)
    return result


def _contains_any(text: Any, terms: tuple[str, ...]) -> bool:
    normalized = norm_text(text)
    return any(norm_text(term) in normalized for term in terms)


def _nested_text(value: Any) -> str:
    if isinstance(value, dict):
        return join_text(*value.values())
    return str(value or "")


def _key_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _tokens(value: str) -> set[str]:
    stop = {"and", "or", "the", "with", "without", "versus", "control", "group", "none", "null", "overall"}
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2 and token not in stop}
