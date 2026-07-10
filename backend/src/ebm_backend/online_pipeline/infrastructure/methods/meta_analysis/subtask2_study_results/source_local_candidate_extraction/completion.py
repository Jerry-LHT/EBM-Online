"""Candidate-scoped completion for targeted extraction full mode."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.config import LLMConfig
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.context import (
    ExtractionContext,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.debug_artifacts import (
    write_debug_artifact,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.progress import (
    ProgressLogger,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.skills.phase2_completion import (
    _field_contracts,
    extract_materials,
    plan_calculation,
    recover_from_source,
    resolve_fields,
    select_support_sources,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.tools.calculators import (
    execute_calculation_plans,
)


RESOLVED_DECISIONS = {"direct", "direct_fill", "calculated"}


def complete_candidates(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    candidates: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    source_outputs: list[dict[str, Any]],
    logger: ProgressLogger | None = None,
    debug_path: Any | None = None,
    method_name: str = "method_source_local_candidate_extraction",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not candidates:
        return candidates, {"enabled": True, "candidate_count": 0, "completed_count": 0}
    log = logger or ProgressLogger(enabled=False)
    workers = min(max(1, _env_int("SUBTASK2_TARGETED_CANDIDATE_WORKERS", 1)), len(candidates))
    if workers <= 1:
        completed = [
            _complete_one_candidate(
                config=config,
                context=context,
                candidate=candidate,
                sources=sources,
                source_outputs=source_outputs,
                logger=log,
                debug_path=debug_path,
                method_name=method_name,
            )
            for candidate in candidates
        ]
    else:
        completed_by_index: list[dict[str, Any] | None] = [None] * len(candidates)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _complete_one_candidate,
                    config=config,
                    context=context,
                    candidate=candidate,
                    sources=sources,
                    source_outputs=source_outputs,
                    logger=log,
                    debug_path=debug_path,
                    method_name=method_name,
                ): index
                for index, candidate in enumerate(candidates)
            }
            for future in as_completed(futures):
                completed_by_index[futures[future]] = future.result()
        completed = [candidate for candidate in completed_by_index if candidate is not None]
    return completed, {
        "enabled": True,
        "candidate_count": len(candidates),
        "completed_count": len(completed),
        "state_counts": _state_counts(completed),
    }


def _complete_one_candidate(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    candidate: dict[str, Any],
    sources: list[dict[str, Any]],
    source_outputs: list[dict[str, Any]],
    logger: ProgressLogger,
    debug_path: Any | None,
    method_name: str,
) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or "")
    logger.log("targeted completion start", candidate_id=candidate_id, study_id=context.study_id)
    _write_completion_checkpoint(
        path=debug_path,
        method_name=method_name,
        context=context,
        candidate=candidate,
        stage="completion_start",
        extra={},
    )
    source_by_id = {str(source.get("source_id") or ""): source for source in sources}
    materials: list[dict[str, Any]] = []
    material_sets: list[dict[str, Any]] = []
    family_summaries: list[dict[str, Any]] = []
    semantic_clues: list[dict[str, Any]] = []
    source_reads: list[dict[str, Any]] = []
    warnings: list[str] = []

    for source, output in _read_initial_material_sources(
        config=config,
        context=context,
        candidate=candidate,
        sources=_initial_sources(candidate=candidate, source_by_id=source_by_id),
    ):
        tagged = _tag_material_output(
            output=output,
            candidate_id=candidate_id,
            source=source,
            start_index=len(materials) + 1,
        )
        materials.extend(tagged["materials"])
        material_sets.extend(tagged["material_sets"])
        family_summaries = _assemble_family_summaries(materials=materials)
        semantic_clues.extend(tagged["semantic_clues"])
        source_reads.append(_source_read_summary(stage="initial", source=source, output=output, material_count=len(tagged["materials"])))
        warnings.extend(_warnings(output))
    _write_completion_checkpoint(
        path=debug_path,
        method_name=method_name,
        context=context,
        candidate=candidate,
        stage="initial_materials_done",
        extra={
            "material_count": len(materials),
            "material_set_count": len(material_sets),
            "semantic_clue_count": len(semantic_clues),
            "source_read_count": len(source_reads),
        },
    )

    if not materials and not semantic_clues:
        completion = {
            "phase": "targeted_phase2_candidate_completion",
            "result_state": "needs_evidence",
            "result_data": {},
            "numeric_extraction": {
                "phase": "targeted_phase2_candidate_completion",
                "fields": {},
                "missing_fields": list(context.required_fields),
            },
            "materials": materials,
            "material_sets": material_sets,
            "family_summaries": family_summaries,
            "semantic_clues": semantic_clues,
            "field_resolutions": {"resolution_status": "unresolved", "fields": {}, "warnings": []},
            "need_ledger": [],
            "calculation_plans": [],
            "calculation_results": [],
            "source_reads": source_reads,
            "warnings": [*warnings, "initial_source_has_no_materials"],
        }
        logger.log("targeted completion done", candidate_id=candidate_id, state="needs_evidence", fields=0)
        _write_completion_checkpoint(
            path=debug_path,
            method_name=method_name,
            context=context,
            candidate=candidate,
            stage="completion_done",
            extra={
                "result_state": "needs_evidence",
                "missing_fields": list(context.required_fields),
            },
        )
        return {**candidate, "completion": completion}

    resolution = _normalize_resolution(
        resolve_fields(
            config=config,
            context=context,
            candidate=candidate,
            materials=materials,
            family_summaries=family_summaries,
            semantic_clues=semantic_clues,
        ),
        required_fields=context.required_fields,
    )
    resolution = _validate_field_assignments(
        context=context,
        candidate=candidate,
        field_resolutions=resolution,
        materials=materials,
    )
    _write_completion_checkpoint(
        path=debug_path,
        method_name=method_name,
        context=context,
        candidate=candidate,
        stage="resolution_done",
        extra={
            "resolution_status": resolution.get("resolution_status"),
            "resolved_field_count": len((resolution.get("fields") or {})),
        },
    )
    field_values = _assemble_resolved_fields(field_resolutions=resolution, materials=materials)
    needs = _build_need_ledger(
        context=context,
        candidate=candidate,
        field_resolutions=resolution,
        field_values=field_values,
        materials=materials,
    )

    calculation_plans: list[dict[str, Any]] = []
    calculation_results: list[dict[str, Any]] = []
    if _has_calculable_field(field_resolutions=resolution):
        calculation_plans = _calculation_plans_from_resolution(field_resolutions=resolution)
        calc_plan: dict[str, Any] = {"operations": calculation_plans, "warnings": []}
        if not calculation_plans and _has_legacy_calculable_field(field_resolutions=resolution):
            calc_plan = plan_calculation(
                config=config,
                context=context,
                candidate=candidate,
                field_resolutions=resolution,
                materials=materials,
            )
            calculation_plans = _normalize_calculation_plans(calc_plan.get("operations") if isinstance(calc_plan, dict) else [])
        calculation_results = execute_calculation_plans(plans=calculation_plans, materials=materials)
        warnings.extend(_warnings(calc_plan))
        field_values = _apply_calculation_results(field_values=field_values, calculation_results=calculation_results)
        needs = _build_need_ledger(
            context=context,
            candidate=candidate,
            field_resolutions=resolution,
            field_values=field_values,
            materials=materials,
        )
        _write_completion_checkpoint(
            path=debug_path,
            method_name=method_name,
            context=context,
            candidate=candidate,
            stage="calculation_done",
            extra={
                "plan_count": len(calculation_plans),
                "result_count": len(calculation_results),
                "open_need_count": len([need for need in needs if need.get("status") == "open"]),
            },
        )

    open_needs = [need for need in needs if need.get("status") == "open"]
    if open_needs:
        recovery_sources = _recovery_sources(
            config=config,
            context=context,
            candidate=candidate,
            open_needs=open_needs,
            sources=sources,
            source_outputs=source_outputs,
            already_read={str(read.get("source_id") or "") for read in source_reads},
        )
        recovery_materials_added = False
        for source in recovery_sources:
            if not open_needs:
                break
            output = recover_from_source(config=config, context=context, candidate=candidate, source=source, needs=open_needs)
            tagged = _tag_material_output(
                output=output,
                candidate_id=candidate_id,
                source=source,
                start_index=len(materials) + 1,
            )
            materials.extend(tagged["materials"])
            material_sets.extend(tagged["material_sets"])
            family_summaries = _assemble_family_summaries(materials=materials)
            semantic_clues.extend(tagged["semantic_clues"])
            source_reads.append(_source_read_summary(stage="recovery", source=source, output=output, material_count=len(tagged["materials"])))
            warnings.extend(_warnings(output))
            if not tagged["materials"] and not tagged["semantic_clues"]:
                continue
            recovery_materials_added = True
        _write_completion_checkpoint(
            path=debug_path,
            method_name=method_name,
            context=context,
            candidate=candidate,
            stage="recovery_done",
            extra={
                "recovery_materials_added": recovery_materials_added,
                "source_read_count": len(source_reads),
            },
        )
        if recovery_materials_added:
            resolution = _normalize_resolution(
                resolve_fields(
                    config=config,
                    context=context,
                    candidate=candidate,
                    materials=materials,
                    family_summaries=family_summaries,
                    semantic_clues=semantic_clues,
                ),
                required_fields=context.required_fields,
            )
            resolution = _validate_field_assignments(
                context=context,
                candidate=candidate,
                field_resolutions=resolution,
                materials=materials,
            )
            field_values = _assemble_resolved_fields(field_resolutions=resolution, materials=materials)
            if _has_calculable_field(field_resolutions=resolution):
                new_plans = _calculation_plans_from_resolution(field_resolutions=resolution)
                calc_plan = {"operations": new_plans, "warnings": []}
                if not new_plans and _has_legacy_calculable_field(field_resolutions=resolution):
                    calc_plan = plan_calculation(
                        config=config,
                        context=context,
                        candidate=candidate,
                        field_resolutions=resolution,
                        materials=materials,
                    )
                    new_plans = _normalize_calculation_plans(calc_plan.get("operations") if isinstance(calc_plan, dict) else [])
                if new_plans:
                    calculation_plans = new_plans
                calculation_results = execute_calculation_plans(plans=calculation_plans, materials=materials)
                warnings.extend(_warnings(calc_plan))
                field_values = _apply_calculation_results(field_values=field_values, calculation_results=calculation_results)
            needs = _build_need_ledger(
                context=context,
                candidate=candidate,
                field_resolutions=resolution,
                field_values=field_values,
                materials=materials,
            )
            _write_completion_checkpoint(
                path=debug_path,
                method_name=method_name,
                context=context,
                candidate=candidate,
                stage="post_recovery_resolution_done",
                extra={
                    "resolution_status": resolution.get("resolution_status"),
                    "open_need_count": len([need for need in needs if need.get("status") == "open"]),
                },
            )

    numeric_fields = _numeric_fields(required_fields=context.required_fields, field_values=field_values, field_resolutions=resolution)
    result_data = {field: field_values[field]["value"] for field in context.required_fields if _has_value(field_values.get(field))}
    complete_result_data = result_data if all(field in result_data for field in context.required_fields) else None
    result_state = _result_state(
        required_fields=context.required_fields,
        result_data=result_data,
        complete_result_data=complete_result_data,
        materials=materials,
        field_resolutions=resolution,
    )
    completion = {
        "phase": "targeted_phase2_candidate_completion",
        "result_state": result_state,
        "result_data": result_data,
        "numeric_extraction": {
            "phase": "targeted_phase2_candidate_completion",
            "fields": numeric_fields,
            "missing_fields": [field for field in context.required_fields if field not in result_data],
        },
        "materials": materials,
        "material_sets": material_sets,
        "family_summaries": family_summaries,
        "semantic_clues": semantic_clues,
        "field_resolutions": resolution,
        "need_ledger": needs,
        "calculation_plans": calculation_plans,
        "calculation_results": calculation_results,
        "source_reads": source_reads,
        "warnings": warnings,
    }
    logger.log("targeted completion done", candidate_id=candidate_id, state=result_state, fields=len(result_data))
    _write_completion_checkpoint(
        path=debug_path,
        method_name=method_name,
        context=context,
        candidate=candidate,
        stage="completion_done",
        extra={
            "result_state": result_state,
            "result_field_count": len(result_data),
            "missing_fields": [field for field in context.required_fields if field not in result_data],
        },
    )
    return {**candidate, "completion": completion}


def _write_completion_checkpoint(
    *,
    path: Any | None,
    method_name: str,
    context: ExtractionContext,
    candidate: dict[str, Any],
    stage: str,
    extra: dict[str, Any],
) -> None:
    if path is None:
        return
    write_debug_artifact(
        path=path,
        payload={
            "method": method_name,
            "instance_id": context.instance_id,
            "study_id": context.study_id,
            "checkpoint_stage": stage,
            "candidate_id": candidate.get("candidate_id"),
            "candidate_match_status": candidate.get("match_status"),
            "candidate_note": candidate.get("study_local_note"),
            **extra,
        },
    )


def _read_initial_material_sources(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    candidate: dict[str, Any],
    sources: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if not sources:
        return []
    workers = min(max(1, _env_int("SUBTASK2_TARGETED_INITIAL_SOURCE_WORKERS", 2)), len(sources))
    if workers <= 1:
        return [
            (source, extract_materials(config=config, context=context, candidate=candidate, source=source))
            for source in sources
        ]
    outputs_by_index: list[tuple[dict[str, Any], dict[str, Any]] | None] = [None] * len(sources)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(extract_materials, config=config, context=context, candidate=candidate, source=source): index
            for index, source in enumerate(sources)
        }
        for future in as_completed(futures):
            index = futures[future]
            outputs_by_index[index] = (sources[index], future.result())
    return [item for item in outputs_by_index if item is not None]


def _initial_sources(*, candidate: dict[str, Any], source_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ids = []
    for value in candidate.get("source_ids") or []:
        source_id = str(value or "")
        if source_id and source_id not in ids:
            ids.append(source_id)
    source_id = str(candidate.get("source_id") or "")
    if source_id and source_id not in ids:
        ids.append(source_id)
    return [source_by_id[source_id] for source_id in ids if source_id in source_by_id]


def _recovery_sources(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    candidate: dict[str, Any],
    open_needs: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    source_outputs: list[dict[str, Any]],
    already_read: set[str],
) -> list[dict[str, Any]]:
    source_by_id = {str(source.get("source_id") or ""): source for source in sources}
    available = []
    for output in source_outputs:
        source_id = str(output.get("source_id") or "")
        if not source_id or source_id in already_read or source_id not in source_by_id:
            continue
        available.append(
            {
                "source_id": source_id,
                "source_type": output.get("source_type") or source_by_id[source_id].get("source_type"),
                "brief_summary": output.get("brief_summary"),
                "source_profile": output.get("source_profile") or {},
                "warnings": output.get("warnings") or [],
            }
        )
    selection = select_support_sources(
        config=config,
        context=context,
        candidate=candidate,
        needs=open_needs,
        available_sources=available,
    )
    selected_ids = []
    seen: set[str] = set()
    for value in selection.get("selected_source_ids") or []:
        source_id = str(value or "")
        if not source_id or source_id in seen or source_id not in source_by_id:
            continue
        seen.add(source_id)
        selected_ids.append(source_id)
    limit = _optional_env_int("SUBTASK2_TARGETED_MAX_RECOVERY_SOURCES")
    if limit is not None and limit >= 0:
        selected_ids = selected_ids[:limit]
    return [source_by_id[source_id] for source_id in selected_ids]


def _tag_material_output(
    *,
    output: dict[str, Any],
    candidate_id: str,
    source: dict[str, Any],
    start_index: int,
) -> dict[str, Any]:
    source_id = str(source.get("source_id") or "")
    materials: list[dict[str, Any]] = []
    for offset, material in enumerate(output.get("materials") if isinstance(output.get("materials"), list) else [], start=start_index):
        if not isinstance(material, dict):
            continue
        source_ref = material.get("source_ref") if isinstance(material.get("source_ref"), dict) else {}
        materials.append(
            {
                **material,
                "material_id": f"{candidate_id}::m{offset:03d}",
                "source_ref": {
                    **source_ref,
                    "source_id": source_ref.get("source_id") or source_id,
                },
            }
        )
    material_sets = [item for item in (output.get("material_sets") or []) if isinstance(item, dict)]
    semantic_clues = [item for item in (output.get("semantic_clues") or []) if isinstance(item, dict)]
    return {"materials": materials, "material_sets": material_sets, "semantic_clues": semantic_clues}


def _assemble_family_summaries(*, materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for material in materials:
        if not isinstance(material, dict):
            continue
        source_ref = material.get("source_ref") if isinstance(material.get("source_ref"), dict) else {}
        source_id = str(source_ref.get("source_id") or "")
        family_context = material.get("family_context") if isinstance(material.get("family_context"), dict) else {}
        family_label = str(family_context.get("family_label") or "")
        if not source_id or not family_label:
            continue
        family_kind = str(family_context.get("family_kind") or "unclear")
        groups.setdefault((source_id, family_kind, family_label), []).append(material)

    summaries: list[dict[str, Any]] = []
    for (source_id, family_kind, family_label), items in groups.items():
        roles: dict[str, int] = {}
        arms: dict[str, int] = {}
        categories: dict[str, int] = {}
        bases: dict[str, int] = {}
        anchors: list[str] = []
        material_ids: list[str] = []
        for material in items:
            family_context = material.get("family_context") if isinstance(material.get("family_context"), dict) else {}
            role = str(family_context.get("within_family_role") or "unclear")
            roles[role] = roles.get(role, 0) + 1
            scope = material.get("scope") if isinstance(material.get("scope"), dict) else {}
            arm = str(scope.get("arm") or "")
            if arm:
                arms[arm] = arms.get(arm, 0) + 1
            diff = material.get("difference_from_peers") if isinstance(material.get("difference_from_peers"), dict) else {}
            category = str(diff.get("category") or "")
            if category:
                categories[category] = categories.get(category, 0) + 1
            basis = material.get("basis") if isinstance(material.get("basis"), dict) else {}
            basis_key = f"{basis.get('basis_type') or 'unclear'}|{basis.get('sample_frame') or 'unclear'}"
            bases[basis_key] = bases.get(basis_key, 0) + 1
            material_id = str(material.get("material_id") or "")
            if material_id:
                material_ids.append(material_id)
            quote = str((source_ref := (material.get("source_ref") if isinstance(material.get("source_ref"), dict) else {})).get("quote_or_anchor") or "")
            if quote and quote not in anchors:
                anchors.append(quote)
        summaries.append(
            {
                "source_id": source_id,
                "family_label": family_label,
                "family_kind": family_kind,
                "material_ids": material_ids,
                "within_family_roles": roles,
                "arms_present": list(arms.keys()),
                "categories_present": list(categories.keys()),
                "basis_frames": list(bases.keys()),
                "anchor_examples": anchors[:3],
            }
        )
    return summaries


def _warnings(output: dict[str, Any]) -> list[str]:
    values = output.get("warnings")
    return [str(value) for value in values] if isinstance(values, list) else []


def _source_read_summary(*, stage: str, source: dict[str, Any], output: dict[str, Any], material_count: int) -> dict[str, Any]:
    return {
        "stage": stage,
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "template": output.get("_template"),
        "status": output.get("status"),
        "material_count": material_count,
        "semantic_clue_count": len(output.get("semantic_clues") or []),
        "warnings": _warnings(output),
    }


def _normalize_resolution(resolution: dict[str, Any], *, required_fields: list[str]) -> dict[str, Any]:
    fields = resolution.get("fields") if isinstance(resolution.get("fields"), dict) else {}
    normalized_fields: dict[str, Any] = {}
    for field in required_fields:
        raw = fields.get(field) if isinstance(fields.get(field), dict) else {}
        operation = str(raw.get("operation") or "").strip()
        decision = str(raw.get("decision") or _decision_from_operation(operation) or "unresolved")
        selected_material_ids = _selected_material_ids_from_resolution(raw)
        selected_supporting_material_ids = _selected_supporting_material_ids_from_resolution(raw)
        normalized_fields[field] = {
            "decision": decision,
            "operation": operation or _operation_from_decision(decision),
            "target_field": raw.get("target_field") or field,
            "direct_material_id": raw.get("direct_material_id"),
            "selected_material_ids": selected_material_ids,
            "selected_supporting_material_ids": selected_supporting_material_ids,
            "calculator": raw.get("calculator"),
            "arguments": raw.get("arguments") if isinstance(raw.get("arguments"), dict) else {},
            "generic_expression": raw.get("generic_expression"),
            "alternative_paths": [
                {
                    "operation": path.get("operation"),
                    "material_ids": [str(value) for value in (path.get("material_ids") or [])],
                    "supporting_material_ids": [str(value) for value in (path.get("supporting_material_ids") or [])],
                    "reason_not_selected": path.get("reason_not_selected"),
                }
                for path in (raw.get("alternative_paths") or [])
                if isinstance(path, dict)
            ],
            "formula_proposal": raw.get("formula_proposal") if isinstance(raw.get("formula_proposal"), dict) else None,
            "rationale": raw.get("rationale"),
            "confidence": raw.get("confidence"),
        }
    return {
        "resolution_status": resolution.get("resolution_status") or "unresolved",
        "fields": normalized_fields,
        "warnings": _warnings(resolution),
    }


def _decision_from_operation(operation: str) -> str | None:
    if operation == "direct_fill":
        return "direct"
    if operation in {"supported_calculation", "generic_calculation"}:
        return "needs_calculation"
    if operation == "needs_more_material":
        return "unresolved"
    if operation in {"unresolved", "not_applicable"}:
        return operation
    return None


def _operation_from_decision(decision: str) -> str:
    if decision == "direct":
        return "direct_fill"
    if decision == "needs_calculation":
        return "supported_calculation"
    return decision or "unresolved"


def _selected_material_ids_from_resolution(raw: dict[str, Any]) -> list[str]:
    direct_id = raw.get("direct_material_id")
    if direct_id:
        return [str(direct_id)]
    return [str(value) for value in raw.get("selected_material_ids") or raw.get("material_ids") or []]


def _selected_supporting_material_ids_from_resolution(raw: dict[str, Any]) -> list[str]:
    ids: list[str] = [
        str(value) for value in raw.get("selected_supporting_material_ids") or raw.get("supporting_material_ids") or []
    ]
    arguments = raw.get("arguments") if isinstance(raw.get("arguments"), dict) else {}
    for value in arguments.values():
        if value and str(value) not in ids:
            ids.append(str(value))
    return ids


def _assemble_resolved_fields(*, field_resolutions: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id = {str(material.get("material_id") or ""): material for material in materials}
    field_values: dict[str, dict[str, Any]] = {}
    for field, spec in (field_resolutions.get("fields") or {}).items():
        decision = str(spec.get("decision") or "unresolved")
        material_ids = spec.get("selected_material_ids") or []
        if decision not in RESOLVED_DECISIONS or not material_ids:
            field_values[field] = {"status": decision, "value": None, "material_ids": material_ids}
            continue
        material = by_id.get(str(material_ids[0] or ""))
        field_values[field] = {
            "status": decision,
            "value": _numeric_material_value(material),
            "material_ids": material_ids,
        }
    return field_values


def _build_need_ledger(
    *,
    context: ExtractionContext,
    candidate: dict[str, Any],
    field_resolutions: dict[str, Any],
    field_values: dict[str, dict[str, Any]],
    materials: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _open_needs_from_resolution(
        context=context,
        candidate=candidate,
        field_resolutions=field_resolutions,
        field_values=field_values,
        materials=materials,
    )


def _open_needs_from_resolution(
    *,
    context: ExtractionContext,
    candidate: dict[str, Any],
    field_resolutions: dict[str, Any],
    field_values: dict[str, dict[str, Any]],
    materials: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    needs: list[dict[str, Any]] = []
    for field in context.required_fields:
        spec = (field_resolutions.get("fields") or {}).get(field) or {}
        decision = str(spec.get("decision") or "unresolved")
        if decision in RESOLVED_DECISIONS and _has_value(field_values.get(field)):
            continue
        if decision == "not_applicable":
            continue
        needs.append(
            {
                "target_field": field,
                "need_type": _default_need_type(field),
                "acceptable_value_types": _acceptable_value_types(field=field, context=context),
                "field_contract": (_field_contracts(context).get(field) or {}),
                "field_semantics": _field_semantics(field=field, context=context, candidate=candidate),
                "current_materials": _field_material_context(
                    field=field,
                    context=context,
                    candidate=candidate,
                    materials=materials,
                ),
                "priority": "high",
                "status": "open",
            }
        )
    return needs


def _field_semantics(*, field: str, context: ExtractionContext, candidate: dict[str, Any]) -> dict[str, Any]:
    setting = candidate.get("study_result_setting") if isinstance(candidate.get("study_result_setting"), dict) else {}
    arm_role = "experimental" if field.startswith("experimental_") else "control" if field.startswith("control_") else None
    arm_label = _candidate_arm_label(field=field, candidate=candidate)
    data_type = str(context.data_type or "").strip().lower()
    base: dict[str, Any] = {
        "target_field": field,
        "arm_role": arm_role,
        "arm_label": arm_label,
        "data_type": data_type,
    }
    if field.endswith("_total"):
        base.update(
            {
                "material_role": "denominator_or_sample_frame",
                "target_meaning": "sample size, total, denominator, or analysis population for the target arm",
                "required_constraints": ["arm", "population_or_sample_frame", "unit_of_analysis"],
                "required_match_context": _compact_none(
                    {
                        "arm_role": arm_role,
                        "arm_label": arm_label,
                        "population_or_subgroup": setting.get("population_or_subgroup"),
                        "unit_of_analysis": "participants",
                    }
                ),
                "conditional_constraints": [],
                "conditional_match_context": {},
                "conditional_rule": (
                    "For a total/denominator need, do not require outcome or timepoint unless the open need "
                    "explicitly provides them in required_match_context."
                ),
            }
        )
    elif field.endswith("_mean"):
        base.update(
            {
                "material_role": "result_mean",
                "target_meaning": "mean for the target arm and candidate local result",
                "required_constraints": ["outcome_or_measure", "arm", "timepoint", "population_or_subgroup", "statistic_frame"],
                "required_match_context": _compact_none(
                    {
                        "outcome_label": setting.get("outcome_label"),
                        "outcome_measure": setting.get("outcome_measure"),
                        "row_label": setting.get("row_label"),
                        "arm_role": arm_role,
                        "arm_label": arm_label,
                        "timepoint": setting.get("timepoint"),
                        "population_or_subgroup": setting.get("population_or_subgroup"),
                        "statistic_type": setting.get("statistic_type"),
                    }
                ),
                "conditional_constraints": [],
                "conditional_match_context": {},
                "conditional_rule": None,
            }
        )
    elif field.endswith("_sd"):
        base.update(
            {
                "material_role": "standard_deviation_or_uncertainty_support",
                "target_meaning": "SD or uncertainty input for the target arm and candidate local result",
                "required_constraints": ["outcome_or_measure", "arm", "timepoint", "population_or_subgroup", "statistic_frame"],
                "required_match_context": _compact_none(
                    {
                        "outcome_label": setting.get("outcome_label"),
                        "outcome_measure": setting.get("outcome_measure"),
                        "row_label": setting.get("row_label"),
                        "arm_role": arm_role,
                        "arm_label": arm_label,
                        "timepoint": setting.get("timepoint"),
                        "population_or_subgroup": setting.get("population_or_subgroup"),
                        "statistic_type": setting.get("statistic_type"),
                    }
                ),
                "conditional_constraints": [],
                "conditional_match_context": {},
                "conditional_rule": None,
            }
        )
    elif field.endswith("_events"):
        base.update(
            {
                "material_role": "event_count_or_event_count_support",
                "target_meaning": "event count or derivation input for the target arm and candidate event",
                "required_constraints": ["event_or_category", "arm", "timepoint_or_follow_up", "population_or_subgroup", "denominator_basis"],
                "required_match_context": _compact_none(
                    {
                        "event_or_category": setting.get("event_label") or setting.get("outcome_label") or setting.get("row_label"),
                        "outcome_measure": setting.get("outcome_measure"),
                        "arm_role": arm_role,
                        "arm_label": arm_label,
                        "timepoint": setting.get("timepoint"),
                        "population_or_subgroup": setting.get("population_or_subgroup"),
                        "statistic_type": setting.get("statistic_type"),
                    }
                ),
                "conditional_constraints": [],
                "conditional_match_context": {},
                "conditional_rule": None,
            }
        )
    else:
        base.update(
            {
                "material_role": "numeric_support",
                "target_meaning": "numeric material that can support the target field",
                "required_constraints": [],
                "required_match_context": {},
                "conditional_constraints": [],
                "conditional_match_context": {},
                "conditional_rule": None,
            }
        )
    return base


def _compact_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _candidate_scope(candidate: dict[str, Any]) -> dict[str, Any]:
    setting = candidate.get("study_result_setting") if isinstance(candidate.get("study_result_setting"), dict) else {}
    return {
        "row_label": setting.get("row_label"),
        "outcome_label": setting.get("outcome_label"),
        "timepoint": setting.get("timepoint"),
        "population_or_subgroup": setting.get("population_or_subgroup"),
        "experimental_arm_label": setting.get("experimental_arm_label"),
        "control_arm_label": setting.get("control_arm_label"),
        "table_local_notes": setting.get("table_local_notes"),
    }


def _candidate_context(candidate: dict[str, Any]) -> dict[str, Any]:
    setting = candidate.get("study_result_setting") if isinstance(candidate.get("study_result_setting"), dict) else {}
    return {
        "outcome_or_event": setting.get("outcome_label") or setting.get("row_label"),
        "measure_or_component": setting.get("outcome_measure"),
        "timepoint": setting.get("timepoint"),
        "population_or_subgroup": setting.get("population_or_subgroup"),
        "statistic_type": setting.get("statistic_type"),
        "experimental_arm": setting.get("experimental_arm_label"),
        "control_arm": setting.get("control_arm_label"),
        "local_notes": setting.get("table_local_notes"),
    }


def _field_material_context(
    *,
    field: str,
    context: ExtractionContext,
    candidate: dict[str, Any],
    materials: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed_value_types = set(_context_value_types(field=field, context=context))
    target_arm_label = _candidate_arm_label(field=field, candidate=candidate)
    context_rows: list[dict[str, Any]] = []
    for material in materials:
        if not isinstance(material, dict):
            continue
        scope = material.get("scope") if isinstance(material.get("scope"), dict) else {}
        basis = material.get("basis") if isinstance(material.get("basis"), dict) else {}
        source_ref = material.get("source_ref") if isinstance(material.get("source_ref"), dict) else {}
        material_arm = str(scope.get("arm") or "")
        value_type = str(material.get("value_type") or "")
        if allowed_value_types and value_type not in allowed_value_types:
            continue
        if target_arm_label and material_arm and not _text_compatible(target_arm_label, material_arm):
            continue
        context_rows.append(
            {
                "material_id": material.get("material_id"),
                "value_text": material.get("value_text"),
                "value": material.get("value"),
                "value_type": value_type,
                "statistic_role": material.get("statistic_role"),
                "source_meaning": material.get("source_meaning"),
                "scope": {
                    "arm": scope.get("arm"),
                    "outcome": scope.get("outcome"),
                    "population": scope.get("population"),
                    "timepoint": scope.get("timepoint"),
                    "subgroup": scope.get("subgroup"),
                },
                "basis": {
                    "basis_type": basis.get("basis_type"),
                    "sample_frame": basis.get("sample_frame"),
                    "denominator_description": basis.get("denominator_description"),
                },
                "source_ref": {
                    "source_id": source_ref.get("source_id"),
                    "quote_or_anchor": source_ref.get("quote_or_anchor"),
                },
                "candidate_relevance": material.get("candidate_relevance"),
            }
        )
    return context_rows[:8]


def _candidate_arm_label(*, field: str, candidate: dict[str, Any]) -> str | None:
    setting = candidate.get("study_result_setting") if isinstance(candidate.get("study_result_setting"), dict) else {}
    if field.startswith("experimental_"):
        return _clean_string(setting.get("experimental_arm_label"))
    if field.startswith("control_"):
        return _clean_string(setting.get("control_arm_label"))
    return None


def _context_value_types(*, field: str, context: ExtractionContext) -> list[str]:
    contracts = _field_contracts(context)
    contract = contracts.get(field) if isinstance(contracts.get(field), dict) else {}
    values: list[str] = []
    for key in ("direct_allowed_value_types", "calculation_allowed_value_types"):
        for value in contract.get(key) or []:
            text = _clean_string(value)
            if text and text not in values:
                values.append(text)
    if values:
        return values
    return _acceptable_value_types(field=field, context=context)


def _text_compatible(left: Any, right: Any) -> bool:
    left_text = _clean_string(left)
    right_text = _clean_string(right)
    if not left_text or not right_text:
        return True
    return left_text in right_text or right_text in left_text


def _clean_string(value: Any) -> str | None:
    text = " ".join(str(value).strip().lower().split()) if value is not None else ""
    return text or None


def _guard_broad_totals(
    *,
    context: ExtractionContext,
    candidate: dict[str, Any],
    field_resolutions: dict[str, Any],
    materials: list[dict[str, Any]],
) -> dict[str, Any]:
    if str(context.data_type or "").strip().lower() != "dichotomous":
        return field_resolutions
    fields = field_resolutions.get("fields") if isinstance(field_resolutions.get("fields"), dict) else {}
    if not fields:
        return field_resolutions
    by_id = {str(material.get("material_id") or ""): material for material in materials if isinstance(material, dict)}
    setting = candidate.get("study_result_setting") if isinstance(candidate.get("study_result_setting"), dict) else {}
    target_timepoint = str(setting.get("timepoint") or "").strip().lower()
    for field_name in ("experimental_total", "control_total"):
        spec = fields.get(field_name)
        if not isinstance(spec, dict):
            continue
        if str(spec.get("decision") or "") != "direct":
            continue
        material_ids = spec.get("selected_material_ids") or []
        if not material_ids:
            continue
        chosen = by_id.get(str(material_ids[0] or ""))
        if not isinstance(chosen, dict):
            continue
        chosen_basis = chosen.get("basis") if isinstance(chosen.get("basis"), dict) else {}
        chosen_frame = str(chosen_basis.get("sample_frame") or "")
        if chosen_frame not in {"randomized", "analyzed"}:
            continue
        chosen_scope = chosen.get("scope") if isinstance(chosen.get("scope"), dict) else {}
        arm = str(chosen_scope.get("arm") or "")
        narrower = _find_narrower_arm_totals(
            materials=materials,
            arm=arm,
            target_timepoint=target_timepoint,
        )
        if not narrower:
            continue
        spec["decision"] = "ambiguous"
        spec["selected_supporting_material_ids"] = list(
            dict.fromkeys([*(spec.get("selected_supporting_material_ids") or []), *[m.get("material_id") for m in narrower if m.get("material_id")]])
        )
        spec["rationale"] = (
            "A broader randomized/analyzed total was available, but another arm-level total with a narrower sample frame "
            "or more candidate-specific denominator basis is also present. The total should stay unresolved until the "
            "candidate-compatible denominator is clarified."
        )
        spec["confidence"] = "medium"
    return field_resolutions


def _validate_field_assignments(
    *,
    context: ExtractionContext,
    candidate: dict[str, Any],
    field_resolutions: dict[str, Any],
    materials: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {str(material.get("material_id") or ""): material for material in materials if isinstance(material, dict)}
    for field_name, spec in ((field_resolutions.get("fields") or {}).items()):
        if not isinstance(spec, dict):
            continue
        decision = str(spec.get("decision") or "")
        if decision != "direct":
            continue
        material_ids = spec.get("selected_material_ids") or []
        if not material_ids:
            continue
        material = by_id.get(str(material_ids[0] or ""))
        if not isinstance(material, dict):
            continue
        value_type = str(material.get("value_type") or "")
        numeric_value = _numeric_material_value(material)
        if _is_direct_assignment_legal(field_name=field_name, value_type=value_type) and numeric_value is not None:
            continue
        supporting_ids = list(dict.fromkeys([*(spec.get("selected_supporting_material_ids") or []), *material_ids]))
        if _can_support_calculation(field_name=field_name, value_type=value_type):
            spec["decision"] = "needs_calculation"
            spec["operation"] = "supported_calculation"
            spec["selected_material_ids"] = []
            spec["selected_supporting_material_ids"] = supporting_ids
            spec["rationale"] = (
                f"The selected material is a {value_type} for {field_name}. It cannot directly fill this field, "
                "but it may support deterministic calculation if a compatible companion material is available."
            )
            spec["confidence"] = "medium"
        else:
            spec["decision"] = "unresolved"
            spec["operation"] = "unresolved"
            spec["selected_material_ids"] = []
            spec["selected_supporting_material_ids"] = supporting_ids
            spec["rationale"] = (
                f"The selected material is a {value_type} for {field_name}. This value cannot directly fill the field."
            )
            spec["confidence"] = "high"
    return field_resolutions


def _is_direct_assignment_legal(*, field_name: str, value_type: str) -> bool:
    if field_name.endswith("_events"):
        return value_type == "count"
    if field_name.endswith("_total"):
        return value_type == "total"
    if field_name.endswith("_mean"):
        return value_type == "mean"
    if field_name.endswith("_sd"):
        return value_type == "sd"
    return True


def _can_support_calculation(*, field_name: str, value_type: str) -> bool:
    if field_name.endswith("_events"):
        return value_type in {"percent", "total", "non_event_count"}
    if field_name.endswith("_sd"):
        return value_type in {"se", "ci_lower", "ci_upper", "total"}
    return False


def _find_narrower_arm_totals(*, materials: list[dict[str, Any]], arm: str, target_timepoint: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    arm_norm = arm.lower()
    for material in materials:
        if not isinstance(material, dict):
            continue
        if str(material.get("value_type") or "") != "total":
            continue
        scope = material.get("scope") if isinstance(material.get("scope"), dict) else {}
        basis = material.get("basis") if isinstance(material.get("basis"), dict) else {}
        material_arm = str(scope.get("arm") or "").lower()
        if arm_norm and material_arm and arm_norm not in material_arm and material_arm not in arm_norm:
            continue
        sample_frame = str(basis.get("sample_frame") or "")
        if sample_frame not in {"follow_up_respondents", "outcome_assessed"}:
            continue
        material_timepoint = str(scope.get("timepoint") or "").strip().lower()
        if target_timepoint and material_timepoint and target_timepoint not in material_timepoint and material_timepoint not in target_timepoint:
            continue
        results.append(material)
    return results


def _default_need_type(field: str) -> str:
    if field.endswith("_events"):
        return "missing_event_count"
    if field.endswith("_total"):
        return "missing_denominator"
    if field.endswith("_mean"):
        return "missing_mean"
    if field.endswith("_sd"):
        return "missing_sd"
    return "need_semantic_derivation_context"


def _acceptable_value_types(*, field: str, context: ExtractionContext) -> list[str]:
    data_type = str(context.data_type or "").strip().lower()
    if data_type == "dichotomous":
        if field.endswith("_events"):
            return ["count", "percent", "non_event_count"]
        if field.endswith("_total"):
            return ["total"]
    if data_type == "continuous":
        if field.endswith("_mean"):
            return ["mean"]
        if field.endswith("_sd"):
            return ["sd", "se", "ci_lower", "ci_upper"]
        if field.endswith("_total"):
            return ["total"]
    return []


def _recovery_goal(field: str) -> str:
    if field.endswith("_events"):
        return "Find a source-grounded event count or derivation inputs for this arm and candidate setting."
    if field.endswith("_total"):
        return "Find a source-grounded denominator compatible with this arm and candidate setting."
    if field.endswith("_mean"):
        return "Find a source-grounded arm-level mean compatible with this candidate setting."
    if field.endswith("_sd"):
        return "Find a source-grounded SD or derivation inputs compatible with this candidate setting."
    return "Find source-grounded material that resolves this field."


def _recovery_question(*, field: str, candidate: dict[str, Any], context: ExtractionContext) -> str:
    arm = _candidate_arm_label(field=field, candidate=candidate)
    arm_text = f" for the {arm} arm" if arm else ""
    data_type = str(context.data_type or "").strip().lower()
    if field.endswith("_events"):
        return (
            f"Find numeric evidence that can provide or support the event count{arm_text} for this candidate. "
            "The evidence may be a direct count or a clearly described intermediate material such as a percent, "
            "denominator, or non-event count."
        )
    if field.endswith("_total"):
        return (
            f"Find numeric evidence that can provide or support the sample size, total, or denominator{arm_text} "
            "for this candidate. Judge whether the numeric value is about the candidate arm and population/sample "
            "frame; do not require every outcome or timepoint detail unless the source makes the denominator "
            "outcome-specific or timepoint-specific."
        )
    if field.endswith("_mean"):
        return (
            f"Find numeric evidence that can provide or support the arm-level mean{arm_text} for this candidate. "
            "The evidence should match the candidate outcome or measure, timepoint, population, and statistic frame."
        )
    if field.endswith("_sd"):
        return (
            f"Find numeric evidence that can provide or support the SD{arm_text} for this candidate. The evidence "
            "may be a direct SD or a clearly described uncertainty input such as SE or CI for the same mean/statistic."
        )
    if data_type == "dichotomous":
        return f"Find numeric evidence that can provide or support this dichotomous field{arm_text} for the candidate."
    return f"Find numeric evidence that can provide or support this continuous field{arm_text} for the candidate."


def _normalize_calculation_plans(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        normalized.append(
            {
                "target_field": plan.get("target_field"),
                "calculator": plan.get("calculator"),
                "arguments": plan.get("arguments") if isinstance(plan.get("arguments"), dict) else {},
                "expression": plan.get("expression") or plan.get("generic_expression"),
                "assumptions": plan.get("assumptions") if isinstance(plan.get("assumptions"), list) else [],
                "rationale": plan.get("rationale"),
                "confidence": plan.get("confidence"),
            }
        )
    return normalized


def _calculation_plans_from_resolution(*, field_resolutions: dict[str, Any]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for field, spec in (field_resolutions.get("fields") or {}).items():
        if not isinstance(spec, dict):
            continue
        operation = str(spec.get("operation") or "")
        if operation not in {"supported_calculation", "generic_calculation"}:
            continue
        calculator = str(spec.get("calculator") or "").strip()
        arguments = spec.get("arguments") if isinstance(spec.get("arguments"), dict) else {}
        if operation == "generic_calculation":
            calculator = calculator or "generic_expression"
            if calculator != "generic_expression":
                continue
            generic_expression = spec.get("generic_expression")
            expression: str | None = None
            assumptions: list[Any] = []
            if isinstance(generic_expression, dict):
                expression = generic_expression.get("expression") or generic_expression.get("formula")
                arguments = generic_expression.get("variables") if isinstance(generic_expression.get("variables"), dict) else arguments
                assumptions = generic_expression.get("assumptions") if isinstance(generic_expression.get("assumptions"), list) else []
            elif generic_expression:
                expression = str(generic_expression)
            plans.append(
                {
                    "target_field": spec.get("target_field") or field,
                    "calculator": "generic_expression",
                    "arguments": arguments,
                    "expression": expression,
                    "assumptions": assumptions,
                    "rationale": spec.get("rationale"),
                    "confidence": spec.get("confidence"),
                }
            )
            continue
        if calculator and arguments:
            plans.append(
                {
                    "target_field": spec.get("target_field") or field,
                    "calculator": calculator,
                    "arguments": arguments,
                    "rationale": spec.get("rationale"),
                    "confidence": spec.get("confidence"),
                }
            )
    return _normalize_calculation_plans(plans)


def _apply_calculation_results(
    *,
    field_values: dict[str, dict[str, Any]],
    calculation_results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    updated = {key: dict(value) for key, value in field_values.items()}
    for result in calculation_results:
        if not isinstance(result, dict):
            continue
        if str(result.get("status") or "") != "calculated":
            continue
        target_field = str(result.get("target_field") or "")
        if not target_field:
            continue
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        input_material_ids = trace.get("input_material_ids") if isinstance(trace.get("input_material_ids"), dict) else {}
        updated[target_field] = {
            "status": "calculated",
            "value": result.get("value"),
            "material_ids": [str(value) for value in input_material_ids.values() if value],
            "calculation_trace": trace,
        }
    return updated


def _numeric_fields(
    *,
    required_fields: list[str],
    field_values: dict[str, dict[str, Any]],
    field_resolutions: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in required_fields:
        spec = (field_resolutions.get("fields") or {}).get(field) or {}
        value = field_values.get(field) or {}
        result[field] = {
            "decision": spec.get("decision"),
            "value": value.get("value"),
            "material_ids": value.get("material_ids") or [],
            "alternative_paths": spec.get("alternative_paths") or [],
            "rationale": spec.get("rationale"),
            "confidence": spec.get("confidence"),
        }
    return result


def _result_state(
    *,
    required_fields: list[str],
    result_data: dict[str, Any],
    complete_result_data: dict[str, Any] | None,
    materials: list[dict[str, Any]],
    field_resolutions: dict[str, Any],
) -> str:
    if complete_result_data is not None:
        return "complete"
    if result_data:
        return "partial"
    if materials:
        return "unresolved"
    return "needs_evidence"


def _numeric_material_value(material: dict[str, Any] | None) -> Any:
    if not isinstance(material, dict):
        return None
    value = material.get("value")
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text):
            return float(text)
    return None


def _has_value(value: dict[str, Any] | None) -> bool:
    if not isinstance(value, dict):
        return False
    return value.get("value") is not None


def _state_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        completion = candidate.get("completion") if isinstance(candidate.get("completion"), dict) else {}
        state = str(completion.get("result_state") or "not_run")
        counts[state] = counts.get(state, 0) + 1
    return counts


def _has_calculable_field(*, field_resolutions: dict[str, Any]) -> bool:
    for spec in (field_resolutions.get("fields") or {}).values():
        operation = str((spec or {}).get("operation") or "")
        if operation in {"supported_calculation", "generic_calculation"}:
            return True
        if str((spec or {}).get("decision") or "") == "needs_calculation":
            return True
    return False


def _has_legacy_calculable_field(*, field_resolutions: dict[str, Any]) -> bool:
    for spec in (field_resolutions.get("fields") or {}).values():
        if str((spec or {}).get("decision") or "") == "needs_calculation" and not str((spec or {}).get("calculator") or ""):
            return True
    return False


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _optional_env_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None
