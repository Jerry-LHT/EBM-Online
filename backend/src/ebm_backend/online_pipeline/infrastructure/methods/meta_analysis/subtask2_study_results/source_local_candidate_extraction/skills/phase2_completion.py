"""LLM skills for targeted-extraction candidate completion."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.config import LLMConfig
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.context import (
    ExtractionContext,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.skills.common import (
    call_skill,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.skills.discover_candidates import (
    _target_semantics,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.tools.source_catalog import (
    source_payload,
)


SYSTEM = (
    "You are an evidence-based medicine data extraction assistant. "
    "Read the provided source faithfully. Return only source-grounded JSON. "
    "Do not perform arithmetic."
)


def extract_materials(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    candidate: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    data_type = _data_type(context)
    source_type = str(source.get("source_type") or "").strip().lower()
    if data_type == "dichotomous":
        template = (
            "material_extraction/extract_materials_dichotomous_table.txt"
            if source_type == "table"
            else "material_extraction/extract_materials_dichotomous_text.txt"
        )
    else:
        template = (
            "material_extraction/extract_materials_continuous_table.txt"
            if source_type == "table"
            else "material_extraction/extract_materials_continuous_text.txt"
        )
    output = call_skill(
        config=config,
        template=template,
        payload={
            "candidate": _candidate_view(candidate),
            "field_need_context": _field_need_context(context),
            "source": source_payload(source),
        },
        system=SYSTEM,
        fallback=_materials_fallback("unavailable"),
    )
    output["_template"] = template
    return output


def resolve_fields(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    candidate: dict[str, Any],
    materials: list[dict[str, Any]],
    family_summaries: list[dict[str, Any]],
    semantic_clues: list[dict[str, Any]],
) -> dict[str, Any]:
    data_type = _data_type(context)
    template = (
        "field_resolution/resolve_fields_dichotomous.txt"
        if data_type == "dichotomous"
        else "field_resolution/resolve_fields_continuous.txt"
    )
    return call_skill(
        config=config,
        template=template,
        payload={
            "candidate_setting": (candidate.get("study_result_setting") or {}),
            "required_fields": context.required_fields,
            "field_contracts": _field_contracts(context),
            "materials": materials,
            "family_summaries": family_summaries,
            "semantic_clues": semantic_clues,
        },
        system=SYSTEM,
        fallback={"resolution_status": "unavailable", "fields": {}, "warnings": ["field_resolution_unavailable"]},
    )


def plan_recovery(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    candidate: dict[str, Any],
    field_resolutions: dict[str, Any],
    materials: list[dict[str, Any]],
) -> dict[str, Any]:
    return call_skill(
        config=config,
        template="recovery/plan_recovery.txt",
        payload={
            "workflow_setting": _workflow_setting(context),
            "candidate": _candidate_view(candidate),
            "required_fields": context.required_fields,
            "field_resolutions": field_resolutions,
            "materials": _compact_materials(materials),
        },
        system=SYSTEM,
        fallback={"needs": [], "warnings": ["recovery_planning_unavailable"]},
    )


def recover_from_source(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    candidate: dict[str, Any],
    source: dict[str, Any],
    needs: list[dict[str, Any]],
) -> dict[str, Any]:
    data_type = _data_type(context)
    source_type = str(source.get("source_type") or "").strip().lower()
    if data_type == "dichotomous":
        template = (
            "recovery/recover_materials_dichotomous_table.txt"
            if source_type == "table"
            else "recovery/recover_materials_dichotomous_text.txt"
        )
    else:
        template = (
            "recovery/recover_materials_continuous_table.txt"
            if source_type == "table"
            else "recovery/recover_materials_continuous_text.txt"
        )
    output = call_skill(
        config=config,
        template=template,
        payload={
            "open_needs": _recovery_needs(needs),
            "source": source_payload(source),
        },
        system=SYSTEM,
        fallback=_materials_fallback("unavailable"),
    )
    output["_template"] = template
    return output


def _recovery_needs(needs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for need in needs:
        if not isinstance(need, dict):
            continue
        compact.append(
            {
                "target_field": need.get("target_field"),
                "need_type": need.get("need_type"),
                "acceptable_value_types": need.get("acceptable_value_types") or [],
                "field_contract": need.get("field_contract") or {},
                "field_semantics": need.get("field_semantics") or {},
                "current_materials": need.get("current_materials") or [],
            }
        )
    return compact


def select_support_sources(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    candidate: dict[str, Any],
    needs: list[dict[str, Any]],
    available_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    return call_skill(
        config=config,
        template="recovery/select_support_sources.txt",
        payload={
            "candidate": _candidate_view(candidate),
            "needs": needs,
            "available_sources": available_sources,
        },
        system=SYSTEM,
        fallback={"selected_source_ids": [], "warnings": ["support_source_selection_unavailable"]},
    )


def plan_calculation(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    candidate: dict[str, Any],
    field_resolutions: dict[str, Any],
    materials: list[dict[str, Any]],
) -> dict[str, Any]:
    return call_skill(
        config=config,
        template="plan_calculation.txt",
        payload={
            "candidate_setting": (candidate.get("study_result_setting") or {}),
            "required_fields": context.required_fields,
            "field_resolutions": field_resolutions,
            "field_contracts": _field_contracts(context),
            "materials": _compact_materials(materials),
        },
        system=SYSTEM,
        fallback={"operations": [], "warnings": ["calculation_planning_unavailable"]},
    )


def _workflow_setting(context: ExtractionContext) -> dict[str, Any]:
    return {
        "setting_id": context.setting_id,
        "comparison": context.analysis_setting.get("comparison") or {},
        "outcome": context.analysis_setting.get("outcome") or {},
        "timepoint": context.analysis_setting.get("timepoint") or {},
        "subgroup": context.analysis_setting.get("subgroup") or {},
        "target_semantics": _target_semantics(context.analysis_setting),
        "data_type": context.data_type,
        "required_fields": context.required_fields,
        "extraction_hint": context.extraction_hint,
    }


def _field_need_context(context: ExtractionContext) -> dict[str, Any]:
    return {
        "data_type": context.data_type,
        "required_fields": context.required_fields,
        "field_contracts": _field_contracts(context),
    }


def _candidate_view(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate.get("candidate_id"),
        "match_status": candidate.get("match_status"),
        "study_result_setting": candidate.get("study_result_setting") or {},
        "study_local_result": candidate.get("study_local_result") or {},
        "study_local_note": candidate.get("study_local_note"),
        "alignment_rationale": candidate.get("alignment_rationale"),
        "source_ids": candidate.get("source_ids") or ([candidate.get("source_id")] if candidate.get("source_id") else []),
    }


def _compact_materials(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for material in materials:
        compact.append(
            {
                "material_id": material.get("material_id"),
                "value": material.get("value"),
                "value_text": material.get("value_text"),
                "value_type": material.get("value_type"),
                "statistic_role": material.get("statistic_role"),
                "source_meaning": material.get("source_meaning"),
                "candidate_relevance": material.get("candidate_relevance"),
                "family_context": material.get("family_context") if isinstance(material.get("family_context"), dict) else {},
                "scope": material.get("scope") or {},
                "basis": material.get("basis") or {},
                "source_ref": material.get("source_ref") or {},
                "difference_from_peers": material.get("difference_from_peers") if isinstance(material.get("difference_from_peers"), dict) else {},
                "confidence": material.get("confidence"),
            }
        )
    return compact


def _field_contracts(context: ExtractionContext) -> dict[str, Any]:
    data_type = _data_type(context)
    contracts: dict[str, Any] = {}
    if data_type == "dichotomous":
        for field in context.required_fields:
            if field.endswith("_events"):
                contracts[field] = {
                    "direct_allowed_value_types": ["count"],
                    "calculation_allowed_value_types": ["percent", "total", "non_event_count"],
                }
            elif field.endswith("_total"):
                contracts[field] = {
                    "direct_allowed_value_types": ["total"],
                    "calculation_allowed_value_types": [],
                }
    else:
        for field in context.required_fields:
            if field.endswith("_mean"):
                contracts[field] = {
                    "direct_allowed_value_types": ["mean"],
                    "calculation_allowed_value_types": [],
                }
            elif field.endswith("_sd"):
                contracts[field] = {
                    "direct_allowed_value_types": ["sd"],
                    "calculation_allowed_value_types": ["se", "ci_lower", "ci_upper", "total"],
                }
            elif field.endswith("_total"):
                contracts[field] = {
                    "direct_allowed_value_types": ["total"],
                    "calculation_allowed_value_types": [],
                }
    return contracts


def _materials_fallback(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "materials": [],
        "material_sets": [],
        "semantic_clues": [],
        "warnings": [f"materials_{status}"],
    }


def _data_type(context: ExtractionContext) -> str:
    return str(context.data_type or "").strip().lower()
