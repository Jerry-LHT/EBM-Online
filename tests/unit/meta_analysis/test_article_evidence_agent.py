from __future__ import annotations

import json
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent.method import (
    Method,
    _assemble_resolution,
    _complex_table,
    _continuous_alignment,
    _normalize_table_result,
    _normalize_resolutions,
    _needs_first_support_table_search,
    _labels_equivalent,
    _material_numbers_match_locator,
    _quote_matches_source,
    _support_material_needs,
)


def _study_map() -> dict[str, Any]:
    return {
        "study_design": "parallel randomized trial",
        "population": "adults with pain",
        "treatment_duration": "7 days",
        "follow_up": ["7 days"],
        "analysis_populations": ["intention-to-treat"],
        "arms": [
            {"label": "low dose", "aliases": [], "role": "experimental", "description": None},
            {"label": "high dose", "aliases": [], "role": "experimental", "description": None},
            {"label": "placebo", "aliases": [], "role": "control", "description": None},
        ],
        "notes": [],
    }


def _targets() -> list[dict[str, Any]]:
    common = {
        "population_scope": "adults with pain",
        "comparison": {"experimental": "active treatment", "comparator": "placebo"},
        "timepoint": {"label": "7 days"},
        "subgroup": {"factor": None, "level": None},
        "data_type": "Dichotomous",
        "result_selection_policy": {},
        "effect_measure_plan": "Risk Ratio",
    }
    return [
        {**common, "target_id": "target-pain", "outcome": {"label": "pain present"}},
        {**common, "target_id": "target-response", "outcome": {"label": "clinical response"}},
    ]


def _block(*, outcome: str, values: tuple[tuple[str, int, int], ...]) -> dict[str, Any]:
    return {
        "outcome_label": outcome,
        "outcome_measure": outcome,
        "unit": None,
        "timepoint": "7 days",
        "statistic_type": "events and analyzed total",
        "population_or_subgroup": "adults with pain",
        "analysis_population": "intention-to-treat",
        "continuous_result_frame": None,
        "change_score_definition": None,
        "scale_direction": None,
        "data_type": "Dichotomous",
        "arms": [
            {
                "label": label,
                "events": events,
                "total": total,
                "mean": None,
                "sd": None,
                "source_quote": f"{label} {events}/{total}",
            }
            for label, events, total in values
        ],
        "table_local_notes": [],
        "uncertainties": [],
    }


class _Caller:
    def __init__(self) -> None:
        self.controller_calls = 0
        self.table_payloads: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        name = kwargs["json_schema_name"]
        payload = json.loads(kwargs["prompt"])
        if name == "meta_study_evidence_controller":
            self.controller_calls += 1
            return {
                "action": "extract_tables" if self.controller_calls == 1 else "ready",
                "section_ids": [],
                "table_ids": ["table-1"] if self.controller_calls == 1 else [],
                "study_map": _study_map(),
                "reason": "The only results table has been extracted." if self.controller_calls > 1 else None,
            }
        if name == "meta_table_result_blocks":
            self.table_payloads.append(payload)
            return {
                "source_status": "results_found",
                "result_blocks": [
                    _block(
                        outcome="pain present",
                        values=(("low dose", 3, 20), ("high dose", 4, 20), ("placebo", 8, 40)),
                    ),
                    _block(
                        outcome="clinical response",
                        values=(("low dose", 12, 20), ("high dose", 13, 20), ("placebo", 18, 40)),
                    ),
                ],
                "source_summary": "Two outcome blocks at seven days.",
            }
        if name == "meta_article_resolution":
            resolutions = []
            for target in payload["targets"]:
                expected = target["outcome"]["label"]
                candidate = next(
                    row for row in payload["candidates"]
                    if row["local_setting"]["outcome_label"] == expected
                )
                resolutions.append(
                    {
                        "target_id": target["target_id"],
                        "status": "resolved",
                        "operation": "combine_experimental_arms",
                        "candidate_ids": [candidate["candidate_id"]],
                        "experimental_arm_labels": ["low dose", "high dose"],
                        "control_arm_labels": ["placebo"],
                        "field_bindings": [],
                        "excluded_candidate_ids": [],
                        "unresolved_candidate_ids": [],
                        "reason": "Both active randomized arms match the planned intervention.",
                    }
                )
            return {"resolutions": resolutions}
        if name == "meta_selected_result_verification":
            return {"valid": True, "issues": [], "corrected_resolution": None}
        raise AssertionError(f"Unexpected schema: {name}")


def test_article_agent_reads_one_raw_table_once_for_all_targets_and_combines_arms() -> None:
    caller = _Caller()
    raw_xml = (
        "<table><tr><td>low dose 3/20</td><td>high dose 4/20</td>"
        "<td>placebo 8/40</td></tr><tr><td>low dose 12/20</td>"
        "<td>high dose 13/20</td><td>placebo 18/40</td></tr></table>"
    )
    result = Method(config={"model": "fake"}, llm_caller=caller).run(
        review_id="review-1",
        targets=_targets(),
        study_id="study-1",
        article={
            "study_id": "study-1",
            "metadata": {"publication_year": "2024"},
            "xml_content": {
                "sections": [
                    {"section_id": "methods", "title": "Methods", "text": "Hidden section text"}
                ]
            },
            "tables": [{"table_id": "table-1", "caption": "Outcomes", "raw_xml": raw_xml}],
        },
        plan_hash="plan-hash",
    )

    assert len(caller.table_payloads) == 1
    assert caller.table_payloads[0]["raw_xml"] == raw_xml
    assert "sections" not in caller.table_payloads[0]
    assert "Hidden section text" not in json.dumps(caller.table_payloads[0])
    assert len(caller.table_payloads[0]["review_targets"]) == 2
    assert [row["setting_id"] for row in result["study_result_rows"]] == [
        "target-pain",
        "target-response",
    ]
    assert result["data_rows"][0]["result_data"] == {
        "experimental_events": 7,
        "experimental_total": 40,
        "control_events": 8,
        "control_total": 40,
    }
    assert result["data_rows"][1]["result_data"]["experimental_events"] == 25
    assert result["coverage"]["status"] == "complete"


def _candidate(
    *,
    candidate_id: str,
    table_id: str,
    timepoint: str = "7 days",
    events: int | None,
    total: int | None,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "source_table_id": table_id,
        "source_hash": table_id,
        "data_type": "Dichotomous",
        "local_setting": {
            "outcome_label": "pain present",
            "outcome_measure": "pain present",
            "unit": None,
            "timepoint": timepoint,
            "statistic_type": "events and analyzed total",
            "population_or_subgroup": "adults with pain",
            "analysis_population": "intention-to-treat",
            "continuous_result_frame": None,
            "change_score_definition": None,
            "scale_direction": "unclear",
        },
        "arms": [
            {"label": "treatment", "events": events, "total": total},
            {"label": "placebo", "events": events, "total": total},
        ],
        "uncertainties": [],
        "source_spans": [],
    }


def test_cross_table_assembly_requires_compatible_identity_and_explicit_field_provenance() -> None:
    events = _candidate(candidate_id="events", table_id="table-events", events=5, total=None)
    totals = _candidate(candidate_id="totals", table_id="table-totals", events=None, total=20)
    resolution = {
        "status": "resolved",
        "operation": "cross_table_assembly",
        "candidate_ids": ["events", "totals"],
        "experimental_arm_labels": ["treatment"],
        "control_arm_labels": ["placebo"],
        "field_bindings": [
            {"field": "experimental_events", "candidate_id": "events", "arm_label": "treatment"},
            {"field": "experimental_total", "candidate_id": "totals", "arm_label": "treatment"},
            {"field": "control_events", "candidate_id": "events", "arm_label": "placebo"},
            {"field": "control_total", "candidate_id": "totals", "arm_label": "placebo"},
        ],
    }
    target = _targets()[0]

    row, error = _assemble_resolution(
        study_id="study-1",
        target=target,
        study_map=_study_map(),
        resolution=resolution,
        candidate_by_id={"events": events, "totals": totals},
        support_materials=[],
        study_year="2024",
    )

    assert error is None
    assert row is not None
    assert row["result_data"]["experimental_events"] == 5
    assert row["result_data"]["experimental_total"] == 20
    provenance = row["result_items"][0]["numeric_extraction"]["field_provenance"]
    assert provenance["experimental_events::treatment"]["table_id"] == "table-events"
    assert provenance["experimental_total::treatment"]["table_id"] == "table-totals"

    conflicting = _candidate(
        candidate_id="totals",
        table_id="table-totals",
        timepoint="14 days",
        events=None,
        total=20,
    )
    rejected, rejected_error = _assemble_resolution(
        study_id="study-1",
        target=target,
        study_map=_study_map(),
        resolution=resolution,
        candidate_by_id={"events": events, "totals": conflicting},
        support_materials=[],
        study_year="2024",
    )

    assert rejected is None
    assert rejected_error == "Cross-table assembly has conflicting timepoint values."


def test_complex_table_detection_ignores_normal_jats_wrapper_and_unit_spans() -> None:
    ordinary = (
        '<table-wrap><table><thead><tr><th rowspan="1" colspan="1">Outcome</th>'
        '<th>Arm A</th></tr></thead><tbody><tr><td>Response</td><td>5/20</td>'
        '</tr></tbody></table></table-wrap>'
    )
    complex_header = ordinary.replace('rowspan="1"', 'rowspan="2"')

    assert _complex_table(ordinary) is False
    assert _complex_table(complex_header) is True


def test_arm_aliases_do_not_duplicate_one_physical_source_arm() -> None:
    candidate = _candidate(
        candidate_id="candidate-1",
        table_id="table-1",
        events=2,
        total=30,
    )
    candidate["arms"] = [
        {"label": "Group L", "events": 2, "total": 30},
        {"label": "Group C", "events": 11, "total": 30},
    ]
    study_map = _study_map()
    study_map["arms"] = [
        {
            "label": "Group L",
            "aliases": ["Levosimendan"],
            "role": "experimental",
            "description": None,
        },
        {
            "label": "Group C",
            "aliases": ["Control"],
            "role": "control",
            "description": None,
        },
    ]
    resolution = {
        "status": "resolved",
        "operation": "select_direct",
        "candidate_ids": ["candidate-1"],
        "experimental_arm_labels": ["Group L", "Levosimendan"],
        "control_arm_labels": ["Group C", "Control"],
        "field_bindings": [],
    }

    row, error = _assemble_resolution(
        study_id="study-1",
        target=_targets()[0],
        study_map=study_map,
        resolution=resolution,
        candidate_by_id={"candidate-1": candidate},
        support_materials=[],
        study_year="2024",
    )

    assert error is None
    assert row is not None
    assert row["comparison"] == {
        "experimental_arm": "Group L",
        "control_arm": "Group C",
    }
    assert row["result_data"] == {
        "experimental_events": 2,
        "experimental_total": 30,
        "control_events": 11,
        "control_total": 30,
    }


def test_continuous_endpoint_uses_frozen_result_frame_vocabulary() -> None:
    alignment = _continuous_alignment(
        {
            "continuous_result_frame": "post-intervention",
            "change_score_definition": None,
            "scale_direction": "higher_is_better",
        }
    )

    assert alignment["result_frame"] == "post_intervention"
    assert alignment["change_score_definition"] == "not_applicable"
    assert alignment["effect_multiplier"] == 1
    assert alignment["status"] == "ready"


def _support_material(
    *,
    material_id: str,
    arm_label: str,
    kind: str,
    value: int,
) -> dict[str, Any]:
    return {
        "material_id": material_id,
        "kind": kind,
        "value": value,
        "lower": None,
        "upper": None,
        "confidence_level": None,
        "decimal_places": None,
        "statistical_scope": "arm",
        "applies_to": "participant_flow",
        "arm_label": arm_label,
        "local_setting": {
            "outcome_label": "pain present",
            "outcome_measure": "pain present",
            "timepoint": "7 days",
            "population_or_subgroup": "adults with pain",
            "analysis_population": "intention-to-treat",
        },
        "source_table_id": "table-flow",
        "source_hash": "flow-hash",
        "source_quote": f"{arm_label} {value}",
        "notes": None,
        "uncertainties": [],
    }


def test_cross_table_support_uses_outcome_complete_count_as_analyzed_n() -> None:
    candidate = _candidate(
        candidate_id="events",
        table_id="table-events",
        events=5,
        total=None,
    )
    supports = [
        _support_material(
            material_id="n-treatment",
            arm_label="treatment",
            kind="outcome_complete_count",
            value=20,
        ),
        _support_material(
            material_id="n-placebo",
            arm_label="placebo",
            kind="outcome_complete_count",
            value=20,
        ),
    ]
    resolution = {
        "status": "resolved",
        "operation": "cross_table_assembly",
        "candidate_ids": ["events"],
        "support_material_ids": ["n-treatment", "n-placebo"],
        "experimental_arm_labels": ["treatment"],
        "control_arm_labels": ["placebo"],
        "field_bindings": [],
    }

    row, error = _assemble_resolution(
        study_id="study-1",
        target=_targets()[0],
        study_map=_study_map(),
        resolution=resolution,
        candidate_by_id={"events": candidate},
        support_materials=supports,
        study_year="2024",
    )

    assert error is None
    assert row is not None
    assert row["result_data"]["experimental_total"] == 20
    provenance = row["result_items"][0]["numeric_extraction"]["field_provenance"]
    assert provenance["experimental_total::treatment"]["method"] == "calculated"
    assert provenance["experimental_total::treatment"]["material_ids"] == ["n-treatment"]


def test_single_result_candidate_support_does_not_require_analysis_population() -> None:
    """A denominator support block may be needed even when the article names no population."""

    candidate = _candidate(
        candidate_id="events",
        table_id="table-events",
        events=5,
        total=None,
    )
    candidate["local_setting"]["analysis_population"] = None
    supports = [
        _support_material(
            material_id="n-treatment",
            arm_label="treatment",
            kind="outcome_complete_count",
            value=20,
        ),
        _support_material(
            material_id="n-placebo",
            arm_label="placebo",
            kind="outcome_complete_count",
            value=20,
        ),
    ]
    resolution = {
        "status": "resolved",
        "operation": "cross_table_assembly",
        "candidate_ids": ["events"],
        "support_material_ids": ["n-treatment", "n-placebo"],
        "experimental_arm_labels": ["treatment"],
        "control_arm_labels": ["placebo"],
        "field_bindings": [],
    }

    row, error = _assemble_resolution(
        study_id="study-1",
        target=_targets()[0],
        study_map=_study_map(),
        resolution=resolution,
        candidate_by_id={"events": candidate},
        support_materials=supports,
        study_year="2024",
    )

    assert error is None
    assert row is not None
    assert row["result_data"] == {
        "experimental_events": 5,
        "experimental_total": 20,
        "control_events": 5,
        "control_total": 20,
    }


def test_enrollment_n_is_not_analyzed_n_without_zero_attrition_evidence() -> None:
    candidate = _candidate(
        candidate_id="events",
        table_id="table-events",
        events=5,
        total=None,
    )
    randomized = [
        _support_material(
            material_id="randomized-treatment",
            arm_label="treatment",
            kind="randomized_total",
            value=20,
        ),
        _support_material(
            material_id="randomized-placebo",
            arm_label="placebo",
            kind="randomized_total",
            value=20,
        ),
    ]
    resolution = {
        "status": "resolved",
        "operation": "cross_table_assembly",
        "candidate_ids": ["events"],
        "support_material_ids": [row["material_id"] for row in randomized],
        "experimental_arm_labels": ["treatment"],
        "control_arm_labels": ["placebo"],
        "field_bindings": [],
    }

    row, error = _assemble_resolution(
        study_id="study-1",
        target=_targets()[0],
        study_map=_study_map(),
        resolution=resolution,
        candidate_by_id={"events": candidate},
        support_materials=randomized,
        study_year="2024",
    )

    assert row is None
    assert error is not None
    assert "experimental_total" in error


def test_consistent_event_percentage_and_n_confirms_result_denominator() -> None:
    output = {
        "source_status": "results_found",
        "result_blocks": [
            {
                "outcome_label": "pain present",
                "outcome_measure": "participants with pain",
                "timepoint": "7 days",
                "statistic_type": "events/N (%)",
                "data_type": "Dichotomous",
                "arms": [
                    {
                        "label": "treatment",
                        "events": 5,
                        "total": 30,
                        "total_kind": "unclear",
                        "percentage": 16.67,
                        "percentage_decimal_places": 2,
                        "source_quote": "5/30 (16.67)",
                    }
                ],
                "block_materials": [],
                "uncertainties": [],
            }
        ],
        "support_materials": [],
    }

    normalized = _normalize_table_result(
        output,
        table={
            "table_id": "table-result",
            "source_hash": "hash",
            "raw_xml": "<table><td>5/30 (16.67)</td></table>",
        },
        targets=_targets(),
    )

    arm = normalized["candidates"][0]["arms"][0]
    assert arm["total"] == 30
    assert {row["kind"] for row in arm["materials"]} == {
        "event_count",
        "result_denominator",
        "percentage",
    }


def test_statistic_profile_keeps_p_value_ancillary_when_arm_events_are_complete() -> None:
    normalized = _normalize_table_result(
        {
            "source_status": "results_found",
            "result_blocks": [
                {
                    "outcome_label": "postoperative atrial fibrillation",
                    "outcome_measure": "participants with postoperative atrial fibrillation",
                    "timepoint": "postoperative period",
                    "statistic_type": "P value",
                    "data_type": "Dichotomous",
                    "arms": [
                        {
                            "label": "Group C",
                            "events": 11,
                            "total": 30,
                            "total_kind": "result_denominator",
                            "percentage": 36.67,
                            "percentage_decimal_places": 2,
                            "source_quote": "Group C 11/30 (36.67)",
                        },
                        {
                            "label": "Group L",
                            "events": 2,
                            "total": 30,
                            "total_kind": "result_denominator",
                            "percentage": 6.67,
                            "percentage_decimal_places": 2,
                            "source_quote": "Group L 2/30 (6.67)",
                        },
                    ],
                    "block_materials": [],
                    "uncertainties": [],
                }
            ],
            "support_materials": [],
        },
        table={
            "table_id": "table-af",
            "source_hash": "hash-af",
            "raw_xml": (
                "<table>Postoperative atrial fibrillation (%) "
                "Group C 11/30 (36.67) Group L 2/30 (6.67) P value</table>"
            ),
        },
        targets=_targets(),
    )

    local_setting = normalized["candidates"][0]["local_setting"]
    assert local_setting["reported_statistic_type"] == "P value"
    assert local_setting["statistic_type"] == "events/N (%)"
    assert local_setting["analysis_input_representation"] == (
        "dichotomous_arm_events_total"
    )
    assert local_setting["statistic_type_status"] == "conflict"
    assert "reported_statistic_type_conflicts_with_typed_materials" in normalized[
        "candidates"
    ][0]["uncertainties"]


def test_statistic_profile_distinguishes_continuous_se_from_final_sd() -> None:
    normalized = _normalize_table_result(
        {
            "source_status": "results_found",
            "result_blocks": [
                {
                    "outcome_label": "pain score",
                    "outcome_measure": "pain score",
                    "timepoint": "week 8",
                    "statistic_type": "mean (SE)",
                    "continuous_result_frame": "post_intervention",
                    "data_type": "Continuous",
                    "arms": [
                        {
                            "label": "Arm A",
                            "mean": 12.0,
                            "total": 25,
                            "total_kind": "result_denominator",
                            "se": 0.8,
                            "uncertainty_scope": "arm_mean",
                            "source_quote": "Arm A (n=25) 12.0 (0.8)",
                        },
                        {
                            "label": "Arm B",
                            "mean": 15.0,
                            "total": 25,
                            "total_kind": "result_denominator",
                            "se": 1.0,
                            "uncertainty_scope": "arm_mean",
                            "source_quote": "Arm B (n=25) 15.0 (1.0)",
                        },
                    ],
                    "block_materials": [],
                    "uncertainties": [],
                }
            ],
            "support_materials": [],
        },
        table={
            "table_id": "table-pain",
            "source_hash": "hash-pain",
            "raw_xml": "<table>Arm A (n=25) 12.0 (0.8) Arm B (n=25) 15.0 (1.0)</table>",
        },
        targets=_targets(),
    )

    local_setting = normalized["candidates"][0]["local_setting"]
    assert local_setting["reported_statistic_type"] == "mean (SE)"
    assert local_setting["statistic_type"] == "mean/SD/N"
    assert local_setting["analysis_input_representation"] == (
        "continuous_arm_mean_sd_total"
    )
    assert local_setting["statistic_type_status"] == "consistent"
    arm = normalized["candidates"][0]["arms"][0]
    assert arm["sd"] == 4.0


def test_source_locator_can_bind_separate_header_and_cell_fragments() -> None:
    raw_text = "Variable CG mean SD 12th week n 20 Quality of life 51.6 1.2"

    assert _quote_matches_source(
        "CG, mean SD, 12th week (n=20) ... 51.6 1.2",
        raw_text,
    )
    assert not _quote_matches_source(
        "CG, mean SD, 12th week (n=20) ... 99.9 1.2",
        raw_text,
    )


def test_relevant_incomplete_candidate_cannot_be_normalized_as_data_unavailable() -> None:
    rows = _normalize_resolutions(
        {
            "resolutions": [
                {
                    "target_id": "target-pain",
                    "status": "data_unavailable",
                    "operation": "exclude",
                    "candidate_ids": [],
                    "support_material_ids": [],
                    "experimental_arm_labels": [],
                    "control_arm_labels": [],
                    "field_bindings": [],
                    "excluded_candidate_ids": [],
                    "unresolved_candidate_ids": ["candidate-incomplete"],
                    "reason": "The result is relevant but lacks an outcome denominator.",
                }
            ]
        },
        target_ids=["target-pain"],
        candidate_ids={"candidate-incomplete"},
        support_material_ids=set(),
        source_coverage_complete=True,
    )

    assert rows[0]["status"] == "unresolved"
    assert rows[0]["unresolved_candidate_ids"] == ["candidate-incomplete"]


def test_incomplete_candidate_requires_at_least_one_support_table_search() -> None:
    candidate = _candidate(
        candidate_id="candidate-incomplete",
        table_id="table-result",
        events=5,
        total=None,
    )
    state = {
        "table_results": {
            "table-result": {
                "candidates": [candidate],
                "support_materials": [],
            }
        }
    }

    assert _needs_first_support_table_search(state) is True
    state["table_results"]["table-baseline"] = {
        "candidates": [],
        "support_materials": [{"kind": "baseline_total"}],
    }
    assert _needs_first_support_table_search(state) is False


def test_direct_material_value_must_appear_in_its_source_locator() -> None:
    assert _material_numbers_match_locator(
        {"value": 14, "lower": None, "upper": None, "source_quote": "14/30 (47)"}
    )
    assert not _material_numbers_match_locator(
        {"value": 16, "lower": None, "upper": None, "source_quote": "14/30 (47)"}
    )
    assert _material_numbers_match_locator(
        {"value": None, "lower": 8.5, "upper": 11.5, "source_quote": "95% CI 8.5 to 11.5"}
    )
    assert _material_numbers_match_locator(
        {"value": None, "lower": 8.5, "upper": 11.5, "source_quote": "95% CI 8.5-11.5"}
    )
    assert _material_numbers_match_locator(
        {"value": -2.5, "lower": None, "upper": None, "source_quote": "mean -2.5"}
    )


def test_support_recovery_need_is_typed_from_missing_final_primitive() -> None:
    candidate = _candidate(
        candidate_id="candidate-incomplete",
        table_id="table-result",
        events=5,
        total=None,
    )

    needs = _support_material_needs([candidate])

    assert len(needs) == 2
    assert {row["arm_label"] for row in needs} == {"treatment", "placebo"}
    assert all(row["missing_fields"] == ["total"] for row in needs)
    assert all(
        "outcome_complete_count" in row["acceptable_material_kinds"]
        and "baseline_total" in row["acceptable_material_kinds"]
        for row in needs
    )


def test_arm_identity_uses_exact_parenthetical_alias_variants() -> None:
    study_map = _study_map()
    study_map["arms"] = [
        {
            "label": "levosimendan group",
            "aliases": ["Group I"],
            "role": "experimental",
            "description": None,
        },
        {
            "label": "control group",
            "aliases": ["Group II"],
            "role": "control",
            "description": None,
        },
    ]

    assert _labels_equivalent("Group I", "Group I (levosimendan)", study_map)
    assert _labels_equivalent("control (Group II)", "Group II", study_map)
    assert not _labels_equivalent("Group I", "Group II (control)", study_map)


def test_numeric_locator_recognizes_unicode_minus_signs() -> None:
    assert _material_numbers_match_locator(
        {
            "value": -0.77,
            "lower": -1.20,
            "upper": -0.34,
            "source_quote": "\u22120.77 (\u2212 1.20 to \u2212 0.34)",
        }
    )
