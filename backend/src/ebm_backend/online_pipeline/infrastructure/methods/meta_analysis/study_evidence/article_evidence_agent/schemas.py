"""Strict structured-output schemas for the article evidence agent."""

from __future__ import annotations

from typing import Any


def controller_schema(*, section_ids: list[str], table_ids: list[str]) -> dict[str, Any]:
    return _object(
        {
            "action": {"type": "string", "enum": ["read_sections", "extract_tables", "ready"]},
            "section_ids": _array(_enum_or_string(section_ids)),
            "table_ids": _array(_enum_or_string(table_ids)),
            "study_map": study_map_schema(),
            "reason": _nullable_string(),
        }
    )


def study_map_schema() -> dict[str, Any]:
    return _object(
        {
            "study_design": _nullable_string(),
            "population": _nullable_string(),
            "treatment_duration": _nullable_string(),
            "follow_up": _array({"type": "string"}),
            "analysis_populations": _array({"type": "string"}),
            "arms": _array(
                _object(
                    {
                        "label": {"type": "string"},
                        "aliases": _array({"type": "string"}),
                        "role": {
                            "type": "string",
                            "enum": ["experimental", "control", "other", "unclear"],
                        },
                        "description": _nullable_string(),
                    }
                )
            ),
            "notes": _array({"type": "string"}),
        }
    )


def table_map_schema() -> dict[str, Any]:
    return _object(
        {
            "structure_status": {
                "type": "string",
                "enum": ["clear", "partially_clear", "unreadable"],
            },
            "header_paths": _array({"type": "string"}),
            "row_groups": _array({"type": "string"}),
            "arm_labels": _array({"type": "string"}),
            "timepoints": _array({"type": "string"}),
            "units": _array({"type": "string"}),
            "footnote_links": _array({"type": "string"}),
            "uncertainties": _array({"type": "string"}),
        }
    )


def table_result_schema() -> dict[str, Any]:
    arm = _object(
        {
            "label": {"type": "string"},
            "events": _nullable_number(),
            "non_events": _nullable_number(),
            "total": _nullable_number(),
            "total_kind": {
                "type": ["string", "null"],
                "enum": [
                    "analyzed",
                    "result_denominator",
                    "randomized",
                    "baseline",
                    "unclear",
                    None,
                ],
            },
            "percentage": _nullable_number(),
            "percentage_decimal_places": _nullable_integer(),
            "mean": _nullable_number(),
            "sd": _nullable_number(),
            "variance": _nullable_number(),
            "se": _nullable_number(),
            "ci_lower": _nullable_number(),
            "ci_upper": _nullable_number(),
            "ci_level": _nullable_number(),
            "uncertainty_scope": {
                "type": ["string", "null"],
                "enum": ["arm_mean", "arm_change_mean", "between_group", "unclear", None],
            },
            "source_quote": {"type": "string"},
        }
    )
    block = _object(
        {
            "outcome_label": _nullable_string(),
            "outcome_measure": _nullable_string(),
            "unit": _nullable_string(),
            "timepoint": _nullable_string(),
            "statistic_type": _nullable_string(),
            "population_or_subgroup": _nullable_string(),
            "analysis_population": _nullable_string(),
            "continuous_result_frame": {
                "type": ["string", "null"],
                "enum": [
                    "post_intervention",
                    "change_from_baseline",
                    "baseline",
                    "unclear",
                    None,
                ],
            },
            "change_score_definition": _nullable_string(),
            "scale_direction": {
                "type": ["string", "null"],
                "enum": ["higher_is_better", "higher_is_worse", "unclear", None],
            },
            "data_type": {"type": "string", "enum": ["Dichotomous", "Continuous"]},
            "arms": _array(arm),
            "block_materials": _array(numeric_material_schema()),
            "table_local_notes": _array({"type": "string"}),
            "uncertainties": _array({"type": "string"}),
        }
    )
    return _object(
        {
            "source_status": {
                "type": "string",
                "enum": ["results_found", "no_relevant_results", "unreadable"],
            },
            "result_blocks": _array(block),
            "support_materials": _array(support_material_schema()),
            "source_summary": _nullable_string(),
        }
    )


def numeric_material_schema() -> dict[str, Any]:
    return _object(
        {
            "kind": {
                "type": "string",
                "enum": [
                    "event_count",
                    "non_event_count",
                    "analyzed_total",
                    "result_denominator",
                    "randomized_total",
                    "baseline_total",
                    "outcome_complete_count",
                    "attrition_count",
                    "percentage",
                    "mean",
                    "standard_deviation",
                    "variance",
                    "standard_error",
                    "confidence_interval",
                    "effect_estimate",
                    "t_statistic",
                    "f_statistic",
                    "p_value",
                ],
            },
            "value": _nullable_number(),
            "lower": _nullable_number(),
            "upper": _nullable_number(),
            "confidence_level": _nullable_number(),
            "decimal_places": _nullable_integer(),
            "statistical_scope": {
                "type": "string",
                "enum": ["arm", "between_group", "study", "unclear"],
            },
            "applies_to": {
                "type": "string",
                "enum": [
                    "event_risk",
                    "mean",
                    "change_mean",
                    "mean_difference",
                    "standardized_mean_difference",
                    "ratio_effect",
                    "participant_flow",
                    "unclear",
                ],
            },
            "source_quote": {"type": "string"},
            "notes": _nullable_string(),
            "uncertainties": _array({"type": "string"}),
        }
    )


def support_material_schema() -> dict[str, Any]:
    return _object(
        {
            "arm_label": _nullable_string(),
            "outcome_label": _nullable_string(),
            "outcome_measure": _nullable_string(),
            "timepoint": _nullable_string(),
            "population_or_subgroup": _nullable_string(),
            "analysis_population": _nullable_string(),
            "material": numeric_material_schema(),
        }
    )


def support_recovery_schema() -> dict[str, Any]:
    return _object(
        {
            "support_materials": _array(support_material_schema()),
            "source_summary": _nullable_string(),
        }
    )


def resolution_schema(
    *,
    target_ids: list[str],
    candidate_ids: list[str],
    support_material_ids: list[str] | None = None,
) -> dict[str, Any]:
    support_ids = support_material_ids or []
    binding = _object(
        {
            "field": {
                "type": "string",
                "enum": [
                    "experimental_events",
                    "experimental_total",
                    "control_events",
                    "control_total",
                    "experimental_mean",
                    "experimental_sd",
                    "control_mean",
                    "control_sd",
                ],
            },
            "candidate_id": _enum_or_string(candidate_ids),
            "arm_label": {"type": "string"},
        }
    )
    resolution = _object(
        {
            "target_id": _enum_or_string(target_ids),
            "status": {
                "type": "string",
                "enum": ["resolved", "data_unavailable", "unresolved", "unsupported_dependency"],
            },
            "operation": {
                "type": ["string", "null"],
                "enum": [
                    "select_direct",
                    "combine_experimental_arms",
                    "combine_control_arms",
                    "combine_both_sides",
                    "deduplicate_same_result",
                    "cross_table_assembly",
                    "exclude",
                    "unresolved",
                    None,
                ],
            },
            "candidate_ids": _array(_enum_or_string(candidate_ids)),
            "support_material_ids": _array(_enum_or_string(support_ids)),
            "experimental_arm_labels": _array({"type": "string"}),
            "control_arm_labels": _array({"type": "string"}),
            "field_bindings": _array(binding),
            "excluded_candidate_ids": _array(_enum_or_string(candidate_ids)),
            "unresolved_candidate_ids": _array(_enum_or_string(candidate_ids)),
            "reason": {"type": "string"},
        }
    )
    return _object({"resolutions": _array(resolution)})


def verification_schema(
    *,
    target_ids: list[str],
    candidate_ids: list[str],
    support_material_ids: list[str] | None = None,
) -> dict[str, Any]:
    correction = resolution_schema(
        target_ids=target_ids,
        candidate_ids=candidate_ids,
        support_material_ids=support_material_ids,
    )["properties"]["resolutions"]["items"]
    return _object(
        {
            "valid": {"type": "boolean"},
            "issues": _array({"type": "string"}),
            "corrected_resolution": {"anyOf": [correction, {"type": "null"}]},
        }
    )


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _array(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def _nullable_string() -> dict[str, Any]:
    return {"type": ["string", "null"]}


def _nullable_number() -> dict[str, Any]:
    return {"type": ["number", "null"]}


def _nullable_integer() -> dict[str, Any]:
    return {"type": ["integer", "null"]}


def _enum_or_string(values: list[str]) -> dict[str, Any]:
    if values:
        return {"type": "string", "enum": values}
    return {"type": "string"}
