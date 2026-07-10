"""Evidence packaging for the two-step indirectness method."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.common import as_list, first_dict


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clip(value: Any, *, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _build_evidence_package(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    review_question = first_dict(domain_evidence.get("review_question"), evidence_body.get("review_question"))
    synthesis_target = first_dict(domain_evidence.get("synthesis_target"), evidence_body.get("synthesis_target"))
    included_study_evidence = first_dict(
        domain_evidence.get("included_study_evidence"),
        evidence_body.get("included_study_evidence"),
    )
    if review_question or synthesis_target or included_study_evidence:
        return _build_layered_evidence_package(domain_evidence=domain_evidence, evidence_body=evidence_body)
    review_scope_pico = first_dict(domain_evidence.get("review_scope_pico"), evidence_body.get("review_scope_pico"))
    synthesis_target_pico = first_dict(domain_evidence.get("synthesis_target_pico"), evidence_body.get("synthesis_target_pico"))
    sof_display_context = first_dict(domain_evidence.get("sof_display_context"), evidence_body.get("sof_display_context"))
    evidence_found = first_dict(domain_evidence.get("evidence_found"), evidence_body.get("evidence_found"))
    if review_scope_pico or synthesis_target_pico or sof_display_context or evidence_found:
        return _build_official_pico_evidence_package(domain_evidence=domain_evidence, evidence_body=evidence_body)
    target_question = first_dict(domain_evidence.get("target_question"), evidence_body.get("target_question"))
    if target_question or evidence_found:
        return _build_v2_evidence_package(domain_evidence=domain_evidence, evidence_body=evidence_body)
    return _build_legacy_evidence_package(domain_evidence=domain_evidence, evidence_body=evidence_body)


def _build_layered_evidence_package(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    review_question = first_dict(domain_evidence.get("review_question"), evidence_body.get("review_question"))
    synthesis_target = first_dict(domain_evidence.get("synthesis_target"), evidence_body.get("synthesis_target"))
    included_study_evidence = first_dict(
        domain_evidence.get("included_study_evidence"),
        evidence_body.get("included_study_evidence"),
    )
    study_rows = [row for row in as_list(included_study_evidence.get("study_result_rows")) if isinstance(row, dict)]
    study_characteristics = [
        _compact_study(item)
        for item in as_list(included_study_evidence.get("study_characteristics"))
        if isinstance(item, dict)
    ]
    return {
        "input_policy": str(domain_evidence.get("input_policy") or "indirectness_allowed_input_only"),
        "review_question": _compact_review_question(review_question),
        "synthesis_target": _compact_synthesis_target(synthesis_target),
        "included_study_evidence": {
            "included_study_ids": as_list(included_study_evidence.get("included_study_ids")),
            "study_characteristics_missing_study_ids": as_list(
                included_study_evidence.get("study_characteristics_missing_study_ids")
            ),
            "study_count": len(study_characteristics),
            "study_characteristics": study_characteristics,
            "study_result_rows": [_compact_row(row) for row in study_rows],
        },
    }


def _build_official_pico_evidence_package(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    review_scope_pico = first_dict(domain_evidence.get("review_scope_pico"), evidence_body.get("review_scope_pico"))
    synthesis_target_pico = first_dict(domain_evidence.get("synthesis_target_pico"), evidence_body.get("synthesis_target_pico"))
    sof_display_context = first_dict(domain_evidence.get("sof_display_context"), evidence_body.get("sof_display_context"))
    evidence_found = first_dict(domain_evidence.get("evidence_found"), evidence_body.get("evidence_found"))
    study_rows = [row for row in as_list(evidence_found.get("study_result_rows")) if isinstance(row, dict)]
    study_characteristics = [
        _compact_study(item)
        for item in as_list(evidence_found.get("study_characteristics"))
        if isinstance(item, dict)
    ]
    return {
        "input_policy": str(domain_evidence.get("input_policy") or "indirectness_allowed_input_only"),
        "review_scope_pico": _compact_review_scope_pico(review_scope_pico),
        "synthesis_target_pico": _compact_synthesis_target_pico(synthesis_target_pico),
        "evidence_found": {
            "included_study_ids": as_list(evidence_found.get("included_study_ids")),
            "study_characteristics_missing_study_ids": as_list(evidence_found.get("study_characteristics_missing_study_ids")),
            "study_count": len(study_characteristics),
            "study_characteristics": study_characteristics,
            "study_result_rows": [_compact_row(row) for row in study_rows],
        },
    }


def _build_v2_evidence_package(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    target_question = first_dict(domain_evidence.get("target_question"), evidence_body.get("target_question"))
    evidence_found = first_dict(domain_evidence.get("evidence_found"), evidence_body.get("evidence_found"))
    study_rows = [row for row in as_list(evidence_found.get("study_result_rows")) if isinstance(row, dict)]
    study_characteristics = [
        _compact_study(item)
        for item in as_list(evidence_found.get("study_characteristics"))
        if isinstance(item, dict)
    ]
    return {
        "input_policy": str(domain_evidence.get("input_policy") or "indirectness_allowed_input_only"),
        "target_question": _compact_target_question(target_question),
        "evidence_found": {
            "included_study_ids": as_list(evidence_found.get("included_study_ids")),
            "study_characteristics_missing_study_ids": as_list(evidence_found.get("study_characteristics_missing_study_ids")),
            "study_count": len(study_characteristics),
            "study_characteristics": study_characteristics,
            "study_result_rows": [_compact_row(row) for row in study_rows],
        },
    }


def _compact_review_question(review_question: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_text": review_question.get("question_text"),
        "population": as_list(review_question.get("population")),
        "population_source": review_question.get("population_source"),
        "intervention": as_list(review_question.get("intervention")),
        "comparator": as_list(review_question.get("comparator")),
        "outcome": as_list(review_question.get("outcome")),
    }


def _compact_synthesis_target(synthesis_target: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_text": synthesis_target.get("question_text"),
        "population": _compact_target_value(first_dict(synthesis_target.get("population"))),
        "intervention": _compact_target_value(first_dict(synthesis_target.get("intervention"))),
        "comparator": _compact_target_value(first_dict(synthesis_target.get("comparator"))),
        "outcome": _compact_target_value(first_dict(synthesis_target.get("outcome"))),
        "timepoint": _compact_target_value(first_dict(synthesis_target.get("timepoint"))),
        "subgroup": _compact_target_value(first_dict(synthesis_target.get("subgroup"))),
        "setting": _compact_target_value(first_dict(synthesis_target.get("setting"))),
    }


def _compact_review_scope_pico(review_scope_pico: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_text": review_scope_pico.get("question_text"),
        "population": as_list(review_scope_pico.get("population")),
        "intervention": as_list(review_scope_pico.get("intervention")),
        "comparator": as_list(review_scope_pico.get("comparator")),
        "outcome": as_list(review_scope_pico.get("outcome")),
    }


def _compact_synthesis_target_pico(synthesis_target_pico: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_text": synthesis_target_pico.get("question_text"),
        "population": _compact_target_value(first_dict(synthesis_target_pico.get("population"))),
        "intervention": _compact_target_value(first_dict(synthesis_target_pico.get("intervention"))),
        "comparator": _compact_target_value(first_dict(synthesis_target_pico.get("comparator"))),
        "outcome": _compact_target_value(first_dict(synthesis_target_pico.get("outcome"))),
        "timepoint": _compact_target_value(first_dict(synthesis_target_pico.get("timepoint"))),
        "subgroup": _compact_target_value(first_dict(synthesis_target_pico.get("subgroup"))),
        "setting": _compact_target_value(first_dict(synthesis_target_pico.get("setting"))),
    }


def _compact_target_value(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": item.get("value"),
        "source": item.get("source"),
        "measure": item.get("measure"),
        "data_type": item.get("data_type"),
        "effect_measure": item.get("effect_measure"),
        "benefit_direction": item.get("benefit_direction"),
    }


def _compact_sof_display_context(sof_display_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "population": sof_display_context.get("population"),
        "intervention": sof_display_context.get("intervention"),
        "comparator": sof_display_context.get("comparator"),
        "outcome": sof_display_context.get("outcome"),
        "timepoint": sof_display_context.get("timepoint"),
        "setting": sof_display_context.get("setting"),
        "participants": sof_display_context.get("participants"),
        "studies": sof_display_context.get("studies"),
        "table_title": sof_display_context.get("table_title"),
    }


def _build_legacy_evidence_package(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    setting = first_dict(domain_evidence.get("analysis_setting"), evidence_body.get("analysis_setting"))
    population_context = first_dict(domain_evidence.get("population_context"))
    study_rows = [row for row in as_list(domain_evidence.get("study_result_rows") or evidence_body.get("study_result_rows")) if isinstance(row, dict)]
    study_characteristics = [
        _compact_study(item)
        for item in as_list(domain_evidence.get("study_characteristics") or evidence_body.get("study_characteristics"))
        if isinstance(item, dict)
    ]
    return {
        "input_policy": str(domain_evidence.get("input_policy") or "indirectness_allowed_input_only"),
        "target": {
            "population": str(population_context.get("text") or ""),
            "population_source": str(population_context.get("source") or "missing"),
            "analysis_setting": _compact_setting(setting),
        },
        "included_study_ids": as_list(domain_evidence.get("included_study_ids") or evidence_body.get("included_study_ids")),
        "study_characteristics_missing_study_ids": as_list(
            domain_evidence.get("study_characteristics_missing_study_ids")
            or evidence_body.get("study_characteristics_missing_study_ids")
        ),
        "study_count": len(study_characteristics),
        "study_characteristics": study_characteristics,
        "study_result_rows": [_compact_row(row) for row in study_rows],
    }


def _compact_target_question(target_question: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_text": target_question.get("question_text"),
        "population": _compact_target_domain(first_dict(target_question.get("population"))),
        "intervention": _compact_target_domain(first_dict(target_question.get("intervention"))),
        "comparator": _compact_target_domain(first_dict(target_question.get("comparator"))),
        "outcome": _compact_target_domain(first_dict(target_question.get("outcome"))),
        "timepoint": _compact_target_domain(first_dict(target_question.get("timepoint"))),
        "subgroup": _compact_target_domain(first_dict(target_question.get("subgroup"))),
        "setting": _compact_target_domain(first_dict(target_question.get("setting"))),
    }


def _compact_target_domain(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary": item.get("primary"),
        "source": item.get("source"),
        "review_pico": as_list(item.get("review_pico")),
        "question_pico": as_list(item.get("question_pico")),
        "sof_context": item.get("sof_context"),
        "measure": item.get("measure"),
        "data_type": item.get("data_type"),
        "effect_measure": item.get("effect_measure"),
        "benefit_direction": item.get("benefit_direction"),
    }


def _compact_setting(setting: dict[str, Any]) -> dict[str, Any]:
    comparison = first_dict(setting.get("comparison"))
    outcome = first_dict(setting.get("outcome"))
    timepoint = first_dict(setting.get("timepoint"))
    subgroup = first_dict(setting.get("subgroup"))
    return {
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
            "source": subgroup.get("source"),
        },
        "data_type": setting.get("data_type"),
        "effect_measure": setting.get("effect_measure"),
    }


def _compact_study(study: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_id": study.get("study_id"),
        "population": _clip(study.get("population")),
        "intervention_comparator": _clip(study.get("intervention_comparator")),
        "outcomes": _clip(study.get("outcomes")),
        "methods": _clip(study.get("methods")),
        "notes": _clip(study.get("notes")),
    }


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_id": row.get("study_id"),
        "study_year": row.get("study_year"),
        "comparison": first_dict(row.get("comparison")),
        "outcome": first_dict(row.get("outcome")),
        "subgroup": first_dict(row.get("subgroup")),
        "analysis_note": _clip(row.get("analysis_note"), limit=300),
    }
