"""Convert indirectness benchmark instances into backend method input."""

from __future__ import annotations

import re
from typing import Any


def build_method_instance(instance: dict[str, Any], *, input_policy: str = "analysis_setting") -> dict[str, Any]:
    """Build the normalized method input for indirectness.

    This is the benchmark-specific boundary. It intentionally does not pass
    SoF comments, SoF footnotes, source SoF spans, alignment explanations, or
    SoF intervention/comparison/outcome/timepoint fields to backend methods.
    """

    domain_evidence = _dict_value(instance.get("domain_evidence"))
    evidence_body = _dict_value(instance.get("evidence_body"))
    target_pico = _dict_value(domain_evidence.get("target_pico"))
    review_pico = _dict_value(target_pico.get("review_pico"))
    question_pico = _dict_value(instance.get("question_pico"))
    analysis_setting = _analysis_setting_for_policy(
        instance=instance,
        domain_evidence=domain_evidence,
        evidence_body=evidence_body,
        input_policy=input_policy,
    )
    sof_context = _compact_sof_context(_dict_value(instance.get("sof_context"), domain_evidence.get("sof_context")))
    review_question = _review_question(
        question_text=instance.get("question_text"),
        question_pico=question_pico,
        review_pico=review_pico,
        population_fallback=sof_context.get("population_text"),
    )
    synthesis_target = _synthesis_target(
        review_question=review_question,
        question_text=instance.get("question_text"),
        analysis_setting=analysis_setting,
    )
    included_study_evidence = _included_study_evidence(
        instance=instance,
        domain_evidence=domain_evidence,
        evidence_body=evidence_body,
    )
    method_domain_evidence = {
        "input_policy": f"benchmark_indirectness_v4_review_synthesis_study_{input_policy}_allowed_fields_only",
        "review_question": review_question,
        "synthesis_target": synthesis_target,
        "included_study_evidence": included_study_evidence,
        "review_scope_pico": review_question,
        "synthesis_target_pico": synthesis_target,
        "target_question": _legacy_target_question(
            review_question=review_question,
            synthesis_target=synthesis_target,
        ),
        "evidence_found": included_study_evidence,
        "population_context": {
            "text": _scope_text(review_question.get("population")),
            "source": review_question.get("population_source"),
        },
        "analysis_setting": analysis_setting,
        "included_study_ids": included_study_evidence["included_study_ids"],
        "study_characteristics": included_study_evidence["study_characteristics"],
        "study_characteristics_missing_study_ids": included_study_evidence["study_characteristics_missing_study_ids"],
        "study_result_rows": included_study_evidence["study_result_rows"],
    }
    return {
        "instance_id": instance.get("instance_id"),
        "sof_row_id": instance.get("sof_row_id"),
        "review_id": instance.get("review_id"),
        "domain": instance.get("domain"),
        "question_pico": {"population": _question_population_list(question_pico)},
        "domain_evidence": method_domain_evidence,
        "evidence_body": {
            "review_question": method_domain_evidence["review_question"],
            "synthesis_target": method_domain_evidence["synthesis_target"],
            "included_study_evidence": method_domain_evidence["included_study_evidence"],
            "analysis_setting": method_domain_evidence["analysis_setting"],
            "review_scope_pico": method_domain_evidence["review_scope_pico"],
            "synthesis_target_pico": method_domain_evidence["synthesis_target_pico"],
            "target_question": method_domain_evidence["target_question"],
            "evidence_found": method_domain_evidence["evidence_found"],
            "included_study_ids": method_domain_evidence["included_study_ids"],
            "study_characteristics": method_domain_evidence["study_characteristics"],
            "study_characteristics_missing_study_ids": method_domain_evidence["study_characteristics_missing_study_ids"],
            "study_result_rows": method_domain_evidence["study_result_rows"],
        },
    }


def _review_question(
    *,
    question_text: Any,
    question_pico: dict[str, Any],
    review_pico: dict[str, Any],
    population_fallback: Any,
) -> dict[str, Any]:
    population = _scope_items(question_pico=question_pico, review_pico=review_pico, key="population", fallback_key="P")
    population_source = "question_pico.population" if population else "sof_population_fallback"
    if not population:
        fallback = _clean_text(population_fallback)
        population = [fallback] if fallback else []
    return {
        "question_text": _clean_text(question_text),
        "population": population,
        "population_source": population_source if population else "missing",
        "intervention": _scope_items(question_pico=question_pico, review_pico=review_pico, key="intervention", fallback_key="I"),
        "comparator": _scope_items(question_pico=question_pico, review_pico=review_pico, key="comparison", fallback_key="C"),
        "outcome": _scope_items(question_pico=question_pico, review_pico=review_pico, key="outcome", fallback_key="O"),
    }


def _synthesis_target(
    *,
    review_question: dict[str, Any],
    question_text: Any,
    analysis_setting: dict[str, Any],
) -> dict[str, Any]:
    comparison = _dict_value(analysis_setting.get("comparison"))
    outcome = _dict_value(analysis_setting.get("outcome"))
    timepoint = _dict_value(analysis_setting.get("timepoint"))
    subgroup = _dict_value(analysis_setting.get("subgroup"))
    return {
        "question_text": _clean_text(question_text),
        "population": _target_value(_scope_text(review_question.get("population")), review_question.get("population_source")),
        "intervention": _target_value(comparison.get("experimental"), "analysis_setting.comparison.experimental"),
        "comparator": _target_value(comparison.get("comparator"), "analysis_setting.comparison.comparator"),
        "outcome": {
            "value": _clean_text(outcome.get("label")),
            "source": "analysis_setting.outcome.label",
            "measure": _clean_text(outcome.get("measure")),
            "benefit_direction": _clean_text(outcome.get("benefit_direction")),
            "data_type": _clean_text(analysis_setting.get("data_type")),
            "effect_measure": _clean_text(analysis_setting.get("effect_measure")),
        },
        "timepoint": _target_value(_join_nonempty(timepoint.get("label"), timepoint.get("window")), "analysis_setting.timepoint"),
        "subgroup": _target_value(subgroup.get("level"), _clean_text(subgroup.get("source")) or "analysis_setting.subgroup"),
        "setting": _target_value("", "not_provided"),
    }


def _sof_display_context(sof_context: dict[str, Any]) -> dict[str, str]:
    return {
        "population": sof_context.get("population_text") or "",
        "intervention": sof_context.get("intervention_text") or "",
        "comparator": sof_context.get("comparison_text") or "",
        "outcome": sof_context.get("outcome_name") or "",
        "timepoint": sof_context.get("timepoint_text") or "",
        "setting": sof_context.get("setting_text") or "",
        "participants": sof_context.get("participants_text") or "",
        "studies": sof_context.get("studies_text") or "",
        "table_title": sof_context.get("table_title") or "",
    }


def _legacy_target_question(
    *,
    review_question: dict[str, Any],
    synthesis_target: dict[str, Any],
) -> dict[str, Any]:
    return {
        "question_text": review_question.get("question_text") or synthesis_target.get("question_text"),
        "population": _legacy_domain(
            synthesis_target.get("population"),
            review_question.get("population"),
        ),
        "intervention": _legacy_domain(
            synthesis_target.get("intervention"),
            review_question.get("intervention"),
        ),
        "comparator": _legacy_domain(
            synthesis_target.get("comparator"),
            review_question.get("comparator"),
        ),
        "outcome": _legacy_domain(
            synthesis_target.get("outcome"),
            review_question.get("outcome"),
        ),
        "timepoint": _legacy_domain(synthesis_target.get("timepoint"), []),
        "subgroup": _legacy_domain(synthesis_target.get("subgroup"), []),
        "setting": _legacy_domain(synthesis_target.get("setting"), []),
    }


def _legacy_domain(target_item: Any, scope_items: Any) -> dict[str, Any]:
    item = _dict_value(target_item)
    return {
        "primary": _clean_text(item.get("value")),
        "source": _clean_text(item.get("source")),
        "review_pico": _list_value(scope_items),
        "question_pico": _list_value(scope_items),
        "measure": item.get("measure"),
        "data_type": item.get("data_type"),
        "effect_measure": item.get("effect_measure"),
        "benefit_direction": item.get("benefit_direction"),
    }


def _target_value(value: Any, source: Any) -> dict[str, str]:
    return {"value": _clean_text(value), "source": _clean_text(source)}


def _scope_items(*, question_pico: dict[str, Any], review_pico: dict[str, Any], key: str, fallback_key: str) -> list[str]:
    question_items = _pico_list(question_pico, key, fallback_key)
    if question_items:
        return question_items
    return _pico_list(review_pico, key, fallback_key)


def _scope_text(value: Any) -> str:
    return ", ".join(_list_value(value))


def _included_study_evidence(
    *,
    instance: dict[str, Any],
    domain_evidence: dict[str, Any],
    evidence_body: dict[str, Any],
) -> dict[str, Any]:
    return {
        "included_study_ids": _list_value(
            domain_evidence.get("included_study_ids")
            or instance.get("included_study_ids")
            or evidence_body.get("included_study_ids")
        ),
        "study_characteristics": [
            _compact_study_characteristics(item)
            for item in _list_value(domain_evidence.get("study_characteristics"))
            if isinstance(item, dict)
        ],
        "study_characteristics_missing_study_ids": _list_value(
            domain_evidence.get("study_characteristics_missing_study_ids")
        ),
        "study_result_rows": [
            _compact_study_result_row(item)
            for item in _list_value(instance.get("study_result_rows") or evidence_body.get("study_result_rows"))
            if isinstance(item, dict)
        ],
    }


def _compact_sof_context(sof_context: dict[str, Any]) -> dict[str, str]:
    return {
        "population_text": _clean_text(sof_context.get("population_text")),
        "intervention_text": _clean_text(sof_context.get("intervention_text")),
        "comparison_text": _clean_text(sof_context.get("comparison_text")),
        "outcome_name": _clean_text(sof_context.get("outcome_name")),
        "timepoint_text": _clean_text(sof_context.get("timepoint_text")),
        "setting_text": _clean_text(sof_context.get("setting_text")),
        "participants_text": _clean_text(sof_context.get("participants_text")),
        "studies_text": _clean_text(sof_context.get("studies_text")),
        "table_title": _clean_text(sof_context.get("table_title")),
    }


def _analysis_setting_for_policy(
    *,
    instance: dict[str, Any],
    domain_evidence: dict[str, Any],
    evidence_body: dict[str, Any],
    input_policy: str,
) -> dict[str, Any]:
    if input_policy == "sof_context":
        return _compact_sof_context_as_analysis_setting(_dict_value(instance.get("sof_context")))
    if input_policy != "analysis_setting":
        raise ValueError("input_policy must be one of: analysis_setting, sof_context")
    return _compact_analysis_setting(
        _dict_value(instance.get("analysis_setting"), domain_evidence.get("analysis_setting"), evidence_body.get("analysis_setting"))
    )


def _compact_sof_context_as_analysis_setting(sof_context: dict[str, Any]) -> dict[str, Any]:
    intervention = _clean_text(sof_context.get("intervention_text"))
    comparison = _clean_text(sof_context.get("comparison_text"))
    outcome = _clean_text(sof_context.get("outcome_name"))
    timepoint = _clean_text(sof_context.get("timepoint_text"))
    setting = _clean_text(sof_context.get("setting_text"))
    population = _clean_text(sof_context.get("population_text"))
    return {
        "analysis_name": outcome,
        "analysis_group_name": _clean_text(sof_context.get("table_title")),
        "comparison": {
            "experimental": intervention,
            "comparator": comparison,
            "text": _join_nonempty(intervention, "versus", comparison) if intervention or comparison else "",
        },
        "outcome": {
            "label": outcome,
            "measure": None,
            "benefit_direction": None,
        },
        "timepoint": {
            "label": timepoint,
            "window": None,
        },
        "subgroup": {
            "level": setting,
            "subgroup_number": None,
            "source": "sof_context.setting_text" if setting else None,
        },
        "data_type": None,
        "effect_measure": None,
        "sof_population_hint": population,
        "source": "sof_context_display_fields_only",
    }


def _compact_analysis_setting(setting: dict[str, Any]) -> dict[str, Any]:
    comparison = _dict_value(setting.get("comparison"))
    outcome = _dict_value(setting.get("outcome"))
    timepoint = _dict_value(setting.get("timepoint"))
    subgroup = _dict_value(setting.get("subgroup"))
    return {
        "analysis_name": setting.get("analysis_name"),
        "analysis_group_name": setting.get("analysis_group_name"),
        "comparison": {
            "experimental": comparison.get("experimental"),
            "comparator": comparison.get("comparator"),
            "text": comparison.get("text"),
        },
        "outcome": {
            "label": outcome.get("label"),
            "measure": outcome.get("measure"),
            "benefit_direction": outcome.get("benefit_direction"),
        },
        "timepoint": {
            "label": timepoint.get("label"),
            "window": timepoint.get("window"),
        },
        "subgroup": {
            "level": subgroup.get("level"),
            "subgroup_number": subgroup.get("subgroup_number"),
            "source": subgroup.get("source"),
        },
        "data_type": setting.get("data_type"),
        "effect_measure": setting.get("effect_measure"),
    }


def _compact_study_characteristics(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_id": item.get("study_id"),
        "matched_study_id": item.get("matched_study_id"),
        "population": _clean_text(item.get("population")),
        "intervention_comparator": _clean_text(item.get("intervention_comparator")),
        "outcomes": _clean_text(item.get("outcomes")),
        "methods": _clean_text(item.get("methods")),
        "notes": _clean_text(item.get("notes")),
        "source": item.get("source"),
    }


def _compact_study_result_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_id": item.get("study_id"),
        "study_year": item.get("study_year"),
        "data_type": item.get("data_type"),
        "comparison": _dict_value(item.get("comparison")),
        "outcome": _dict_value(item.get("outcome")),
        "subgroup": _dict_value(item.get("subgroup")),
        "result_data": _dict_value(item.get("result_data")),
        "analysis_note": None,
    }


def _synthesis_evidence_contrast(
    *,
    review_scope_pico: dict[str, Any],
    synthesis_target_pico: dict[str, Any],
    sof_display_context: dict[str, Any],
    evidence_found: dict[str, Any],
) -> dict[str, Any]:
    studies = [item for item in _list_value(evidence_found.get("study_characteristics")) if isinstance(item, dict)]
    rows = [item for item in _list_value(evidence_found.get("study_result_rows")) if isinstance(item, dict)]
    domains = {
        "population": _contrast_domain(
            target=_target_text(synthesis_target_pico, "population"),
            review_scope=_scope_text(review_scope_pico.get("population")),
            sof_context=sof_display_context.get("population"),
            evidence_terms=_dedup_clipped([study.get("population") for study in studies]),
            possible_limits=_population_limit_terms(studies),
        ),
        "intervention": _contrast_domain(
            target=_target_text(synthesis_target_pico, "intervention"),
            review_scope=_scope_text(review_scope_pico.get("intervention")),
            sof_context=sof_display_context.get("intervention"),
            evidence_terms=_dedup_clipped(
                [study.get("intervention_comparator") for study in studies]
                + [_comparison_text(row, "experimental") for row in rows]
            ),
            possible_limits=_intervention_limit_terms(studies, rows),
        ),
        "comparator": _contrast_domain(
            target=_target_text(synthesis_target_pico, "comparator"),
            review_scope=_scope_text(review_scope_pico.get("comparator")),
            sof_context=sof_display_context.get("comparator"),
            evidence_terms=_dedup_clipped(
                [study.get("intervention_comparator") for study in studies]
                + [_comparison_text(row, "comparator") for row in rows]
            ),
            possible_limits=_comparator_limit_terms(studies, rows),
        ),
        "direct_comparison": _contrast_domain(
            target=_join_nonempty(_target_text(synthesis_target_pico, "intervention"), "versus", _target_text(synthesis_target_pico, "comparator")),
            review_scope=_join_nonempty(_scope_text(review_scope_pico.get("intervention")), "versus", _scope_text(review_scope_pico.get("comparator"))),
            sof_context=_join_nonempty(sof_display_context.get("intervention"), "versus", sof_display_context.get("comparator")),
            evidence_terms=_dedup_clipped([_row_direct_comparison(row) for row in rows] + [study.get("intervention_comparator") for study in studies]),
            possible_limits=_direct_comparison_limit_terms(rows),
        ),
        "outcome": _contrast_domain(
            target=_target_text(synthesis_target_pico, "outcome"),
            review_scope=_scope_text(review_scope_pico.get("outcome")),
            sof_context=sof_display_context.get("outcome"),
            evidence_terms=_dedup_clipped(
                [study.get("outcomes") for study in studies]
                + [_outcome_text(row) for row in rows]
            ),
            possible_limits=_outcome_limit_terms(studies, rows),
        ),
        "timepoint": _contrast_domain(
            target=_target_text(synthesis_target_pico, "timepoint"),
            review_scope="",
            sof_context=sof_display_context.get("timepoint"),
            evidence_terms=_dedup_clipped([_outcome_timepoint_text(row) for row in rows] + [study.get("outcomes") for study in studies]),
            possible_limits=_timepoint_limit_terms(studies, rows),
        ),
        "setting": _contrast_domain(
            target=_target_text(synthesis_target_pico, "setting"),
            review_scope="",
            sof_context=sof_display_context.get("setting"),
            evidence_terms=_dedup_clipped([study.get("methods") for study in studies] + [study.get("notes") for study in studies]),
            possible_limits=_setting_limit_terms(studies, rows),
        ),
    }
    return {
        "derivation": "deterministic_from_allowed_normalized_input_only",
        "role": "candidate target-vs-evidence contrast; not an author rationale and not an automatic downgrade rule",
        "domains": domains,
        "overall": {
            "study_count": len(studies),
            "result_row_count": len(rows),
            "missing_study_characteristics_count": len(_list_value(evidence_found.get("study_characteristics_missing_study_ids"))),
            "domains_with_possible_limits": [
                domain
                for domain, item in domains.items()
                if isinstance(item, dict) and item.get("possible_limits")
            ],
        },
    }


def _contrast_domain(
    *,
    target: Any,
    review_scope: Any,
    sof_context: Any,
    evidence_terms: list[str],
    possible_limits: list[str],
) -> dict[str, Any]:
    return {
        "target": _clean_text(target),
        "review_scope": _clean_text(review_scope),
        "sof_display_fallback": _clean_text(sof_context),
        "evidence_terms": evidence_terms[:8],
        "coverage_summary": _coverage_summary(evidence_terms),
        "possible_limits": possible_limits[:8],
    }


def _target_text(pico: dict[str, Any], key: str) -> str:
    item = _dict_value(pico.get(key))
    parts = [item.get("value")]
    if key == "outcome":
        parts.extend([item.get("measure"), item.get("data_type"), item.get("effect_measure")])
    return _join_nonempty(*parts)


def _dedup_clipped(values: list[Any], *, limit: int = 220) -> list[str]:
    seen: set[str] = set()
    items = []
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        clipped = text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
        key = clipped.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(clipped)
    return items


def _coverage_summary(evidence_terms: list[str]) -> str:
    if not evidence_terms:
        return "No study-level terms available in normalized input."
    if len(evidence_terms) == 1:
        return evidence_terms[0]
    return f"{len(evidence_terms)} distinct study/result-row terms available; see evidence_terms."


def _population_limit_terms(studies: list[dict[str, Any]]) -> list[str]:
    terms = _text_blob(studies, ("population", "methods", "notes"))
    return _keyword_limits(
        terms,
        {
            "age_or_life_stage_restriction": ("adult", "adults", "children", "child", "infant", "adolescent", "elderly", "aged", "older"),
            "severity_or_risk_restriction": ("severe", "severity", "moderate", "mild", "high risk", "low risk", "advanced", "refractory", "chronic", "acute"),
            "eligibility_restriction": ("included", "excluded", "exclusion", "only", "selected", "eligible", "ineligible"),
            "comorbidity_or_special_population": ("comorbid", "pregnan", "renal", "cardiac", "diabet", "immun", "cancer", "hiv"),
        },
    )


def _intervention_limit_terms(studies: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[str]:
    terms = _join_nonempty(
        _text_blob(studies, ("intervention_comparator", "methods", "notes")),
        _text_blob(rows, ("comparison",)),
    )
    return _keyword_limits(
        terms,
        {
            "specific_variant_dose_or_schedule": ("dose", "dosage", "mg", "mcg", "weekly", "daily", "duration", "regimen", "schedule", "route"),
            "intervention_package_or_cointervention": ("plus", "combined", "combination", "in addition", "co-intervention", "cointervention", "package"),
            "delivery_provider_or_expertise": ("provider", "nurse", "specialist", "surgeon", "training", "supervised", "clinic", "hospital"),
            "device_drug_or_procedure_variant": ("device", "drug", "surgery", "procedure", "technique", "formulation", "protocol"),
        },
    )


def _comparator_limit_terms(studies: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[str]:
    terms = _join_nonempty(
        _text_blob(studies, ("intervention_comparator", "methods", "notes")),
        _text_blob(rows, ("comparison",)),
    )
    return _keyword_limits(
        terms,
        {
            "usual_care_or_practice_context": ("usual care", "standard care", "routine care", "practice", "control", "placebo", "no treatment"),
            "active_comparator_variant": ("active", "alternative", "different", "another", "versus"),
        },
    )


def _direct_comparison_limit_terms(rows: list[dict[str, Any]]) -> list[str]:
    comparisons = [_row_direct_comparison(row).lower() for row in rows]
    if not comparisons:
        return ["no_result_row_comparison_terms"]
    if any("network" in text or "indirect" in text for text in comparisons):
        return ["row_terms_suggest_indirect_or_network_comparison"]
    return []


def _outcome_limit_terms(studies: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[str]:
    terms = _join_nonempty(_text_blob(studies, ("outcomes", "methods", "notes")), _text_blob(rows, ("outcome",)))
    return _keyword_limits(
        terms,
        {
            "surrogate_proxy_or_intermediate": ("surrogate", "proxy", "intermediate", "biomarker", "laboratory", "radiographic", "physiologic"),
            "measurement_tool_or_definition": ("scale", "score", "questionnaire", "instrument", "definition", "defined", "assessed", "measured"),
            "composite_or_non_patient_important": ("composite", "combined endpoint", "endpoint", "symptom", "quality of life", "qol"),
        },
    )


def _timepoint_limit_terms(studies: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[str]:
    terms = _join_nonempty(_text_blob(studies, ("outcomes", "methods", "notes")), _text_blob(rows, ("outcome",)))
    limits = _keyword_limits(
        terms,
        {
            "follow_up_or_assessment_window_terms": ("follow-up", "follow up", "week", "weeks", "month", "months", "year", "years", "day", "days"),
        },
    )
    windows = _time_windows(terms)
    if len(windows) > 1:
        limits.append("multiple_distinct_time_windows_in_evidence")
    return limits


def _setting_limit_terms(studies: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[str]:
    terms = _text_blob(studies, ("methods", "notes"))
    limits = _keyword_limits(
        terms,
        {
            "care_setting_or_resource_context": ("hospital", "clinic", "primary care", "community", "specialist", "tertiary", "resource"),
            "geography_or_health_system_context": ("country", "countries", "multicentre", "multicenter", "single centre", "single center"),
            "technology_or_practice_era_terms": ("technology", "practice", "modern", "historical", "before", "older"),
        },
    )
    years = sorted({year for year in (_safe_int(row.get("study_year")) for row in rows) if year is not None})
    if years:
        if min(years) < 2000:
            limits.append("older_study_era_pre_2000")
        if max(years) - min(years) >= 15:
            limits.append("wide_study_era_range")
    return limits


def _keyword_limits(text: str, groups: dict[str, tuple[str, ...]]) -> list[str]:
    lowered = text.lower()
    return [label for label, keywords in groups.items() if any(keyword in lowered for keyword in keywords)]


def _text_blob(items: list[dict[str, Any]], keys: tuple[str, ...]) -> str:
    parts = []
    for item in items:
        for key in keys:
            value = item.get(key)
            if isinstance(value, dict):
                parts.append(_jsonish_text(value))
            else:
                parts.append(_clean_text(value))
    return _join_nonempty(*parts)


def _jsonish_text(value: dict[str, Any]) -> str:
    parts = []
    for item in value.values():
        if isinstance(item, dict):
            parts.append(_jsonish_text(item))
        elif isinstance(item, list):
            parts.extend(_clean_text(part) for part in item)
        else:
            parts.append(_clean_text(item))
    return _join_nonempty(*parts)


def _comparison_text(row: dict[str, Any], key: str) -> str:
    comparison = _dict_value(row.get("comparison"))
    return _clean_text(comparison.get(key) or comparison.get("text"))


def _row_direct_comparison(row: dict[str, Any]) -> str:
    comparison = _dict_value(row.get("comparison"))
    return _join_nonempty(comparison.get("experimental"), "versus", comparison.get("comparator")) or _clean_text(comparison.get("text"))


def _outcome_text(row: dict[str, Any]) -> str:
    outcome = _dict_value(row.get("outcome"))
    return _join_nonempty(outcome.get("label"), outcome.get("measure"), outcome.get("timepoint"))


def _outcome_timepoint_text(row: dict[str, Any]) -> str:
    outcome = _dict_value(row.get("outcome"))
    return _clean_text(outcome.get("timepoint") or outcome.get("label"))


def _time_windows(text: str) -> set[str]:
    return {match.group(0).lower() for match in re.finditer(r"\b\d+\s*(?:day|days|week|weeks|month|months|year|years)\b", text, re.I)}


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _question_population_list(pico: dict[str, Any]) -> list[str]:
    return _pico_list(pico, "population", "P")


def _pico_list(pico: dict[str, Any], key: str, fallback_key: str) -> list[str]:
    value = pico.get(key)
    if value is None:
        value = pico.get(fallback_key)
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    if _clean_text(value):
        return [_clean_text(value)]
    return []


def _pico_list_text(pico: dict[str, Any], key: str, fallback_key: str) -> str:
    return ", ".join(_pico_list(pico, key, fallback_key))


def _first_text_source(*candidates: tuple[str, Any]) -> tuple[str, str]:
    for source, value in candidates:
        text = _clean_text(value)
        if text:
            return text, source
    return "", "missing"


def _dict_value(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _join_nonempty(*values: Any) -> str:
    return " ".join(str(value) for value in values if str(value or "").strip())
