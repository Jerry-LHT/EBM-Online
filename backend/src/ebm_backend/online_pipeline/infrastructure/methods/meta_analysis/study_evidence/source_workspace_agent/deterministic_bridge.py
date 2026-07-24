"""Bridge verified semantic evidence into the existing deterministic core.

The replacement agent changes evidence reading, not the already-tested arm
calculators or MetaAnalysisDataRow assembly.  Keeping this bridge explicit makes
the temporary reuse visible and prevents LLM-produced arithmetic.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from statistics import NormalDist
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent import (
    method as stable_core,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent.calculators import (
    solve_arm,
)

from .evidence_state import (
    article_arm_label,
    source_spans,
    unique_dicts,
    unique_text,
)


POLICY_VERSION = "source_workspace_agent_v16_direction_adjudication"
DIRECT_FIELDS = {"direct_effect", "direct_uncertainty"}


def build_result(
    *,
    study_id: str,
    study_year: str | None,
    targets: list[dict[str, Any]],
    notebook: dict[str, Any],
    decisions: list[dict[str, Any]],
    verdicts: list[dict[str, Any]],
    coverage_complete: bool,
    coverage: dict[str, Any],
) -> dict[str, Any]:
    target_by_id = {str(row["target_id"]): row for row in targets}
    decision_by_id = {str(row["target_id"]): row for row in decisions}
    verdict_by_id = {str(row["target_id"]): row for row in verdicts}
    all_candidate_by_id = {
        str(row["candidate_id"]): row for row in notebook["candidates"]
    }
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    data_rows: list[dict[str, Any]] = []
    target_resolution_reasons: dict[str, dict[str, str]] = {}

    for target in targets:
        target_id = str(target["target_id"])
        decision = decision_by_id[target_id]
        assembled: dict[str, Any] | None = None
        resolution = _non_ready_resolution(decision)
        if decision["status"] == "ready":
            verdict = verdict_by_id.get(target_id)
            if verdict is None:
                resolution = _unresolved_resolution(
                    target_id=target_id,
                    candidate_ids=decision["candidate_ids"],
                    reason="Ready evidence did not receive a verification verdict.",
                )
            elif verdict["status"] == "unresolved":
                resolution = _unresolved_resolution(
                    target_id=target_id,
                    candidate_ids=verdict["selected_candidate_ids"]
                    or decision["candidate_ids"],
                    reason=verdict["reason"],
                )
            else:
                try:
                    resolution, assembled, error = _assemble_verified(
                        study_id=study_id,
                        study_year=study_year,
                        target=target,
                        study_map=notebook["study_map"],
                        verdict=verdict,
                        candidate_by_id=all_candidate_by_id,
                        excluded_candidate_ids=decision["excluded_candidate_ids"],
                    )
                except ValueError as exc:
                    resolution = _unresolved_resolution(
                        target_id=target_id,
                        candidate_ids=verdict["selected_candidate_ids"],
                        reason=(
                            "Verified evidence failed deterministic validation: "
                            f"{exc}"
                        ),
                    )
                    assembled = None
                    error = None
                if error:
                    resolution = _unresolved_resolution(
                        target_id=target_id,
                        candidate_ids=verdict["selected_candidate_ids"],
                        reason=(
                            "Verified semantic evidence failed deterministic "
                            f"assembly: {error}"
                        ),
                    )
                    assembled = None

        row = stable_core._study_result_row(
            study_id=study_id,
            study_year=study_year,
            target=target,
            candidates=notebook["candidates"],
            resolution=resolution,
            source_coverage_complete=coverage_complete,
        )
        record = stable_core._resolution_record(
            study_id=study_id,
            target=target,
            resolution=resolution,
            candidate_by_id=all_candidate_by_id,
            assembled=assembled,
        )
        record["applied_rule_ids"] = [POLICY_VERSION]
        reason_code = _resolution_reason_code(
            resolution=resolution,
            candidates=notebook["candidates"],
            target_data_type=str(target.get("data_type") or ""),
        )
        if reason_code is not None:
            # This is not necessarily an infrastructure failure.  The shared
            # record field is the established transport for a stable, machine
            # readable reason code; `reason` remains the human explanation.
            record["failure_code"] = reason_code
            record["failure_detail"] = str(resolution.get("reason") or "")
            record["failure_metadata"] = {
                "stage": "candidate_resolution",
                "candidate_boundary": "raw_table_only",
                "coverage_complete": coverage_complete,
            }
            row["extraction_status_reason"] = reason_code
            target_resolution_reasons[target_id] = {
                "status": str(resolution["status"]),
                "reason_code": reason_code,
                "reason_detail": str(resolution.get("reason") or ""),
            }
        rows.append(row)
        records.append(record)
        if assembled is not None:
            data_rows.append(assembled)

    return {
        "study_id": study_id,
        "study_result_rows": rows,
        "resolution_records": records,
        "data_rows": data_rows,
        "coverage": {
            **coverage,
            "target_resolution_reasons": target_resolution_reasons,
        },
    }


def _assemble_verified(
    *,
    study_id: str,
    study_year: str | None,
    target: dict[str, Any],
    study_map: dict[str, Any],
    verdict: dict[str, Any],
    candidate_by_id: dict[str, dict[str, Any]],
    excluded_candidate_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    selected_ids = list(verdict["selected_candidate_ids"])
    selected = {
        candidate_id: deepcopy(candidate_by_id[candidate_id])
        for candidate_id in selected_ids
        if candidate_id in candidate_by_id
    }
    if len(selected) != len(selected_ids):
        return (
            _unresolved_resolution(
                target_id=str(target["target_id"]),
                candidate_ids=selected_ids,
                reason="Verification selected an unavailable candidate.",
            ),
            None,
            "verification_selected_unavailable_candidate",
        )

    for candidate in selected.values():
        for arm in candidate.get("arms") or []:
            arm["materials"] = []
            arm["events"] = None
            arm["total"] = None
            arm["mean"] = None
            arm["sd"] = None
            arm["field_traces"] = {}
            arm["source_quote"] = ""

    support_materials: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    fields_by_material: dict[str, list[str]] = {}
    field_selection: dict[str, list[dict[str, Any]]] = {}
    for field_row in verdict["verified_fields"]:
        field = str(field_row["field"])
        reported_material_kind = str(field_row["material"].get("kind") or "")
        material = _prepare_material(
            field_row["material"],
            field=field,
            assumptions=verdict["assumptions"],
            selection_basis=str(field_row["selection_basis"]),
            selection_confidence=str(field_row["selection_confidence"]),
            selection_rationale=str(field_row["selection_rationale"]),
        )
        fields_by_material.setdefault(str(material["material_id"]), []).append(field)
        material["evidence_scope"] = deepcopy(field_row["evidence_scope"])
        material["article_arm_id"] = str(field_row.get("arm_id") or "") or None
        material["arm_label"] = str(field_row.get("arm_label") or "") or None
        material["verified_field"] = field
        material["source_ref"] = str(field_row.get("source_ref") or "") or None
        material["source_kind"] = str(field_row.get("source_kind") or "") or None
        field_selection.setdefault(field, []).append(
            {
                "material_ids": [str(material["material_id"])],
                "source_ref": str(field_row["source_ref"]),
                "source_kind": str(field_row["source_kind"]),
                "arm_id": str(field_row["arm_id"]),
                "arm_label": str(field_row["arm_label"]),
                "reported_material_kind": reported_material_kind,
                "material_kind": str(material.get("kind") or ""),
                "basis": str(field_row["selection_basis"]),
                "confidence": str(field_row["selection_confidence"]),
                "rationale": str(field_row["selection_rationale"]),
                "evidence_scope": deepcopy(field_row["evidence_scope"]),
            }
        )
        candidate_id = field_row.get("candidate_id")
        if candidate_id and field not in DIRECT_FIELDS:
            candidate = selected[str(candidate_id)]
            arm = _unique_arm(
                candidate=candidate,
                requested_arm_id=str(field_row["arm_id"]),
                requested_label=str(field_row["arm_label"]),
            )
            if arm is None:
                return (
                    _unresolved_resolution(
                        target_id=str(target["target_id"]),
                        candidate_ids=selected_ids,
                        reason="Verified evidence could not be bound to one article arm.",
                    ),
                    None,
                    f"ambiguous_verified_arm:{field_row['arm_label']}",
                )
            material["candidate_id"] = str(candidate_id)
            material["arm_label"] = str(arm["label"])
            arm["materials"].append(material)
            bindings.append(
                {
                    "field": field,
                    "candidate_id": str(candidate_id),
                    "arm_id": str(field_row["arm_id"]),
                    "arm_label": str(arm["label"]),
                }
            )
        else:
            material["candidate_id"] = str(candidate_id) if candidate_id else None
            support_materials.append(material)

    for candidate in selected.values():
        candidate_materials: list[dict[str, Any]] = []
        candidate_uncertainties: list[str] = []
        for arm in candidate.get("arms") or []:
            calculation = solve_arm(
                data_type=str(candidate["data_type"]),
                materials=arm["materials"],
            )
            arm["events"] = calculation.values.get("events")
            arm["total"] = calculation.values.get("total")
            arm["mean"] = calculation.values.get("mean")
            arm["sd"] = calculation.values.get("sd")
            arm["field_traces"] = calculation.field_traces
            arm["source_quote"] = " ... ".join(
                unique_text(
                    material.get("source_quote") for material in arm["materials"]
                )
            )
            candidate_materials.extend(arm["materials"])
            candidate_uncertainties.extend(calculation.warnings)
        candidate["uncertainties"] = unique_text(candidate_uncertainties)
        candidate["source_spans"] = source_spans(candidate_materials)
        direct_representation = DIRECT_FIELDS.issubset(field_selection)
        profile = (
            {
                "canonical_statistic_type": "direct mean difference and standard error",
                "analysis_input_representation": "generic_inverse_variance",
                "reported_statistic_kinds": sorted(
                    {
                        str(material.get("kind") or "")
                        for material in support_materials
                        if str(material.get("kind") or "")
                    }
                ),
                "status": "canonicalized",
            }
            if direct_representation
            else stable_core._statistic_profile(
                data_type=str(candidate["data_type"]),
                arms=candidate.get("arms") or [],
                block_materials=candidate.get("block_materials") or [],
                reported_statistic_type=None,
            )
        )
        candidate["local_setting"].update(
            {
                "reported_statistic_type": None,
                "statistic_type": profile["canonical_statistic_type"],
                "analysis_input_representation": profile[
                    "analysis_input_representation"
                ],
                "reported_statistic_kinds": profile["reported_statistic_kinds"],
                "statistic_type_status": profile["status"],
            }
        )

    operation = _resolution_operation(
        candidate_count=len(selected),
        support_count=len(support_materials),
        experimental_arm_count=len(verdict["experimental_arm_ids"]),
        control_arm_count=len(verdict["control_arm_ids"]),
    )
    target_id = str(target["target_id"])
    # Publish the verified, calculator-backed candidate state to the notebook
    # used for the article-local study-result row.  Otherwise that row would
    # retain the census-time "incomplete" statistic profile even though the
    # verifier supplied all final fields.
    for candidate_id, resolved_candidate in selected.items():
        if candidate_id in candidate_by_id:
            candidate_by_id[candidate_id].clear()
            candidate_by_id[candidate_id].update(deepcopy(resolved_candidate))
    resolution = {
        "target_id": target_id,
        "status": "resolved",
        "operation": operation,
        "candidate_ids": selected_ids,
        "support_material_ids": [
            str(material["material_id"]) for material in support_materials
        ],
        "experimental_arm_ids": list(verdict["experimental_arm_ids"]),
        "control_arm_ids": list(verdict["control_arm_ids"]),
        "experimental_arm_labels": [
            article_arm_label(arm_id=arm_id, study_map=study_map)
            for arm_id in verdict["experimental_arm_ids"]
        ],
        "control_arm_labels": [
            article_arm_label(arm_id=arm_id, study_map=study_map)
            for arm_id in verdict["control_arm_ids"]
        ],
        "field_bindings": unique_dicts(bindings),
        "excluded_candidate_ids": list(excluded_candidate_ids),
        "unresolved_candidate_ids": [],
        "reason": verdict["reason"],
    }
    continuous_semantics = verdict.get("continuous_semantics") or {}
    direct_effect_semantics = verdict.get("direct_effect_semantics") or {}
    if str(target.get("data_type") or "") == "Continuous":
        scale_direction = str(
            continuous_semantics.get("scale_direction") or "unclear"
        )
        for candidate in selected.values():
            if scale_direction in {"higher_is_better", "higher_is_worse"}:
                candidate["local_setting"]["scale_direction"] = scale_direction
            candidate["local_setting"]["scale_direction_basis"] = (
                continuous_semantics.get("basis")
            )
            candidate["local_setting"]["scale_direction_confidence"] = (
                continuous_semantics.get("confidence")
            )
            candidate["local_setting"]["scale_direction_rationale"] = (
                continuous_semantics.get("rationale")
            )
            if DIRECT_FIELDS.issubset(field_selection):
                candidate["local_setting"]["change_score_direction"] = str(
                    direct_effect_semantics.get("change_score_direction")
                    or "unclear"
                )
    if DIRECT_FIELDS.issubset(field_selection):
        assembled, error = _assemble_direct_effect(
            study_id=study_id,
            study_year=study_year,
            target=target,
            study_map=study_map,
            resolution=resolution,
            selected=selected,
            verified_fields=verdict["verified_fields"],
            direct_effect_semantics=direct_effect_semantics,
        )
    else:
        assembled, error = stable_core._assemble_resolution(
            study_id=study_id,
            target=target,
            study_map=study_map,
            resolution=resolution,
            candidate_by_id=selected,
            support_materials=support_materials,
            study_year=study_year,
            allow_unoriented_post_intervention=True,
        )
    if assembled is not None:
        _normalize_assembled_source_spans(
            assembled,
            support_materials=support_materials,
        )
        _attach_selection_audit(
            assembled,
            field_selection=field_selection,
            verified_material_ids=sorted(fields_by_material),
            assumptions=verdict["assumptions"],
        )
    return resolution, assembled, error


def _assemble_direct_effect(
    *,
    study_id: str,
    study_year: str | None,
    target: dict[str, Any],
    study_map: dict[str, Any],
    resolution: dict[str, Any],
    selected: dict[str, dict[str, Any]],
    verified_fields: list[dict[str, Any]],
    direct_effect_semantics: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Build a GIV row from a verified between-group MD and uncertainty."""

    by_field = {
        str(row["field"]): row
        for row in verified_fields
        if str(row.get("field") or "") in DIRECT_FIELDS
    }
    if set(by_field) != DIRECT_FIELDS:
        return None, "Direct-effect assembly requires one effect and one uncertainty field."
    effect_material = by_field["direct_effect"]["material"]
    uncertainty_material = by_field["direct_uncertainty"]["material"]
    raw_effect = _finite_number(effect_material.get("value"))
    if raw_effect is None:
        return None, "Direct-effect material does not contain a finite effect value."
    standard_error, uncertainty_trace, error = _direct_standard_error(
        effect=raw_effect,
        material=uncertainty_material,
    )
    if error:
        return None, error
    source_directions = {
        str((row.get("evidence_scope") or {}).get("comparison_direction") or "")
        for row in by_field.values()
    }
    explicit_source_directions = source_directions - {
        "",
        "unclear",
        "not_applicable",
    }
    if len(explicit_source_directions) > 1:
        return None, "Direct effect and uncertainty use inconsistent comparison directions."
    adjudicated_direction = str(
        direct_effect_semantics.get("comparison_direction") or ""
    )
    if explicit_source_directions and adjudicated_direction not in explicit_source_directions:
        return None, (
            "Adjudicated direct-effect direction conflicts with a source-reported "
            "comparison direction."
        )
    direction_multiplier = {
        "experimental_minus_control": 1,
        "control_minus_experimental": -1,
    }.get(adjudicated_direction)
    if direction_multiplier is None:
        return None, "Direct effect comparison direction is not interpretable."

    local_setting = deepcopy(next(iter(selected.values()))["local_setting"])
    source_change_directions = {
        str((row.get("evidence_scope") or {}).get("change_score_direction") or "")
        for row in by_field.values()
    }
    explicit_source_change_directions = source_change_directions - {
        "",
        "unclear",
        "not_applicable",
    }
    if len(explicit_source_change_directions) > 1:
        return None, "Direct effect and uncertainty use inconsistent change-score directions."
    adjudicated_change_direction = str(
        direct_effect_semantics.get("change_score_direction") or ""
    )
    if (
        explicit_source_change_directions
        and adjudicated_change_direction not in explicit_source_change_directions
    ):
        return None, (
            "Adjudicated direct-effect change direction conflicts with a "
            "source-reported direction."
        )
    if adjudicated_change_direction:
        local_setting["change_score_direction"] = adjudicated_change_direction
    alignment = stable_core._continuous_alignment(local_setting)
    if alignment["effect_multiplier"] not in {-1, 1}:
        if (
            alignment["result_frame"] == "post_intervention"
            and alignment["change_score_definition"] == "not_applicable"
        ):
            alignment = {
                **alignment,
                "scale_direction": "unclear",
                "effect_multiplier": 1,
                "status": "ready",
                "rationale": (
                    "The direct between-group estimate is retained on its reported "
                    "experimental-minus-control measurement scale; clinical high/low "
                    "direction remains unavailable for downstream interpretation."
                ),
            }
        else:
            return None, "Direct continuous result lacks an interpretable scale/change direction."
    alignment["direct_effect_direction_adjudication"] = deepcopy(
        direct_effect_semantics
    )
    participant_count = _direct_participant_count(
        selected=list(selected.values()),
        experimental_arm_ids=resolution["experimental_arm_ids"],
        control_arm_ids=resolution["control_arm_ids"],
        verified_fields=verified_fields,
    )
    effect_value = raw_effect * direction_multiplier
    result_data = {
        "effect_value": effect_value,
        "standard_error": standard_error,
        "effect_measure": "Mean Difference",
        "analysis_scale": "natural",
        "participant_count": participant_count,
    }
    experimental_labels = list(resolution["experimental_arm_labels"])
    control_labels = list(resolution["control_arm_labels"])
    target_id = str(target["target_id"])
    resolution_id = f"resolution::{target_id}::{stable_core._slug(study_id)}"
    candidate_ids = list(selected)
    materials = [effect_material, uncertainty_material]
    spans = source_spans(materials)
    derivation = {
        "method": "generic_inverse_variance",
        "computed_fields": ["standard_error"] if uncertainty_trace["method"] == "ci_to_se" else [],
        "input_values": {
            "reported_effect": raw_effect,
            "source_comparison_directions": sorted(source_directions),
            "adjudicated_comparison_direction": adjudicated_direction,
            "comparison_direction_multiplier": direction_multiplier,
            "source_change_score_directions": sorted(source_change_directions),
            "adjudicated_change_score_direction": adjudicated_change_direction,
            "direction_adjudication": deepcopy(direct_effect_semantics),
            "uncertainty": uncertainty_trace,
            "participant_count": participant_count,
        },
        "formula": uncertainty_trace["formula"],
        "notes": (
            "The LLM selected and scoped reported evidence; deterministic code "
            "normalized comparison direction and uncertainty."
        ),
    }
    setting = stable_core._external_setting(
        local_setting,
        experimental_labels,
        control_labels,
    )
    setting.update(
        {
            "statistic_type": "direct mean difference and standard error",
            "analysis_input_representation": "generic_inverse_variance",
            "statistic_type_status": "canonicalized",
        }
    )
    result_item = {
        "candidate_id": f"resolved::{stable_core._slug(target_id)}::{stable_core._slug(study_id)}",
        "source_candidate_ids": candidate_ids,
        "match_status": "matched",
        "study_result_setting": setting,
        "data_type": "Continuous",
        "result_data": result_data,
        "include_in_estimate": True,
        "analysis_disposition": "ready_for_estimate",
        "resolution_reason": resolution_id,
        "resolution_operation": "select_direct_effect",
        "derivation": derivation,
        "source_spans": spans,
        "numeric_extraction": {"direct_effect": result_data},
        "continuous_effect_alignment": alignment,
    }
    row = {
        "data_row_id": f"data-row::{stable_core._slug(target_id)}::{stable_core._slug(study_id)}",
        "row_id": f"data-row::{stable_core._slug(target_id)}::{stable_core._slug(study_id)}",
        "setting_id": target_id,
        "setting_family_id": str(target.get("setting_family_id") or target_id),
        "study_id": study_id,
        "study_year": study_year,
        "data_type": "Continuous",
        "comparison": {
            "experimental_arm": " + ".join(experimental_labels),
            "control_arm": " + ".join(control_labels),
        },
        "outcome": {
            "label": str((target.get("outcome") or {}).get("label") or ""),
            "timepoint": stable_core._optional_text((target.get("timepoint") or {}).get("label")),
        },
        "subgroup": target.get("subgroup") or {"factor": None, "level": None},
        "result_data": result_data,
        "source_candidate_ids": candidate_ids,
        "resolution_id": resolution_id,
        "result_items": [result_item],
        "derivation": derivation,
        "continuous_effect_alignment": alignment,
        "source_spans": spans,
        "analysis_status": "pending",
    }
    return row, None


def _direct_standard_error(
    *,
    effect: float,
    material: dict[str, Any],
) -> tuple[float, dict[str, Any], str | None]:
    kind = str(material.get("kind") or "")
    if kind == "standard_error":
        value = _finite_number(material.get("value"))
        if value is None or value <= 0:
            return 0.0, {}, "Direct standard error must be finite and positive."
        return value, {
            "method": "reported_se",
            "reported_standard_error": value,
            "formula": "SE = reported SE",
        }, None
    if kind != "confidence_interval":
        return 0.0, {}, "Direct uncertainty must be a reported SE or confidence interval."
    lower = _finite_number(material.get("lower"))
    upper = _finite_number(material.get("upper"))
    level = _finite_number(material.get("confidence_level"))
    if lower is None or upper is None or level is None or not lower < upper:
        return 0.0, {}, "Direct confidence interval is incomplete or invalid."
    normalized_level = _confidence_level_percent(level)
    if normalized_level is None or not lower <= effect <= upper:
        return 0.0, {}, "Direct effect is incompatible with its confidence interval."
    critical = NormalDist().inv_cdf(0.5 + normalized_level / 200.0)
    if not math.isfinite(critical) or critical <= 0:
        return 0.0, {}, "Direct confidence level cannot be converted to a critical value."
    standard_error = (upper - lower) / (2.0 * critical)
    if not math.isfinite(standard_error) or standard_error <= 0:
        return 0.0, {}, "Direct confidence interval produced an invalid standard error."
    return standard_error, {
        "method": "ci_to_se",
        "ci_lower": lower,
        "ci_upper": upper,
        "reported_confidence_level": level,
        "confidence_level_percent": normalized_level,
        "critical_value": critical,
        "formula": "SE = (CI upper - CI lower) / (2 * normal critical value)",
    }, None


def _confidence_level_percent(value: float) -> float | None:
    if 0 < value < 1:
        return value * 100.0
    if 1 < value < 100:
        return value
    return None


def _direct_participant_count(
    *,
    selected: list[dict[str, Any]],
    experimental_arm_ids: list[str],
    control_arm_ids: list[str],
    verified_fields: list[dict[str, Any]],
) -> int | None:
    verified_totals: dict[str, set[int]] = {}
    for field_row in verified_fields:
        field = str(field_row.get("field") or "")
        if field not in {"experimental_total", "control_total"}:
            continue
        arm_id = str(field_row.get("arm_id") or "")
        value = _finite_number((field_row.get("material") or {}).get("value"))
        if arm_id and value is not None and value.is_integer() and value > 0:
            verified_totals.setdefault(arm_id, set()).add(int(value))
    selected_ids = [*experimental_arm_ids, *control_arm_ids]
    if all(len(verified_totals.get(arm_id, set())) == 1 for arm_id in selected_ids):
        return sum(next(iter(verified_totals[arm_id])) for arm_id in selected_ids)

    values_by_arm: dict[str, set[int]] = {}
    for candidate in selected:
        for arm in candidate.get("arms") or []:
            arm_id = str(arm.get("article_arm_id") or "")
            value = _finite_number(arm.get("total"))
            if arm_id and value is not None and value.is_integer() and value > 0:
                values_by_arm.setdefault(arm_id, set()).add(int(value))
    if any(len(values_by_arm.get(arm_id, set())) != 1 for arm_id in selected_ids):
        return None
    return sum(next(iter(values_by_arm[arm_id])) for arm_id in selected_ids)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_assembled_source_spans(
    assembled: dict[str, Any],
    *,
    support_materials: list[dict[str, Any]],
) -> None:
    """Restore section/table provenance after using the shared assembler."""

    source_kinds = {
        str(material.get("source_ref") or material.get("source_table_id") or ""):
        str(material.get("source_kind") or "table")
        for material in support_materials
    }

    def normalize(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for raw in spans:
            span = deepcopy(raw)
            source_ref = str(span.get("source_id") or "")
            if source_kinds.get(source_ref) == "section":
                span["table_id"] = None
                span["section"] = source_ref
            result.append(span)
        return unique_dicts(result)

    assembled["source_spans"] = normalize(assembled.get("source_spans") or [])
    for item in assembled.get("result_items") or []:
        item["source_spans"] = normalize(item.get("source_spans") or [])


def _prepare_material(
    material: dict[str, Any],
    *,
    field: str,
    assumptions: list[str],
    selection_basis: str,
    selection_confidence: str,
    selection_rationale: str,
) -> dict[str, Any]:
    result = deepcopy(material)
    if result.get("trace_warnings"):
        raise ValueError(
            f"Verified material has source trace warnings: {result['trace_warnings']}"
        )
    if (
        "numeric_value_not_found_in_source_locator" in (result.get("uncertainties") or [])
        and not (
            str(result.get("kind") or "") == "confidence_interval"
            and _finite_number(result.get("lower")) is not None
            and _finite_number(result.get("upper")) is not None
            and _finite_number(result.get("confidence_level")) is not None
        )
    ):
        raise ValueError("Verified numeric value is absent from its source quote")
    result["verified_uncertainties"] = list(result.get("uncertainties") or [])
    result["uncertainties"] = []
    kind = str(result.get("kind") or "")
    if field.endswith("_total") and kind in {
        "randomized_total",
        "baseline_total",
        "outcome_complete_count",
    }:
        result["kind"] = "analyzed_total"
        result["derivation_trace"] = {
            "method": "semantic_evidence_binding",
            "formula": f"analyzed_total = selected {kind}",
            "input_material_ids": [str(result["material_id"])],
            "assumptions": list(assumptions),
            "selection_basis": selection_basis,
            "selection_confidence": selection_confidence,
        }
    result["selected_for_fields"] = [field]
    result["verification_assumptions"] = list(assumptions)
    result["selection_basis"] = selection_basis
    result["selection_confidence"] = selection_confidence
    result["selection_rationale"] = selection_rationale
    return result


def _attach_selection_audit(
    assembled: dict[str, Any],
    *,
    field_selection: dict[str, list[dict[str, Any]]],
    verified_material_ids: list[str],
    assumptions: list[str],
) -> None:
    """Keep semantic source selection visible without changing the public row shape."""

    scope_assessment = _scope_assessment(field_selection)
    existing = deepcopy(assembled.get("derivation") or {})
    input_values = (
        deepcopy(existing.get("input_values"))
        if isinstance(existing.get("input_values"), dict)
        else {}
    )
    input_values["verified_material_ids"] = list(verified_material_ids)
    input_values["field_selection"] = deepcopy(field_selection)
    input_values["scope_assessment"] = deepcopy(scope_assessment)
    if existing.get("method") and existing.get("method") != "direct":
        input_values.setdefault("assembly_method", existing.get("method"))
    existing.update(
        {
            "method": "source_grounded_semantic_verification",
            "computed_fields": list(existing.get("computed_fields") or []),
            "input_values": input_values,
            "formula": existing.get("formula")
            or "No LLM arithmetic; deterministic arm calculator only.",
        }
    )
    notes = [str(existing.get("notes") or "").strip(), *assumptions]
    existing["notes"] = "; ".join(
        item for item in notes if item
    ) or "Semantic field selection was verified against the raw source."
    assembled["derivation"] = existing
    for item in assembled.get("result_items") or []:
        item["derivation"] = deepcopy(existing)
        item["evidence_scope_assessment"] = deepcopy(scope_assessment)
        # Keep the established disposition vocabulary for downstream adapters;
        # residual scope quality is carried by the explicit assessment below.
        item["analysis_disposition"] = "ready_for_estimate"
        # Keep the contribution usable for fully automatic synthesis while
        # making inferred/ambiguous scope visible to downstream consumers.
        # `include_in_estimate` remains true by design; deterministic pooling
        # must not silently drop the best-supported article value.
        item["include_in_estimate"] = True
        numeric_extraction = item.setdefault("numeric_extraction", {})
        numeric_extraction["field_selection"] = deepcopy(field_selection)
        numeric_extraction["scope_assessment"] = deepcopy(scope_assessment)


def _scope_assessment(
    field_selection: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Summarize residual evidence-scope uncertainty after verification.

    This is a deterministic presentation/trace layer.  It does not reject a
    value selected by the verifier and it never decides which denominator is
    correct; it tells downstream stages whether any selected field relied on
    an inference, lower confidence, or incomplete scope.
    """

    warnings: list[str] = []
    provisional_fields: list[str] = []
    for field, selections in field_selection.items():
        for selection in selections:
            scope = selection.get("evidence_scope") or {}
            status = str(scope.get("scope_status") or "missing")
            basis = str(selection.get("basis") or "")
            confidence = str(selection.get("confidence") or "")
            field_warning: list[str] = []
            if status != "complete":
                field_warning.append(f"scope_status={status}")
            if basis != "direct":
                field_warning.append(f"selection_basis={basis or 'missing'}")
            if confidence != "high":
                field_warning.append(
                    f"selection_confidence={confidence or 'missing'}"
                )
            if field.endswith("_total") and str(
                scope.get("denominator_scope") or ""
            ) in {"randomized_or_baseline", "unclear"}:
                field_warning.append(
                    "denominator_scope="
                    + str(scope.get("denominator_scope") or "unclear")
                )
            if field_warning:
                provisional_fields.append(field)
                warnings.append(f"{field}: " + ", ".join(field_warning))
    warnings = unique_text(warnings)
    provisional_fields = unique_text(provisional_fields)
    return {
        "status": "complete" if not warnings else "provisional",
        "warnings": warnings,
        "provisional_fields": provisional_fields,
    }


def _unique_arm(
    *,
    candidate: dict[str, Any],
    requested_arm_id: str,
    requested_label: str,
) -> dict[str, Any] | None:
    matches = [
        arm
        for arm in candidate.get("arms") or []
        if str(arm.get("article_arm_id") or "") == requested_arm_id
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return None

    # Verification may repair an investigator omission, but it must point to
    # exactly one still-unbound candidate arm using the raw observed label.
    # This is identity binding, not semantic/fuzzy arm matching.
    requested_key = _arm_surface_key(requested_label)
    unbound_matches = [
        arm
        for arm in candidate.get("arms") or []
        if not str(arm.get("article_arm_id") or "")
        and requested_key
        and _arm_surface_key(str(arm.get("label") or "")) == requested_key
    ]
    if len(unbound_matches) != 1:
        return None
    unbound_matches[0]["article_arm_id"] = requested_arm_id
    unbound_matches[0]["identity_status"] = "verification_bound"
    return unbound_matches[0]


def _arm_surface_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _resolution_operation(
    *,
    candidate_count: int,
    support_count: int,
    experimental_arm_count: int,
    control_arm_count: int,
) -> str:
    if candidate_count > 1 or support_count:
        return "cross_table_assembly"
    if experimental_arm_count > 1 and control_arm_count > 1:
        return "combine_both_sides"
    if experimental_arm_count > 1:
        return "combine_experimental_arms"
    if control_arm_count > 1:
        return "combine_control_arms"
    return "select_direct"


def _non_ready_resolution(decision: dict[str, Any]) -> dict[str, Any]:
    status = str(decision["status"])
    if status == "ready":
        return _unresolved_resolution(
            target_id=str(decision["target_id"]),
            candidate_ids=list(decision["candidate_ids"]),
            reason="Ready evidence has not yet been verified.",
        )
    operation = "unresolved" if status == "unresolved" else "exclude"
    return {
        "target_id": str(decision["target_id"]),
        "status": status,
        "operation": operation,
        "candidate_ids": [],
        "support_material_ids": [],
        "experimental_arm_labels": [],
        "control_arm_labels": [],
        "field_bindings": [],
        "excluded_candidate_ids": list(decision["excluded_candidate_ids"]),
        "unresolved_candidate_ids": (
            list(decision["candidate_ids"]) if status == "unresolved" else []
        ),
        "reason": str(decision["reason"]),
    }


def _resolution_reason_code(
    *,
    resolution: dict[str, Any],
    candidates: list[dict[str, Any]],
    target_data_type: str,
) -> str | None:
    """Classify a non-ready decision without changing its evidence policy.

    The resolver supplies the detailed natural-language reason.  This helper
    adds a conservative code from deterministic state so downstream callers do
    not have to infer a business disposition from `data_unavailable` alone.
    """

    status = str(resolution.get("status") or "")
    if status == "resolved":
        return None
    if status == "data_unavailable":
        has_target_type_candidate = any(
            str(candidate.get("data_type") or "") == target_data_type
            for candidate in candidates
        )
        return (
            "no_compatible_table_candidate"
            if has_target_type_candidate
            else "no_eligible_table_candidate"
        )
    if status == "unsupported_dependency":
        return "unsupported_reported_statistic"
    if status == "unresolved":
        return "unresolved_table_candidate"
    return "unknown_resolution_status"


def _unresolved_resolution(
    *,
    target_id: str,
    candidate_ids: list[str],
    reason: str,
) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "status": "unresolved",
        "operation": "unresolved",
        "candidate_ids": [],
        "support_material_ids": [],
        "experimental_arm_labels": [],
        "control_arm_labels": [],
        "field_bindings": [],
        "excluded_candidate_ids": [],
        "unresolved_candidate_ids": list(candidate_ids),
        "reason": reason,
    }
