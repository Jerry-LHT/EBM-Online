"""Strict structured-output schemas for the source-workspace evidence agent."""

from __future__ import annotations

from typing import Any


MATERIAL_KINDS = [
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
]

FINAL_FIELDS = [
    "experimental_events",
    "experimental_total",
    "control_events",
    "control_total",
    "experimental_mean",
    "experimental_sd",
    "control_mean",
    "control_sd",
    "direct_effect",
    "direct_uncertainty",
]

DIRECT_FIELDS = {"direct_effect", "direct_uncertainty"}

# These describe how the verifier selected a source value.  They are semantic
# audit labels, not deterministic precedence rules: the model still has to
# inspect the supplied raw source and explain why one interpretation is the
# best-supported one.
SELECTION_BASES = [
    "direct",
    "supported_inference",
    "assumption",
]
SELECTION_CONFIDENCES = ["high", "medium", "low"]
SCOPE_STATUSES = ["complete", "requires_audit", "incomplete"]
RESULT_FRAMES = [
    "post_intervention",
    "change_from_baseline",
    "baseline",
    "not_applicable",
    "unclear",
]
CHANGE_SCORE_DIRECTIONS = [
    "post_minus_baseline",
    "baseline_minus_post",
    "not_applicable",
    "unclear",
]
DIRECTION_BASES = [
    "source_reported",
    "cross_source_inference",
    "insufficient_information",
    "not_applicable",
]
DIRECTION_CONFIDENCES = ["high", "medium", "low", "not_applicable"]
DENOMINATOR_SCOPES = [
    "not_applicable",
    "result_cell_or_row",
    "result_column",
    "outcome_complete",
    "analysis_population",
    "randomized_or_baseline",
    "unclear",
]


def table_census_schema(*, source_refs: list[str]) -> dict[str, Any]:
    return _object(
        {
            "source_observations": _array(
                _object(
                    {
                        "source_ref": _enum_or_string(source_refs),
                        "source_status": {
                            "type": "string",
                            "enum": [
                                "target_relevant",
                                "support_only",
                                "no_target_evidence",
                                "uncertain",
                            ],
                        },
                        "summary": {"type": "string"},
                        "candidate_blocks": _array(
                            _candidate_schema(source_refs=source_refs)
                        ),
                        "support_materials": _array(
                            _support_schema(source_refs=source_refs)
                        ),
                        "study_map_update": _study_map_schema(
                            source_refs=source_refs
                        ),
                        "evidence_needs": _array({"type": "string"}),
                    }
                )
            )
        }
    )


def investigator_schema(
    *,
    table_refs: list[str],
    section_refs: list[str],
    evidence_need_ids: list[str] | None = None,
    allowed_actions: list[str] | None = None,
) -> dict[str, Any]:
    all_refs = [*table_refs, *section_refs]
    actions = list(
        allowed_actions
        or ["finish", "search_sections", "read_sources"]
    )
    invalid_actions = set(actions) - {"finish", "search_sections", "read_sources"}
    if not actions or invalid_actions:
        raise ValueError(f"Unsupported investigator actions: {sorted(invalid_actions)}")
    return _object(
        {
            "action": {
                "type": "string",
                "enum": actions,
            },
            "queries": _array({"type": "string"}),
            "source_refs": _array(_enum_or_string(all_refs)),
            "candidate_blocks": _array(_candidate_schema(source_refs=table_refs)),
            "support_materials": _array(_support_schema(source_refs=all_refs)),
            "study_map_update": _study_map_schema(source_refs=all_refs),
            "claims": _array(
                _object(
                    {
                        "claim": {"type": "string"},
                        "scope": {"type": "string"},
                        "source_refs": _array(_enum_or_string(all_refs)),
                    }
                )
            ),
            "alternatives": _array(
                _object(
                    {
                        "question": {"type": "string"},
                        "interpretations": _array({"type": "string"}),
                        "source_refs": _array(_enum_or_string(all_refs)),
                    }
                )
            ),
            "open_questions": _array({"type": "string"}),
            "evidence_need_updates": _array(
                _object(
                    {
                        "need_id": _enum_or_string(evidence_need_ids or []),
                        "status": {
                            "type": "string",
                            "enum": ["resolved", "blocked", "superseded"],
                        },
                        "source_refs": _array(_enum_or_string(all_refs)),
                        "reason": {"type": "string"},
                    }
                )
            ),
            "reason": {"type": "string"},
        }
    )


def arm_reconciliation_schema(
    *,
    observation_ids: list[str],
    source_refs: list[str],
) -> dict[str, Any]:
    return _object(
        {
            "canonical_arms": _array(
                _object(
                    {
                        "canonical_label": {"type": "string"},
                        "aliases": _array({"type": "string"}),
                        "role": {
                            "type": "string",
                            "enum": ["experimental", "control", "other", "unclear"],
                        },
                        "description": _nullable_string(),
                        "member_observation_ids": _array(
                            _enum_or_string(observation_ids)
                        ),
                        "evidence_source_refs": _array(
                            _enum_or_string(source_refs)
                        ),
                        "rationale": {"type": "string"},
                    }
                )
            ),
            "unresolved_observation_ids": _array(
                _enum_or_string(observation_ids)
            ),
            "notes": _array({"type": "string"}),
        }
    )


def resolution_schema(
    *,
    target_ids: list[str],
    candidate_ids: list[str],
    material_ids: list[str],
    arm_ids: list[str],
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    return _object(
        {
            "decisions": _array(
                _resolution_decision_schema(
                    target_ids=target_ids,
                    candidate_ids=candidate_ids,
                    material_ids=material_ids,
                    arm_ids=arm_ids,
                    source_refs=source_refs,
                )
            )
        }
    )


def verification_schema(
    *,
    target_ids: list[str],
    candidate_ids: list[str],
    arm_ids: list[str],
    source_refs: list[str],
) -> dict[str, Any]:
    field_material = _object(
        {
            "field": {"type": "string", "enum": FINAL_FIELDS},
            "candidate_id": _nullable_enum(candidate_ids),
            "source_ref": _enum_or_string(source_refs),
            "source_kind": {"type": "string", "enum": ["table", "section"]},
            "arm_id": _nullable_enum(arm_ids),
            "observed_arm_label": _nullable_string(),
            "material": _material_schema(),
            "evidence_scope": _evidence_scope_schema(source_refs=source_refs),
            "selection_basis": {
                "type": "string",
                "enum": SELECTION_BASES,
            },
            "selection_confidence": {
                "type": "string",
                "enum": SELECTION_CONFIDENCES,
            },
            "selection_rationale": {"type": "string"},
        }
    )
    return _object(
        {
            "verdicts": _array(
                _object(
                    {
                        "target_id": _enum_or_string(target_ids),
                        "status": {
                            "type": "string",
                            "enum": ["confirmed", "corrected", "unresolved"],
                        },
                        "selected_candidate_ids": _array(
                            _enum_or_string(candidate_ids)
                        ),
                        "experimental_arm_ids": _array(_enum_or_string(arm_ids)),
                        "control_arm_ids": _array(_enum_or_string(arm_ids)),
                        "field_evidence": _array(field_material),
                        "competing_interpretations": _array({"type": "string"}),
                        "assumptions": _array({"type": "string"}),
                        "reason": {"type": "string"},
                    }
                )
            )
        }
    )


def source_verification_schema(
    *,
    target_ids: list[str],
    candidate_ids: list[str],
    arm_ids: list[str],
    source_ref: str,
) -> dict[str, Any]:
    """Return source-local evidence cards without requiring a complete result row."""

    field_material = _object(
        {
            "field": {"type": "string", "enum": FINAL_FIELDS},
            "candidate_id": _nullable_enum(candidate_ids),
            "source_ref": {"type": "string", "enum": [source_ref]},
            "source_kind": {"type": "string", "enum": ["table", "section"]},
            "arm_id": _nullable_enum(arm_ids),
            "observed_arm_label": _nullable_string(),
            "material": _material_schema(),
            "evidence_scope": _evidence_scope_schema(source_refs=[source_ref]),
            "selection_basis": {
                "type": "string",
                "enum": SELECTION_BASES,
            },
            "selection_confidence": {
                "type": "string",
                "enum": SELECTION_CONFIDENCES,
            },
            "selection_rationale": {"type": "string"},
        }
    )
    return _object(
        {
            "source_reviews": _array(
                _object(
                    {
                        "target_id": _enum_or_string(target_ids),
                        "source_status": {
                            "type": "string",
                            "enum": [
                                "evidence_found",
                                "no_relevant_evidence",
                                "unresolved",
                            ],
                        },
                        "selected_candidate_ids": _array(
                            _enum_or_string(candidate_ids)
                        ),
                        "field_evidence": _array(field_material),
                        "competing_interpretations": _array({"type": "string"}),
                        "reason": {"type": "string"},
                    }
                )
            )
        }
    )


def cross_source_adjudication_schema(
    *,
    target_ids: list[str],
    candidate_ids: list[str],
    arm_ids: list[str],
    evidence_ids: list[str],
) -> dict[str, Any]:
    """Select already-grounded source-local evidence into final verdicts."""

    return _object(
        {
            "verdicts": _array(
                _object(
                    {
                        "target_id": _enum_or_string(target_ids),
                        "status": {
                            "type": "string",
                            "enum": ["confirmed", "corrected", "unresolved"],
                        },
                        "selected_candidate_ids": _array(
                            _enum_or_string(candidate_ids)
                        ),
                        "experimental_arm_ids": _array(_enum_or_string(arm_ids)),
                        "control_arm_ids": _array(_enum_or_string(arm_ids)),
                        "field_selections": _array(
                            _object(
                                {
                                    "field": {"type": "string", "enum": FINAL_FIELDS},
                                    "evidence_ids": _array(
                                        _enum_or_string(evidence_ids)
                                    ),
                                }
                            )
                        ),
                        "competing_interpretations": _array({"type": "string"}),
                        "assumptions": _array({"type": "string"}),
                        "scale_direction": {
                            "type": "string",
                            "enum": [
                                "higher_is_better",
                                "higher_is_worse",
                                "unclear",
                                "not_applicable",
                            ],
                        },
                        "scale_direction_basis": {
                            "type": "string",
                            "enum": [
                                "source_reported",
                                "expert_inference",
                                "insufficient_information",
                                "not_applicable",
                            ],
                        },
                        "scale_direction_confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low", "not_applicable"],
                        },
                        "scale_direction_rationale": {"type": "string"},
                        "direct_effect_semantics": _direct_effect_semantics_schema(),
                        "reason": {"type": "string"},
                    }
                )
            )
        }
    )


def _direct_effect_semantics_schema() -> dict[str, Any]:
    """Describe the working orientation used for a direct continuous effect.

    The reported source scope remains attached to each evidence card.  This
    object records the adjudicator's normalized interpretation, which may be
    inferred from multiple grounded sources when the article does not state
    its subtraction order explicitly.
    """

    return _object(
        {
            "comparison_direction": {
                "type": "string",
                "enum": [
                    "experimental_minus_control",
                    "control_minus_experimental",
                    "not_applicable",
                    "unclear",
                ],
            },
            "change_score_direction": {
                "type": "string",
                "enum": CHANGE_SCORE_DIRECTIONS,
            },
            "basis": {
                "type": "string",
                "enum": DIRECTION_BASES,
            },
            "confidence": {
                "type": "string",
                "enum": DIRECTION_CONFIDENCES,
            },
            "rationale": {"type": "string"},
        }
    )


def _evidence_scope_schema(*, source_refs: list[str]) -> dict[str, Any]:
    return _object(
        {
            "outcome_label": {"type": "string"},
            "outcome_measure": _nullable_string(),
            "timepoint": _nullable_string(),
            "arm_label": _nullable_string(),
            "comparison_direction": {
                "type": "string",
                "enum": [
                    "experimental_minus_control",
                    "control_minus_experimental",
                    "not_applicable",
                    "unclear",
                ],
            },
            "analysis_population": _nullable_string(),
            "result_frame": {"type": "string", "enum": RESULT_FRAMES},
            "change_score_direction": {
                "type": "string",
                "enum": CHANGE_SCORE_DIRECTIONS,
            },
            "row_or_item_label": _nullable_string(),
            "column_header_path": _array({"type": "string"}),
            "denominator_scope": {
                "type": "string",
                "enum": DENOMINATOR_SCOPES,
            },
            "footnote_links": _array(
                _object(
                    {
                        "marker": {"type": "string"},
                        "text": {"type": "string"},
                    }
                )
            ),
            "supporting_quotes": _array(
                _object(
                    {
                        "source_ref": _enum_or_string(source_refs),
                        "source_kind": {
                            "type": "string",
                            "enum": ["table", "section"],
                        },
                        "quote": {"type": "string"},
                    }
                )
            ),
            "scope_status": {"type": "string", "enum": SCOPE_STATUSES},
        }
    )


def _candidate_schema(*, source_refs: list[str]) -> dict[str, Any]:
    return _object(
        {
            "source_table_id": _enum_or_string(source_refs),
            "outcome_label": {"type": "string"},
            "outcome_measure": _nullable_string(),
            "unit": _nullable_string(),
            "timepoint": _nullable_string(),
            "population_or_subgroup": _nullable_string(),
            "analysis_population": _nullable_string(),
            "data_type": {
                "type": "string",
                "enum": ["Dichotomous", "Continuous"],
            },
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
            "change_score_direction": {
                "type": "string",
                "enum": CHANGE_SCORE_DIRECTIONS,
            },
            "scale_direction": {
                "type": "string",
                "enum": ["higher_is_better", "higher_is_worse", "unclear"],
            },
            "arms": _array(
                _object(
                    {
                        "label": {"type": "string"},
                        "materials": _array(_material_schema()),
                    }
                )
            ),
            "notes": _array({"type": "string"}),
            "uncertainties": _array({"type": "string"}),
        }
    )


def _support_schema(*, source_refs: list[str]) -> dict[str, Any]:
    return _object(
        {
            "source_ref": _enum_or_string(source_refs),
            "source_kind": {"type": "string", "enum": ["table", "section"]},
            "arm_label": _nullable_string(),
            "outcome_label": _nullable_string(),
            "outcome_measure": _nullable_string(),
            "timepoint": _nullable_string(),
            "population_or_subgroup": _nullable_string(),
            "analysis_population": _nullable_string(),
            "material": _material_schema(),
        }
    )


def _material_schema() -> dict[str, Any]:
    return _object(
        {
            "kind": {"type": "string", "enum": MATERIAL_KINDS},
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
            "interpretation": {"type": "string"},
            "uncertainties": _array({"type": "string"}),
        }
    )


def _study_map_schema(*, source_refs: list[str]) -> dict[str, Any]:
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
            "evidence": _array(
                _object(
                    {
                        "fact": {"type": "string"},
                        "source_refs": _array(_enum_or_string(source_refs)),
                    }
                )
            ),
        }
    )


def _resolution_decision_schema(
    *,
    target_ids: list[str],
    candidate_ids: list[str],
    material_ids: list[str],
    arm_ids: list[str],
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    return _object(
        {
            "target_id": _enum_or_string(target_ids),
            "status": {
                "type": "string",
                "enum": [
                    "ready",
                    "data_unavailable",
                    "unresolved",
                    "unsupported_dependency",
                ],
            },
            "candidate_ids": _array(_enum_or_string(candidate_ids)),
            "experimental_arm_ids": _array(_enum_or_string(arm_ids)),
            "control_arm_ids": _array(_enum_or_string(arm_ids)),
            "field_evidence": _array(
                _object(
                    {
                        "field": {"type": "string", "enum": FINAL_FIELDS},
                        "material_ids": _array(_enum_or_string(material_ids)),
                    }
                )
            ),
            "alternative_material_ids": _array(_enum_or_string(material_ids)),
            # The resolver explicitly asks for semantic source handles needed
            # to verify arm identity or study scope; values are never inferred
            # from an opaque ID by the verifier.
            "context_source_refs": _array(_enum_or_string(source_refs or [])),
            "excluded_candidate_ids": _array(_enum_or_string(candidate_ids)),
            "assumptions": _array({"type": "string"}),
            "reason": {"type": "string"},
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
    return {"type": "string", "enum": values} if values else {"type": "string"}


def _nullable_enum(values: list[str]) -> dict[str, Any]:
    if not values:
        return {"type": ["string", "null"]}
    return {"type": ["string", "null"], "enum": [*values, None]}
