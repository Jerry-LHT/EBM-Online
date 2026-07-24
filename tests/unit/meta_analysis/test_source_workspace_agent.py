from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.errors import (
    MetaAnalysisInvocationError,
    MetaAnalysisOutputError,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMAPIError
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.factory import (
    build_production_study_evidence_agent,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.source_workspace_agent.evidence_state import (
    _bind_candidate_arm_ids,
    _merge_reconciled_study_map,
    _quote_matches_visible_source,
    apply_arm_reconciliation,
    article_arm_id_for_label,
    arm_observations,
    decision_optional_source_refs,
    decision_required_source_refs,
    empty_notebook,
    merge_study_map,
    _normalize_direct_effect_semantics,
    normalize_arm_reconciliation_response,
    result_blind_notebook,
    normalize_resolution_response,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.source_workspace_agent.deterministic_bridge import (
    _assemble_direct_effect,
    _direct_standard_error,
    _resolution_reason_code,
    _unique_arm,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.source_workspace_agent.context import (
    compile_census_context,
    request_input_summary,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent.method import (
    _compatible_support_materials,
    _resolved_arms,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.source_workspace_agent.method import (
    DEFAULT_LLM_TIMEOUT_SECONDS,
    MAX_CANDIDATES_PER_ARTICLE,
    Method,
    _bounded_table_windows,
    _coverage,
    _output_failure_code,
    _validate_state_size,
    _scope_audit_reasons,
    _source_local_candidate_ids,
    _supported_result_representations,
    _payloads_mark_actual_context_limited,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.source_workspace_agent.schemas import (
    source_verification_schema,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.source_workspace_agent.source_workspace import (
    SourceWindow,
    SourceWorkspace,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.source_workspace_agent.working_state import (
    active_evidence_needs,
    apply_evidence_need_updates,
    normalize_evidence_need_updates,
    register_evidence_needs,
)


def _target(*, data_type: str = "Dichotomous") -> dict[str, Any]:
    return {
        "target_id": "target-1",
        "setting_family_id": "family-1",
        "population_scope": "adults with pain",
        "comparison": {
            "experimental": "active treatment",
            "comparator": "placebo",
        },
        "outcome": {
            "label": "pain response" if data_type == "Dichotomous" else "pain score",
            "measure": "pain response" if data_type == "Dichotomous" else "pain scale",
        },
        "timepoint": {"label": "12 weeks"},
        "subgroup": {"factor": None, "level": None},
        "data_type": data_type,
        "result_selection_policy": {},
        "effect_measure_plan": (
            "Risk Ratio" if data_type == "Dichotomous" else "Mean Difference"
        ),
        "analysis_model_plan": "common_effect",
        "notes": "Use the randomized active-treatment versus placebo comparison.",
    }


def _empty_map() -> dict[str, Any]:
    return {
        "study_design": None,
        "population": None,
        "treatment_duration": None,
        "follow_up": [],
        "analysis_populations": [],
        "arms": [],
        "notes": [],
        "evidence": [],
    }


def _material(
    key: str,
    kind: str,
    value: float,
    quote: str,
    *,
    applies_to: str,
) -> dict[str, Any]:
    return {
        "evidence_key": key,
        "kind": kind,
        "value": value,
        "lower": None,
        "upper": None,
        "confidence_level": None,
        "decimal_places": 0,
        "statistical_scope": "arm",
        "applies_to": applies_to,
        "source_quote": quote,
        "interpretation": "Directly reported for this arm and outcome.",
        "uncertainties": [],
    }


def _investigator_finish(
    *,
    support_materials: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "action": "finish",
        "queries": [],
        "source_refs": [],
        "candidate_blocks": [],
        "support_materials": support_materials or [],
        "study_map_update": {
            "study_design": "parallel randomized trial",
            "population": "adults with pain",
            "treatment_duration": "12 weeks",
            "follow_up": ["12 weeks"],
            "analysis_populations": ["intention-to-treat"],
            "arms": [
                {
                    "label": "treatment",
                    "aliases": ["active treatment"],
                    "role": "experimental",
                    "description": "active treatment",
                },
                {
                    "label": "placebo",
                    "aliases": [],
                    "role": "control",
                    "description": "placebo",
                },
            ],
            "notes": [],
            "evidence": [],
        },
        "claims": [],
        "alternatives": [],
        "open_questions": [],
        "reason": "The supplied table and prose establish the requested result.",
    }


class _BinaryCaller:
    def __init__(self, *, invalid_first_census: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.invalid_first_census = invalid_first_census
        self.census_attempts = 0

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        name = str(kwargs["json_schema_name"])
        payload = json.loads(kwargs["prompt"])
        self.calls.append((name, payload))
        if name == "meta_source_workspace_table_census":
            self.census_attempts += 1
            if self.invalid_first_census and self.census_attempts == 1:
                return {"source_observations": []}
            observations = []
            for source in payload["sources"]:
                source_ref = source["source_ref"]
                if source_ref == "table-result":
                    observations.append(
                        {
                            "source_ref": source_ref,
                            "source_status": "target_relevant",
                            "summary": "Pain-response events and denominators by arm.",
                            "candidate_blocks": [
                                {
                                    "source_table_id": source_ref,
                                    "outcome_label": "pain response",
                                    "outcome_measure": "pain response",
                                    "unit": None,
                                    "timepoint": "12 weeks",
                                    "population_or_subgroup": "adults with pain",
                                    "analysis_population": "intention-to-treat",
                                    "data_type": "Dichotomous",
                                    "continuous_result_frame": None,
                                    "change_score_definition": None,
                                    "scale_direction": "higher_is_better",
                                    "arms": [
                                        {
                                            "label": "treatment",
                                            "materials": [
                                                _material(
                                                    "te",
                                                    "event_count",
                                                    5,
                                                    "treatment 5/20",
                                                    applies_to="event_risk",
                                                ),
                                                _material(
                                                    "tn",
                                                    "result_denominator",
                                                    20,
                                                    "treatment 5/20",
                                                    applies_to="event_risk",
                                                ),
                                            ],
                                        },
                                        {
                                            "label": "placebo",
                                            "materials": [
                                                _material(
                                                    "ce",
                                                    "event_count",
                                                    8,
                                                    "placebo 8/20",
                                                    applies_to="event_risk",
                                                ),
                                                _material(
                                                    "cn",
                                                    "result_denominator",
                                                    20,
                                                    "placebo 8/20",
                                                    applies_to="event_risk",
                                                ),
                                            ],
                                        },
                                    ],
                                    "notes": [],
                                    "uncertainties": [],
                                }
                            ],
                            "support_materials": [],
                            "study_map_update": _empty_map(),
                            "evidence_needs": ["confirm randomized arm identity"],
                        }
                    )
                else:
                    observations.append(
                        {
                            "source_ref": source_ref,
                            "source_status": "no_target_evidence",
                            "summary": "No result relevant to the frozen target.",
                            "candidate_blocks": [],
                            "support_materials": [],
                            "study_map_update": _empty_map(),
                            "evidence_needs": [],
                        }
                    )
            return {"source_observations": observations}
        if name == "meta_source_workspace_investigation":
            return _investigator_finish()
        if name == "meta_source_workspace_arm_reconciliation":
            return _reconcile_arm_observations(payload)
        if name == "meta_source_workspace_resolution":
            blind_candidates = payload["evidence_notebook"]["candidates"]
            blind_materials = [
                material
                for candidate in blind_candidates
                for arm in candidate["arms"]
                for material in arm["materials"]
            ]
            assert all(
                not ({"value", "lower", "upper", "source_quote"} & set(material))
                for material in blind_materials
            )
            candidate = payload["evidence_notebook"]["candidates"][0]
            evidence = {
                (arm["label"], material["kind"]): material["material_id"]
                for arm in candidate["arms"]
                for material in arm["materials"]
            }
            return {
                "decisions": [
                    {
                        "target_id": "target-1",
                        "status": "ready",
                        "candidate_ids": [candidate["candidate_id"]],
                        "experimental_arm_labels": ["treatment"],
                        "control_arm_labels": ["placebo"],
                        "field_evidence": [
                            {
                                "field": "experimental_events",
                                "material_ids": [evidence[("treatment", "event_count")]],
                            },
                            {
                                "field": "experimental_total",
                                "material_ids": [
                                    evidence[("treatment", "result_denominator")]
                                ],
                            },
                            {
                                "field": "control_events",
                                "material_ids": [evidence[("placebo", "event_count")]],
                            },
                            {
                                "field": "control_total",
                                "material_ids": [
                                    evidence[("placebo", "result_denominator")]
                                ],
                            },
                        ],
                        "alternative_material_ids": [],
                        "excluded_candidate_ids": [],
                        "assumptions": [],
                        "reason": "One result matches the frozen target without using magnitude.",
                    }
                ]
            }
        if name == "meta_source_workspace_source_verification":
            source_ref = payload["source_boundary"]["source_ref"]
            candidate_ids = [
                row["candidate_id"] for row in payload.get("candidate_context") or []
            ]
            if source_ref != "table-result":
                return _empty_source_review(payload, source_ref=source_ref)
            candidate_id = candidate_ids[0]
            return {
                "source_reviews": [
                    {
                        "target_id": "target-1",
                        "source_status": "evidence_found",
                        "selected_candidate_ids": [candidate_id],
                        "field_evidence": [
                            _verified_field(
                                "experimental_events",
                                candidate_id,
                                "treatment",
                                "event_count",
                                5,
                                "treatment 5/20",
                            ),
                            _verified_field(
                                "experimental_total",
                                candidate_id,
                                "treatment",
                                "result_denominator",
                                20,
                                "treatment 5/20",
                            ),
                            _verified_field(
                                "control_events",
                                candidate_id,
                                "placebo",
                                "event_count",
                                8,
                                "placebo 8/20",
                            ),
                            _verified_field(
                                "control_total",
                                candidate_id,
                                "placebo",
                                "result_denominator",
                                20,
                                "placebo 8/20",
                            ),
                        ],
                        "competing_interpretations": [],
                        "reason": "This table locally verifies all four binary fields.",
                    }
                ]
            }
        if name == "meta_source_workspace_cross_source_adjudication":
            return _adjudicate_all_verified_evidence(payload)
        if name == "meta_source_workspace_verification":
            candidate_id = payload["proposals"][0]["selected_candidates"][0][
                "candidate_id"
            ]
            return {
                "verdicts": [
                    {
                        "target_id": "target-1",
                        "status": "confirmed",
                        "selected_candidate_ids": [candidate_id],
                        "experimental_arm_labels": ["treatment"],
                        "control_arm_labels": ["placebo"],
                        "field_evidence": [
                            _verified_field(
                                "experimental_events",
                                candidate_id,
                                "treatment",
                                "event_count",
                                5,
                                "treatment 5/20",
                            ),
                            _verified_field(
                                "experimental_total",
                                candidate_id,
                                "treatment",
                                "result_denominator",
                                20,
                                "treatment 5/20",
                            ),
                            _verified_field(
                                "control_events",
                                candidate_id,
                                "placebo",
                                "event_count",
                                8,
                                "placebo 8/20",
                            ),
                            _verified_field(
                                "control_total",
                                candidate_id,
                                "placebo",
                                "result_denominator",
                                20,
                                "placebo 8/20",
                            ),
                        ],
                        "competing_interpretations": [],
                        "assumptions": [],
                        "reason": "The raw table reconstructs all four fields.",
                    }
                ]
            }
        raise AssertionError(f"Unexpected schema: {name}")


class _ReadThenFinishCaller(_BinaryCaller):
    def __init__(self) -> None:
        super().__init__()
        self.investigation_calls = 0

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        name = str(kwargs["json_schema_name"])
        if name != "meta_source_workspace_investigation":
            return super().__call__(**kwargs)
        payload = json.loads(kwargs["prompt"])
        self.calls.append((name, payload))
        self.investigation_calls += 1
        response = _investigator_finish()
        if self.investigation_calls == 1:
            response.update(
                {
                    "action": "read_sources",
                    "source_refs": ["study-1::section::0000"],
                    "reason": "Read the known methods source before finalizing.",
                }
            )
            return response
        assert {
            row["source_ref"] for row in payload["latest_raw_sources"]
        } == {"study-1::section::0000"}
        assert kwargs["json_schema"]["properties"]["action"]["enum"] == ["finish"]
        return response


class _TimeoutCaptureCaller(_BinaryCaller):
    def __init__(self) -> None:
        super().__init__()
        self.timeout_seconds: list[float | None] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.timeout_seconds.append(kwargs.get("timeout_seconds"))
        return super().__call__(**kwargs)


class _FailSecondTableCaller(_BinaryCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_table_census":
            payload = json.loads(kwargs["prompt"])
            if payload["sources"][0]["source_ref"] == "table-other":
                raise LLMAPIError(
                    "provider timeout",
                    status_code=504,
                    request_id="request-table-other",
                    retry_after_seconds=None,
                    retryable=True,
                    provider_message="table-other timed out",
                    failure_code="provider_timeout",
                )
        return super().__call__(**kwargs)


class _CrossTableStudyMapCaller(_BinaryCaller):
    """Uses Table 1 only as a study-map source for a Table 2 candidate."""

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        response = super().__call__(**kwargs)
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_table_census":
            observation = response["source_observations"][0]
            if observation["source_ref"] == "table-other":
                observation["study_map_update"]["arms"] = [
                    {
                        "label": "active treatment",
                        "aliases": ["treatment"],
                        "role": "experimental",
                        "description": "active treatment regimen",
                    },
                    {
                        "label": "placebo",
                        "aliases": ["control"],
                        "role": "control",
                        "description": "matching placebo",
                    },
                ]
                observation["study_map_update"]["evidence"] = [
                    {
                        "fact": "This table defines the randomized arm regimens.",
                        "source_refs": ["table-other"],
                    }
                ]
        return response


class _MarkerlessFootnoteCaller(_BinaryCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_scope_audit":
            payload = json.loads(kwargs["prompt"])
            self.calls.append((str(kwargs["json_schema_name"]), payload))
            return _repeat_scope_audit(payload)
        response = super().__call__(**kwargs)
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_source_verification":
            response["source_reviews"][0]["field_evidence"][0]["evidence_scope"][
                "footnote_links"
            ] = [{"marker": "", "text": "Data are presented as counts."}]
        return response


class _NoCompatibleTableCandidateCaller(_BinaryCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        response = super().__call__(**kwargs)
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_resolution":
            response["decisions"][0].update(
                {
                    "status": "data_unavailable",
                    "candidate_ids": [],
                    "experimental_arm_labels": [],
                    "control_arm_labels": [],
                    "field_evidence": [],
                    "reason": (
                        "The article reports a result outside the supported raw-table "
                        "candidate boundary."
                    ),
                }
            )
        return response


class _MultiArmCaller(_BinaryCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        name = str(kwargs["json_schema_name"])
        payload = json.loads(kwargs["prompt"])
        response = super().__call__(**kwargs)
        if name == "meta_source_workspace_table_census":
            if response["source_observations"][0]["source_ref"] != "table-result":
                return response
            candidate = next(
                observation["candidate_blocks"][0]
                for observation in response["source_observations"]
                if observation["source_ref"] == "table-result"
            )
            candidate["arms"].insert(
                1,
                {
                    "label": "treatment-high",
                    "materials": [
                        _material(
                            "he",
                            "event_count",
                            7,
                            "treatment-high 7/20",
                            applies_to="event_risk",
                        ),
                        _material(
                            "hn",
                            "result_denominator",
                            20,
                            "treatment-high 7/20",
                            applies_to="event_risk",
                        ),
                    ],
                },
            )
        elif name == "meta_source_workspace_investigation":
            response["study_map_update"]["arms"].insert(
                1,
                {
                    "label": "treatment-high",
                    "aliases": ["high-dose active treatment"],
                    "role": "experimental",
                    "description": "high-dose active treatment",
                },
            )
        elif name == "meta_source_workspace_resolution":
            candidate = payload["evidence_notebook"]["candidates"][0]
            high_materials = {
                material["kind"]: material["material_id"]
                for arm in candidate["arms"]
                if arm["label"] == "treatment-high"
                for material in arm["materials"]
            }
            decision = response["decisions"][0]
            decision["experimental_arm_labels"] = ["treatment", "treatment-high"]
            for field in decision["field_evidence"]:
                if field["field"] == "experimental_events":
                    field["material_ids"].append(high_materials["event_count"])
                elif field["field"] == "experimental_total":
                    field["material_ids"].append(
                        high_materials["result_denominator"]
                    )
        elif name == "meta_source_workspace_source_verification":
            review = response["source_reviews"][0]
            if review["source_status"] != "evidence_found":
                return response
            candidate_id = review["selected_candidate_ids"][0]
            review["field_evidence"].extend(
                [
                    _verified_field(
                        "experimental_events",
                        candidate_id,
                        "treatment-high",
                        "event_count",
                        7,
                        "treatment-high 7/20",
                    ),
                    _verified_field(
                        "experimental_total",
                        candidate_id,
                        "treatment-high",
                        "result_denominator",
                        20,
                        "treatment-high 7/20",
                    ),
                ]
            )
        return response


class _AliasArmCaller(_BinaryCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        name = str(kwargs["json_schema_name"])
        response = super().__call__(**kwargs)
        if name == "meta_source_workspace_resolution":
            decision = response["decisions"][0]
            decision["experimental_arm_labels"] = [
                "treatment",
                "active treatment",
            ]
        elif name == "meta_source_workspace_verification":
            verdict = response["verdicts"][0]
            verdict["experimental_arm_labels"] = [
                "treatment",
                "active treatment",
            ]
        return response


class _ConflictingArmIdCaller(_BinaryCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        response = super().__call__(**kwargs)
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_source_verification":
            payload = json.loads(kwargs["prompt"])
            treatment_id = next(
                arm["arm_id"]
                for arm in payload["study_map"]["arms"]
                if arm["label"] == "treatment"
            )
            response["source_reviews"][0]["field_evidence"][0]["arm_id"] = next(
                arm["arm_id"]
                for arm in payload["study_map"]["arms"]
                if arm["arm_id"] != treatment_id
            )
        return response


class _ProvisionalBinaryCaller(_BinaryCaller):
    """The blind resolver proposes a complete row but defers scope to verification."""

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_resolution":
            response = super().__call__(**kwargs)
            response["decisions"][0]["status"] = "unresolved"
            response["decisions"][0]["reason"] = (
                "The denominator scope should be checked against the raw table."
            )
            return response
        return super().__call__(**kwargs)


class _PartialProvisionalBinaryCaller(_ProvisionalBinaryCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        response = super().__call__(**kwargs)
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_resolution":
            response["decisions"][0]["field_evidence"] = response["decisions"][0][
                "field_evidence"
            ][:2]
        return response


class _ReadyPartialBinaryCaller(_BinaryCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        response = super().__call__(**kwargs)
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_resolution":
            response["decisions"][0]["field_evidence"] = []
        return response


class _ContinuousCrossSourceCaller:
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        name = str(kwargs["json_schema_name"])
        payload = json.loads(kwargs["prompt"])
        if name == "meta_source_workspace_scope_audit":
            return _repeat_scope_audit(payload)
        if name == "meta_source_workspace_table_census":
            source_ref = payload["sources"][0]["source_ref"]
            return {
                "source_observations": [
                    {
                        "source_ref": source_ref,
                        "source_status": "target_relevant",
                        "summary": "Pain means and SDs are reported without N.",
                        "candidate_blocks": [
                            {
                                "source_table_id": source_ref,
                                "outcome_label": "pain score",
                                "outcome_measure": "pain scale",
                                "unit": "points",
                                "timepoint": "12 weeks",
                                "population_or_subgroup": "adults with pain",
                                "analysis_population": "intention-to-treat",
                                "data_type": "Continuous",
                                "continuous_result_frame": "post_intervention",
                                "change_score_definition": None,
                                "scale_direction": "higher_is_worse",
                                "arms": [
                                    {
                                        "label": "treatment",
                                        "materials": [
                                            _material(
                                                "tm",
                                                "mean",
                                                12,
                                                "treatment 12 (4)",
                                                applies_to="mean",
                                            ),
                                            _material(
                                                "tsd",
                                                "standard_deviation",
                                                4,
                                                "treatment 12 (4)",
                                                applies_to="mean",
                                            ),
                                        ],
                                    },
                                    {
                                        "label": "placebo",
                                        "materials": [
                                            _material(
                                                "cm",
                                                "mean",
                                                15,
                                                "placebo 15 (5)",
                                                applies_to="mean",
                                            ),
                                            _material(
                                                "csd",
                                                "standard_deviation",
                                                5,
                                                "placebo 15 (5)",
                                                applies_to="mean",
                                            ),
                                        ],
                                    },
                                ],
                                "notes": [],
                                "uncertainties": ["Outcome denominator is not in this table."],
                            }
                        ],
                        "support_materials": [],
                        "study_map_update": _empty_map(),
                        "evidence_needs": [
                            "12-week outcome-complete N for each randomized arm"
                        ],
                    }
                ]
            }
        if name == "meta_source_workspace_investigation":
            section = payload["latest_raw_sources"][0]
            return _investigator_finish(
                support_materials=[
                    {
                        "source_ref": section["source_ref"],
                        "source_kind": "section",
                        "arm_label": "treatment",
                        "outcome_label": "pain score",
                        "outcome_measure": "pain scale",
                        "timepoint": "12 weeks",
                        "population_or_subgroup": "adults with pain",
                        "analysis_population": "intention-to-treat",
                        "material": _material(
                            "tn",
                            "outcome_complete_count",
                            20,
                            "At 12 weeks, pain data were available for all 20 treatment participants",
                            applies_to="participant_flow",
                        ),
                    },
                    {
                        "source_ref": section["source_ref"],
                        "source_kind": "section",
                        "arm_label": "placebo",
                        "outcome_label": "pain score",
                        "outcome_measure": "pain scale",
                        "timepoint": "12 weeks",
                        "population_or_subgroup": "adults with pain",
                        "analysis_population": "intention-to-treat",
                        "material": _material(
                            "cn",
                            "outcome_complete_count",
                            18,
                            "18 placebo participants",
                            applies_to="participant_flow",
                        ),
                    },
                ]
            )
        if name == "meta_source_workspace_arm_reconciliation":
            return _reconcile_arm_observations(payload)
        if name == "meta_source_workspace_resolution":
            candidate = payload["evidence_notebook"]["candidates"][0]
            support = payload["evidence_notebook"]["support_materials"]
            materials = {
                (arm["label"], material["kind"]): material["material_id"]
                for arm in candidate["arms"]
                for material in arm["materials"]
            }
            totals = {
                material["arm_label"]: material["material_id"] for material in support
            }
            return {
                "decisions": [
                    {
                        "target_id": "target-1",
                        "status": "ready",
                        "candidate_ids": [candidate["candidate_id"]],
                        "experimental_arm_labels": ["treatment"],
                        "control_arm_labels": ["placebo"],
                        "field_evidence": [
                            {
                                "field": "experimental_mean",
                                "material_ids": [materials[("treatment", "mean")]],
                            },
                            {
                                "field": "experimental_sd",
                                "material_ids": [
                                    materials[("treatment", "standard_deviation")]
                                ],
                            },
                            {
                                "field": "experimental_total",
                                "material_ids": [totals["treatment"]],
                            },
                            {
                                "field": "control_mean",
                                "material_ids": [materials[("placebo", "mean")]],
                            },
                            {
                                "field": "control_sd",
                                "material_ids": [
                                    materials[("placebo", "standard_deviation")]
                                ],
                            },
                            {
                                "field": "control_total",
                                "material_ids": [totals["placebo"]],
                            },
                        ],
                        "alternative_material_ids": [],
                        "excluded_candidate_ids": [],
                        "assumptions": [],
                        "reason": "The prose explicitly supplies outcome-complete N.",
                    }
                ]
            }
        if name == "meta_source_workspace_source_verification":
            source_ref = payload["source_boundary"]["source_ref"]
            candidate_id = payload["proposals"][0]["selected_candidates"][0][
                "candidate_id"
            ]
            if payload["source_boundary"]["source_kind"] == "table":
                fields = [
                    _verified_field(
                        "experimental_mean",
                        candidate_id,
                        "treatment",
                        "mean",
                        12,
                        "treatment 12 (4)",
                        applies_to="mean",
                    ),
                    _verified_field(
                        "experimental_sd",
                        candidate_id,
                        "treatment",
                        "standard_deviation",
                        4,
                        "treatment 12 (4)",
                        applies_to="mean",
                    ),
                    _verified_field(
                        "control_mean",
                        candidate_id,
                        "placebo",
                        "mean",
                        15,
                        "placebo 15 (5)",
                        applies_to="mean",
                    ),
                    _verified_field(
                        "control_sd",
                        candidate_id,
                        "placebo",
                        "standard_deviation",
                        5,
                        "placebo 15 (5)",
                        applies_to="mean",
                    ),
                ]
            else:
                fields = [
                    _verified_field(
                        "experimental_total",
                        None,
                        "treatment",
                        "outcome_complete_count",
                        20,
                        "At 12 weeks, pain data were available for all 20 treatment participants",
                        source_ref=source_ref,
                        source_kind="section",
                        applies_to="participant_flow",
                    ),
                    _verified_field(
                        "control_total",
                        None,
                        "placebo",
                        "outcome_complete_count",
                        18,
                        "18 placebo participants",
                        source_ref=source_ref,
                        source_kind="section",
                        applies_to="participant_flow",
                    ),
                ]
            return {
                "source_reviews": [
                    {
                        "target_id": "target-1",
                        "source_status": "evidence_found",
                        "selected_candidate_ids": (
                            [candidate_id]
                            if payload["source_boundary"]["source_kind"] == "table"
                            else []
                        ),
                        "field_evidence": fields,
                        "competing_interpretations": [],
                        "reason": "This source verifies its local continuous evidence.",
                    }
                ]
            }
        if name == "meta_source_workspace_cross_source_adjudication":
            return _adjudicate_all_verified_evidence(payload)
        if name == "meta_source_workspace_verification":
            proposal = payload["proposals"][0]
            candidate_id = proposal["selected_candidates"][0]["candidate_id"]
            section_ref = next(
                row["source_ref"]
                for row in payload["raw_source_bundle"]
                if row["source_kind"] == "section"
            )
            return {
                "verdicts": [
                    {
                        "target_id": "target-1",
                        "status": "confirmed",
                        "selected_candidate_ids": [candidate_id],
                        "experimental_arm_labels": ["treatment"],
                        "control_arm_labels": ["placebo"],
                        "field_evidence": [
                            _verified_field(
                                "experimental_mean",
                                candidate_id,
                                "treatment",
                                "mean",
                                12,
                                "treatment 12 (4)",
                                applies_to="mean",
                                supporting_quotes=[
                                    {
                                        "source_ref": section_ref,
                                        "source_kind": "section",
                                        "quote": (
                                            "At 12 weeks, pain data were available for all "
                                            "20 treatment participants"
                                        ),
                                    }
                                ],
                            ),
                            _verified_field(
                                "experimental_sd",
                                candidate_id,
                                "treatment",
                                "standard_deviation",
                                4,
                                "treatment 12 (4)",
                                applies_to="mean",
                            ),
                            _verified_field(
                                "experimental_total",
                                None,
                                "treatment",
                                "outcome_complete_count",
                                20,
                                "At 12 weeks, pain data were available for all 20 treatment participants",
                                source_ref=section_ref,
                                source_kind="section",
                                applies_to="participant_flow",
                            ),
                            _verified_field(
                                "control_mean",
                                candidate_id,
                                "placebo",
                                "mean",
                                15,
                                "placebo 15 (5)",
                                applies_to="mean",
                            ),
                            _verified_field(
                                "control_sd",
                                candidate_id,
                                "placebo",
                                "standard_deviation",
                                5,
                                "placebo 15 (5)",
                                applies_to="mean",
                            ),
                            _verified_field(
                                "control_total",
                                None,
                                "placebo",
                                "outcome_complete_count",
                                18,
                                "18 placebo participants",
                                source_ref=section_ref,
                                source_kind="section",
                                applies_to="participant_flow",
                            ),
                        ],
                        "competing_interpretations": [],
                        "assumptions": [],
                        "reason": "The table and outcome-specific prose have compatible scope.",
                    }
                ]
            }
        raise AssertionError(f"Unexpected schema: {name}")


class _BestSupportedDenominatorCaller(_ContinuousCrossSourceCaller):
    """Selects an arm-level randomized N when no outcome-specific N is printed."""

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        name = str(kwargs["json_schema_name"])
        payload = json.loads(kwargs["prompt"])
        if name == "meta_source_workspace_investigation":
            section = payload["latest_raw_sources"][0]
            return _investigator_finish(
                support_materials=[
                    {
                        "source_ref": section["source_ref"],
                        "source_kind": "section",
                        "arm_label": "treatment",
                        "outcome_label": "pain score",
                        "outcome_measure": "pain scale",
                        "timepoint": "12 weeks",
                        "population_or_subgroup": "adults with pain",
                        "analysis_population": "randomized participants",
                        "material": _material(
                            "tn-randomized",
                            "randomized_total",
                            20,
                            "20 treatment participants were randomized and no treatment exclusions were reported",
                            applies_to="participant_flow",
                        ),
                    },
                    {
                        "source_ref": section["source_ref"],
                        "source_kind": "section",
                        "arm_label": "placebo",
                        "outcome_label": "pain score",
                        "outcome_measure": "pain scale",
                        "timepoint": "12 weeks",
                        "population_or_subgroup": "adults with pain",
                        "analysis_population": "randomized participants",
                        "material": _material(
                            "cn-randomized",
                            "randomized_total",
                            18,
                            "18 placebo participants were randomized and no placebo exclusions were reported",
                            applies_to="participant_flow",
                        ),
                    },
                ]
            )
        if (
            name == "meta_source_workspace_source_verification"
            and payload["source_boundary"]["source_kind"] == "section"
        ):
            section_ref = payload["source_boundary"]["source_ref"]
            return {
                "source_reviews": [
                    {
                        "target_id": "target-1",
                        "source_status": "evidence_found",
                        "selected_candidate_ids": [],
                        "field_evidence": [
                            _verified_field(
                                "experimental_total",
                                None,
                                "treatment",
                                "randomized_total",
                                20,
                                "20 treatment participants were randomized and no treatment exclusions were reported",
                                source_ref=section_ref,
                                source_kind="section",
                                applies_to="participant_flow",
                                selection_basis="supported_inference",
                                selection_confidence="medium",
                                selection_rationale=(
                                    "The arm-level randomized N is the only reported "
                                    "denominator and the source reports no treatment exclusions."
                                ),
                            ),
                            _verified_field(
                                "control_total",
                                None,
                                "placebo",
                                "randomized_total",
                                18,
                                "18 placebo participants were randomized and no placebo exclusions were reported",
                                source_ref=section_ref,
                                source_kind="section",
                                applies_to="participant_flow",
                                selection_basis="supported_inference",
                                selection_confidence="medium",
                                selection_rationale=(
                                    "The arm-level randomized N is the only reported "
                                    "denominator and the source reports no placebo exclusions."
                                ),
                            ),
                        ],
                        "competing_interpretations": [],
                        "reason": (
                            "The raw report supports the randomized arm denominators "
                            "and provides no contradictory outcome-specific exclusion."
                        ),
                    }
                ]
            }
        return super().__call__(**kwargs)


class _InvalidSelectionThenBestCaller(_BestSupportedDenominatorCaller):
    def __init__(self) -> None:
        self.invalid_once = True

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        response = super().__call__(**kwargs)
        if (
            self.invalid_once
            and str(kwargs["json_schema_name"])
            == "meta_source_workspace_source_verification"
            and json.loads(kwargs["prompt"])["source_boundary"]["source_kind"]
            == "section"
        ):
            self.invalid_once = False
            for field in response["source_reviews"][0]["field_evidence"]:
                if field["field"].endswith("_total"):
                    field["selection_basis"] = "direct"
            return response
        return response


class _UnknownDirectionContinuousCaller(_ContinuousCrossSourceCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        response = super().__call__(**kwargs)
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_table_census":
            for observation in response["source_observations"]:
                for candidate in observation["candidate_blocks"]:
                    candidate["scale_direction"] = "unclear"
        return response


def _verified_field(
    field: str,
    candidate_id: str | None,
    arm_label: str,
    kind: str,
    value: float,
    quote: str,
    *,
    source_ref: str = "table-result",
    source_kind: str = "table",
    applies_to: str = "event_risk",
    selection_basis: str | None = None,
    selection_confidence: str = "high",
    selection_rationale: str | None = None,
    scope_status: str = "complete",
    footnote_links: list[dict[str, str]] | None = None,
    supporting_quotes: list[dict[str, str]] | None = None,
    denominator_scope: str | None = None,
) -> dict[str, Any]:
    if selection_basis is None:
        selection_basis = (
            "direct"
            if kind
            in {
                "event_count",
                "result_denominator",
                "analyzed_total",
                "outcome_complete_count",
                "mean",
                "standard_deviation",
            }
            else "supported_inference"
        )
    if denominator_scope is None:
        denominator_scope = {
            "result_denominator": "result_cell_or_row",
            "analyzed_total": "analysis_population",
            "outcome_complete_count": "outcome_complete",
            "randomized_total": "randomized_or_baseline",
            "baseline_total": "randomized_or_baseline",
        }.get(kind, "not_applicable")
    is_binary = applies_to == "event_risk"
    return {
        "field": field,
        "candidate_id": candidate_id,
        "source_ref": source_ref,
        "source_kind": source_kind,
        "arm_label": arm_label,
        "selection_basis": selection_basis,
        "selection_confidence": selection_confidence,
        "selection_rationale": selection_rationale
        or f"The raw {source_kind} reports this {kind} for the selected scope.",
        "evidence_scope": {
            "outcome_label": "pain response" if is_binary else "pain score",
            "outcome_measure": "pain response" if is_binary else "pain scale",
            "timepoint": "12 weeks",
            "arm_label": arm_label,
            "analysis_population": (
                "randomized participants"
                if kind in {"randomized_total", "baseline_total"}
                else "intention-to-treat"
            ),
            "result_frame": "not_applicable" if is_binary else "post_intervention",
            "row_or_item_label": "pain response" if is_binary else "pain score",
            "column_header_path": [arm_label] if source_kind == "table" else [],
            "denominator_scope": denominator_scope,
            "footnote_links": footnote_links or [],
            "supporting_quotes": supporting_quotes or [],
            "scope_status": scope_status,
        },
        "material": _material(
            f"verify-{field}", kind, value, quote, applies_to=applies_to
        ),
    }


def _empty_source_review(
    payload: dict[str, Any],
    *,
    source_ref: str,
) -> dict[str, Any]:
    return {
        "source_reviews": [
            {
                "target_id": target["target_id"],
                "source_status": "no_relevant_evidence",
                "selected_candidate_ids": [],
                "field_evidence": [],
                "competing_interpretations": [],
                "reason": f"{source_ref} contains no evidence needed for this target.",
            }
            for target in payload["targets"]
        ]
    }


def _reconcile_arm_observations(payload: dict[str, Any]) -> dict[str, Any]:
    observations = payload["source_local_arm_observations"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for observation in observations:
        label = str(observation["observed_label"]).casefold()
        if label in {"treatment", "active treatment", "experimental group", "eg"}:
            key = "treatment"
        elif label in {"placebo", "control", "control group", "cg"}:
            key = "placebo"
        else:
            key = label
        groups.setdefault(key, []).append(observation)
    rows = []
    for key, members in groups.items():
        roles = {str(row.get("role") or "unclear") for row in members}
        role = next(iter(roles - {"unclear"}), "unclear")
        if role == "unclear":
            if key == "treatment" or key.startswith("treatment-"):
                role = "experimental"
            elif key == "placebo":
                role = "control"
        canonical = {
            "treatment": "treatment",
            "placebo": "placebo",
        }.get(key, str(members[0]["observed_label"]))
        rows.append(
            {
                "canonical_label": canonical,
                "aliases": list(dict.fromkeys(
                    [
                        str(row["observed_label"])
                        for row in members
                        if str(row["observed_label"]).casefold()
                        != canonical.casefold()
                    ]
                    + (
                        ["active treatment"]
                        if key == "treatment"
                        else ["control"]
                        if key == "placebo"
                        else []
                    )
                )),
                "role": role,
                "description": next(
                    (
                        str(row["description"])
                        for row in members
                        if row.get("description")
                    ),
                    canonical,
                ),
                "member_observation_ids": [
                    row["observation_id"] for row in members
                ],
                "evidence_source_refs": sorted(
                    {str(row["source_ref"]) for row in members}
                ),
                "rationale": "The source-local descriptions and labels identify one article arm.",
            }
        )
    return {
        "canonical_arms": rows,
        "unresolved_observation_ids": [],
        "notes": [],
    }


def _adjudicate_all_verified_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    study_map = payload["study_map"]
    experimental_ids = [
        arm["arm_id"]
        for arm in study_map["arms"]
        if arm.get("role") == "experimental"
    ]
    control_ids = [
        arm["arm_id"] for arm in study_map["arms"] if arm.get("role") == "control"
    ]
    evidence = [
        row
        for review in payload["verified_source_reviews"]
        for row in review.get("verified_evidence") or []
    ]
    by_field: dict[str, list[str]] = {}
    for row in evidence:
        by_field.setdefault(row["field"], []).append(row["evidence_id"])
    proposals = {row["target_id"]: row for row in payload["proposals"]}
    return {
        "verdicts": [
            {
                "target_id": target["target_id"],
                "status": "confirmed" if by_field else "unresolved",
                "selected_candidate_ids": [
                    row["candidate_id"]
                    for row in proposals[target["target_id"]]["selected_candidates"]
                ],
                "experimental_arm_ids": experimental_ids,
                "control_arm_ids": control_ids,
                "field_selections": [
                    {"field": field, "evidence_ids": ids}
                    for field, ids in by_field.items()
                ],
                "competing_interpretations": [],
                "assumptions": [],
                "scale_direction": (
                    "unclear"
                    if target["data_type"] == "Continuous"
                    else "not_applicable"
                ),
                "scale_direction_basis": (
                    "insufficient_information"
                    if target["data_type"] == "Continuous"
                    else "not_applicable"
                ),
                "scale_direction_confidence": (
                    "low"
                    if target["data_type"] == "Continuous"
                    else "not_applicable"
                ),
                "scale_direction_rationale": (
                    "The source names a continuous scale but does not establish whether higher scores are clinically better or worse."
                    if target["data_type"] == "Continuous"
                    else "Scale direction is not applicable to a dichotomous outcome."
                ),
                "direct_effect_semantics": {
                    "comparison_direction": "not_applicable",
                    "change_score_direction": "not_applicable",
                    "basis": "not_applicable",
                    "confidence": "not_applicable",
                    "rationale": (
                        "The selected representation is arm-level and does not "
                        "contain a direct between-group effect."
                        if target["data_type"] == "Continuous"
                        else "Direct-effect semantics are not applicable to a dichotomous outcome."
                    ),
                },
                "reason": "All selected evidence cards have compatible source scope.",
            }
            for target in payload["targets"]
        ]
    }


def _repeat_scope_audit(payload: dict[str, Any]) -> dict[str, Any]:
    verdicts = deepcopy(payload["initial_verdicts"])
    for verdict in verdicts:
        verdict["status"] = "confirmed"
        verdict["reason"] = "The focused raw-source audit confirms the field scopes."
        for index, field in enumerate(verdict["field_evidence"]):
            field["material"]["evidence_key"] = (
                f"scope-audit-{field['field']}-{index}"
            )
    return {"verdicts": verdicts}


class _FootnoteScopeCaller(_BinaryCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        name = str(kwargs["json_schema_name"])
        response = super().__call__(**kwargs)
        if name == "meta_source_workspace_source_verification":
            for field in response["source_reviews"][0]["field_evidence"]:
                if field["field"] == "control_total":
                    field["material"]["value"] = 18
                    field["material"]["source_quote"] = "placebo 8/18"
                    field["evidence_scope"]["denominator_scope"] = "outcome_complete"
                    field["evidence_scope"]["footnote_links"] = [
                        {
                            "marker": "f",
                            "text": "f: placebo 8/18 at 12 weeks",
                        }
                    ]
                    field["selection_basis"] = "direct"
                    field["selection_confidence"] = "high"
                    field["selection_rationale"] = (
                        "The linked footnote identifies the outcome-specific denominator."
                    )
        return response


class _AuxiliaryBadQuoteCaller(_BinaryCaller):
    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        response = super().__call__(**kwargs)
        if str(kwargs["json_schema_name"]) == "meta_source_workspace_table_census":
            for observation in response["source_observations"]:
                for candidate in observation["candidate_blocks"]:
                    candidate["arms"][0]["materials"].append(
                        _material(
                            "aux-p",
                            "p_value",
                            0.05,
                            "synthetic quote not in the source",
                            applies_to="unclear",
                        )
                    )
        return response


def _binary_article() -> dict[str, Any]:
    return {
        "study_id": "study-1",
        "metadata": {"publication_year": "2024"},
        "xml_content": {
            "sections": [
                {
                    "section_id": "methods",
                    "title": "",
                    "text": (
                        "Adults with pain were randomized to treatment or placebo "
                        "and assessed at 12 weeks."
                    ),
                }
            ]
        },
        "tables": [
            {
                "table_id": "table-result",
                "caption": "",
                "raw_xml": (
                    "<table><tr><td>treatment 5/20</td>"
                    "<td>placebo 8/20</td></tr></table>"
                ),
            },
            {
                "table_id": "table-other",
                "caption": "",
                "raw_xml": "<table><tr><td>Author affiliations</td></tr></table>",
            },
        ],
    }


def _binary_footnote_article() -> dict[str, Any]:
    article = _binary_article()
    article["tables"][0]["raw_xml"] = (
        "<table><thead><tr><th>Treatment n=20</th><th>Placebo n=20</th></tr></thead>"
        "<tbody><tr><td>treatment 5/20</td><td>placebo 8/20</td></tr></tbody>"
        "<table-wrap-foot><fn id=\"f\"><p>f: placebo 8/18 at 12 weeks</p></fn>"
        "</table-wrap-foot></table>"
    )
    return article


def _continuous_cross_source_article() -> dict[str, Any]:
    return {
        "study_id": "study-1",
        "metadata": {"publication_year": "2024"},
        "xml_content": {
            "sections": [
                {
                    "section_id": "results",
                    "title": "",
                    "text": (
                        "At 12 weeks, pain data were available for all 20 treatment "
                        "participants and 18 placebo participants."
                    ),
                }
            ]
        },
        "tables": [
            {
                "table_id": "table-result",
                "caption": "",
                "raw_xml": (
                    "<table><tr><td>pain score at 12 weeks</td>"
                    "<td>treatment 12 (4)</td><td>placebo 15 (5)</td>"
                    "</tr></table>"
                ),
            }
        ],
    }


def _continuous_randomized_denominator_article() -> dict[str, Any]:
    article = _continuous_cross_source_article()
    article["xml_content"]["sections"][0]["text"] = (
        "20 treatment participants were randomized and no treatment exclusions "
        "were reported. 18 placebo participants were randomized and no placebo "
        "exclusions were reported."
    )
    return article


def test_source_workspace_reads_blank_titles_and_exact_windows() -> None:
    article = _binary_article()
    article["tables"][0]["raw_xml"] = "x" * 1_400
    workspace = SourceWorkspace.from_article(study_id="study-1", article=article)

    windows, omitted = workspace.table_windows(
        max_window_chars=1_000,
        overlap_chars=100,
    )

    assert omitted == []
    assert windows[0].title == ""
    assert windows[0].content == "x" * 1_000
    assert windows[1].start == 900
    assert workspace.search_sections(["randomized"])[0]["source_ref"].endswith(
        "section::0000"
    )


def test_scope_audit_windows_prefer_complete_raw_source_when_bounded() -> None:
    article = _binary_footnote_article()
    workspace = SourceWorkspace.from_article(study_id="study-1", article=article)

    payloads = workspace.scope_audit_windows(
        source_refs=["table-result"],
        evidence_locators=[
            {
                "source_ref": "table-result",
                "source_kind": "table",
                "transport": {"start": 0, "end": 60},
                "source_quote": "placebo 8/20",
            }
        ],
        max_window_chars=1_000,
        max_total_chars=10_000,
    )

    assert len(payloads) == 1
    assert payloads[0]["transport"]["kind"] == "complete_source"
    assert "table-wrap-foot" in payloads[0]["raw_xml"]
    coverage = workspace.source_bundle_coverage(
        source_refs=["table-result"], payloads=payloads
    )
    assert coverage["complete_source_refs"] == ["table-result"]
    assert workspace.source("table-result").has_scope_linkage_markup is True


def test_scope_audit_windows_report_partial_transport_under_budget() -> None:
    article = _binary_footnote_article()
    article["tables"][0]["raw_xml"] = "<table>" + ("x" * 2_600) + "</table>"
    workspace = SourceWorkspace.from_article(study_id="study-1", article=article)

    payloads = workspace.scope_audit_windows(
        source_refs=["table-result"],
        evidence_locators=[
            {
                "source_ref": "table-result",
                "source_kind": "table",
                "transport": {"start": 1_200, "end": 1_300},
                "source_quote": "",
            }
        ],
        max_window_chars=1_000,
        max_total_chars=1_500,
    )

    assert payloads
    assert payloads[-1]["context_budget_exceeded"] is True
    coverage = workspace.source_bundle_coverage(
        source_refs=["table-result"], payloads=payloads
    )
    assert coverage["partial_source_refs"] == ["table-result"]
    assert coverage["context_budget_exceeded"] is True


def test_unresolved_verdict_with_candidate_is_routed_to_scope_audit() -> None:
    workspace = SourceWorkspace.from_article(
        study_id="study-1", article=_binary_article()
    )
    reasons = _scope_audit_reasons(
        {
            "status": "unresolved",
            "selected_candidate_ids": ["candidate-1"],
            "competing_interpretations": [],
        },
        workspace=workspace,
        verification_context_limited=False,
    )
    assert reasons == ["verification_unresolved"]


def test_source_workspace_marks_section_context_budget_without_cutting_windows() -> None:
    article = _binary_article()
    article["xml_content"]["sections"][0]["text"] = "randomized " * 220
    workspace = SourceWorkspace.from_article(study_id="study-1", article=article)

    payloads = workspace.read_sources(
        ["study-1::section::0000"],
        max_window_chars=1_000,
        overlap_chars=100,
        max_total_chars=1_500,
    )

    assert len(payloads) == 1
    assert len(payloads[0]["text"]) == 1_000
    assert payloads[0]["context_budget_exceeded"] is True


def test_source_workspace_marks_section_window_limit() -> None:
    article = _binary_article()
    article["xml_content"]["sections"][0]["text"] = "randomized " * 220
    workspace = SourceWorkspace.from_article(study_id="study-1", article=article)

    payloads = workspace.read_sources(
        ["study-1::section::0000"],
        max_window_chars=1_000,
        overlap_chars=100,
        max_windows=1,
    )

    assert len(payloads) == 1
    assert payloads[0]["context_budget_exceeded"] is True


def test_source_workspace_marks_search_result_limit() -> None:
    article = _binary_article()
    article["xml_content"]["sections"].append(
        {
            "section_id": "results-2",
            "title": "",
            "text": "Randomized participants were included in the analysis.",
        }
    )
    workspace = SourceWorkspace.from_article(study_id="study-1", article=article)

    payloads = workspace.search_sections(["randomized"], max_results=1)

    assert len(payloads) == 1
    assert payloads[0]["context_budget_exceeded"] is True


def test_source_workspace_exposes_title_and_abstract_as_front_matter() -> None:
    article = _binary_article()
    article["metadata"]["title"] = "Active treatment for adults with pain"
    article["xml_content"]["sections"].insert(
        0,
        {
            "section_id": "abstract",
            "title": "Abstract",
            "text": "This randomized trial compared active treatment with placebo.",
        },
    )
    workspace = SourceWorkspace.from_article(study_id="study-1", article=article)

    assert workspace.front_matter_refs == [
        "study-1::front::title",
        "study-1::section::0000",
    ]
    sources = workspace.read_sources(workspace.front_matter_refs)
    assert sources[0]["text"] == "Active treatment for adults with pain"
    assert sources[1]["text"].startswith("This randomized trial")
    assert workspace.manifest()["sections"][0]["title"] == (
        "Active treatment for adults with pain"
    )


def test_title_alone_does_not_bypass_empty_article_gate() -> None:
    article = {
        "study_id": "study-1",
        "metadata": {"title": "A study title"},
        "xml_content": {"sections": []},
        "tables": [],
    }

    with pytest.raises(ValueError, match="no readable section or raw table"):
        SourceWorkspace.from_article(study_id="study-1", article=article)


def test_default_context_search_includes_target_population() -> None:
    article = _binary_article()
    article["metadata"]["title"] = "Trial in adults with pain"
    caller = _BinaryCaller()

    Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=article,
        plan_hash="plan-hash",
    )

    investigation = next(
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_investigation"
    )
    assert investigation["latest_raw_sources"][0]["source_ref"] == (
        "study-1::front::title"
    )
    assert "adults with pain" in investigation["latest_raw_sources"][0]["text"]
    assert investigation["remaining_budget"]["section_searches"] > 0
    assert investigation["remaining_budget"]["source_read_windows"] > 0
    assert "article_hash" not in investigation["source_catalog"]
    assert "source_hash" not in investigation["latest_raw_sources"][0]


def test_census_context_keeps_exact_raw_xml_but_scopes_target_and_transport() -> None:
    workspace = SourceWorkspace.from_article(
        study_id="study-1",
        article=_binary_article(),
    )
    windows, _ = workspace.table_windows()
    source_payload = windows[0].to_payload()

    compiled = compile_census_context(
        targets=[_target()],
        source_payloads=[source_payload],
    )
    payload = compiled.aliases.encode(compiled.payload)

    assert payload["sources"][0]["raw_xml"] == source_payload["raw_xml"]
    assert "source_hash" not in payload["sources"][0]
    assert "start" not in payload["sources"][0]["window"]
    assert "end" not in payload["sources"][0]["window"]
    assert "result_selection_policy" not in payload["targets"][0]
    assert "effect_measure_plan" not in payload["targets"][0]
    assert "analysis_model_plan" not in payload["targets"][0]
    assert "notes" not in payload["targets"][0]


def test_evidence_need_lifecycle_removes_resolved_work_from_active_context() -> None:
    workspace = SourceWorkspace.from_article(
        study_id="study-1",
        article=_binary_article(),
    )
    notebook = empty_notebook(workspace=workspace)
    register_evidence_needs(
        notebook,
        needs=["confirm randomized arm identity"],
        source_ref="table-result",
    )
    need_id = active_evidence_needs(notebook)[0]["need_id"]
    updates = normalize_evidence_need_updates(
        [
            {
                "need_id": need_id,
                "status": "resolved",
                "source_refs": ["table-result"],
                "reason": "The randomized arms are explicit in the table.",
            }
        ],
        known_need_ids={need_id},
        allowed_source_refs={"table-result"},
    )

    apply_evidence_need_updates(notebook, updates=updates)

    assert active_evidence_needs(notebook) == []
    assert notebook["evidence_needs"] == []
    assert notebook["evidence_need_registry"][0]["status"] == "resolved"


def test_request_budget_counts_system_payload_schema_and_output() -> None:
    summary = request_input_summary(
        config={"context_window_tokens": 32_000},
        system="system prompt",
        payload={"task": "test", "raw_source": "x" * 4_000},
        schema={"type": "object", "properties": {}},
        max_output_tokens=4_096,
        alias_map={},
    )

    assert summary["components"]["system"]["estimated_tokens"] > 0
    assert summary["components"]["payload"]["estimated_tokens"] >= 1_000
    assert summary["components"]["schema"]["estimated_tokens"] > 0
    assert summary["estimated_total_context_tokens"] > 4_096
    assert summary["fits_context_window"] is True


def test_meta_llm_calls_use_the_method_specific_timeout() -> None:
    caller = _TimeoutCaptureCaller()

    Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert caller.timeout_seconds
    assert set(caller.timeout_seconds) == {DEFAULT_LLM_TIMEOUT_SECONDS}


def test_call_artifacts_are_durable_before_and_after_provider_call(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("META_STUDY_EVIDENCE_DEBUG_DIR", str(tmp_path))
    delegate = _BinaryCaller()
    observed_started: list[bool] = []

    def caller(**kwargs: Any) -> dict[str, Any]:
        if kwargs["json_schema_name"] == "meta_source_workspace_table_census":
            paths = list(tmp_path.rglob("census_*_attempt_1.json"))
            observed_started.append(
                any(
                    json.loads(path.read_text(encoding="utf-8"))["status"]
                    == "started"
                    for path in paths
                )
            )
        return delegate(**kwargs)

    Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert observed_started and all(observed_started)
    debug_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    attempt = json.loads(
        (debug_dir / "census_000_attempt_1.json").read_text(encoding="utf-8")
    )
    assert attempt["status"] == "accepted"
    assert attempt["input_summary"]["fits_context_window"] is True
    assert set(attempt["input_summary"]["components"]) == {
        "system",
        "payload",
        "schema",
        "provider_overhead",
    }
    ledger = [
        json.loads(line)
        for line in (debug_dir / "call_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert ledger[0]["status"] == "started"
    assert any(row["status"] == "accepted" for row in ledger)
    assert (debug_dir / "investigation_state.json").exists()
    assert (debug_dir / "resolution_state.json").exists()
    assert (debug_dir / "verification_state.json").exists()


def test_preflight_context_budget_failure_does_not_call_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("META_STUDY_EVIDENCE_DEBUG_DIR", str(tmp_path))
    caller = _BinaryCaller()

    with pytest.raises(MetaAnalysisInvocationError) as captured:
        Method(
            config={"model": "fake", "context_window_tokens": 8_000},
            llm_caller=caller,
            max_table_workers=1,
        ).run(
            review_id="review-1",
            targets=[_target()],
            study_id="study-1",
            article=_binary_article(),
            plan_hash="plan-hash",
        )

    assert captured.value.failure_code == "context_budget_exceeded"
    assert captured.value.attempts == 0
    assert caller.calls == []
    attempt_path = next(tmp_path.rglob("census_000_attempt_1.json"))
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    assert attempt["status"] == "context_budget_exceeded"


def test_meta_llm_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="llm_timeout_seconds"):
        Method(
            config={"model": "fake"},
            llm_caller=_BinaryCaller(),
            llm_timeout_seconds=0,
        )


def test_verification_relocates_rendered_quote_inside_long_raw_xml() -> None:
    prefix = "<td>irrelevant</td>" * 900
    raw_xml = (
        "<table><tr>"
        + prefix
        + "<td><b>Treatment</b> 5/20</td><td>Placebo 8/20</td>"
        + "</tr></table>"
    )
    article = _binary_article()
    article["tables"] = [
        {
            "table_id": "long-result",
            "caption": "",
            "raw_xml": raw_xml,
        }
    ]
    workspace = SourceWorkspace.from_article(study_id="study-1", article=article)
    table_windows, _ = workspace.table_windows(
        max_window_chars=2_000,
        overlap_chars=200,
    )
    source_window = next(
        row.to_payload()
        for row in table_windows
        if "Treatment" in row.content
    )
    payloads = workspace.evidence_windows(
        evidence_locators=[
            {
                "source_ref": "long-result",
                "source_kind": "table",
                "source_hash": source_window["source_hash"],
                "transport": source_window["transport"],
                "source_quote": "Treatment 5/20",
            }
        ],
        max_window_chars=1_000,
    )
    assert payloads
    assert any("5/20" in row["raw_xml"] for row in payloads)
    assert all(len(row["raw_xml"]) <= 1_000 for row in payloads)


def test_verification_marks_evidence_window_limit() -> None:
    article = _binary_article()
    workspace = SourceWorkspace.from_article(study_id="study-1", article=article)

    payloads = workspace.evidence_windows(
        evidence_locators=[
            {
                "source_ref": "table-result",
                "source_kind": "table",
                "transport": {"start": 0, "end": 55},
                "source_quote": "Treatment 5/20",
            },
            {
                "source_ref": "table-other",
                "source_kind": "table",
                "transport": {"start": 0, "end": 55},
                "source_quote": "Author affiliations",
            },
        ],
        max_window_chars=1_000,
        max_windows=1,
    )

    assert len(payloads) == 1
    assert payloads[0]["context_budget_exceeded"] is True


def test_result_blind_projection_drops_free_form_numeric_evidence() -> None:
    notebook = empty_notebook(
        workspace=SourceWorkspace.from_article(
            study_id="study-1",
            article=_binary_article(),
        )
    )
    notebook["claims"] = [
        {
            "claim": "The observed effect was 123.456.",
            "scope": "result",
            "source_refs": ["table-result"],
        }
    ]
    notebook["open_questions"] = ["Is the denominator 123.456 or 20?"]
    notebook["support_materials"] = [
        {
            "material_id": "material::support",
            "kind": "result_denominator",
            "value": 20,
            "source_ref": "table-result",
            "source_kind": "table",
            "interpretation": "The hidden value is 123.456.",
            "uncertainties": ["Could be 123.456"],
            "local_setting": {"outcome_label": "pain response"},
        }
    ]
    projection = result_blind_notebook(notebook)
    serialized = json.dumps(projection, ensure_ascii=False)
    assert "123.456" not in serialized
    assert "claims" not in projection
    assert "open_questions" not in projection


def test_quote_grounding_accepts_xml_wrapped_visible_table_text() -> None:
    assert _quote_matches_visible_source(
        '<th align="left" colspan="1">3 month (N\u2009=\u200927)</th>',
        "Intervention 3 month (N = 27) Joint pain 1.30 (1.68)",
    )


def test_result_blind_projection_hides_numeric_population_descriptions() -> None:
    notebook = empty_notebook(
        workspace=SourceWorkspace.from_article(
            study_id="study-1",
            article=_binary_article(),
        )
    )
    notebook["study_map"]["analysis_populations"] = ["Group treatment n=30"]
    notebook["study_map"]["arms"] = [
        {
            "label": "treatment",
            "aliases": [],
            "role": "experimental",
            "description": "30 participants received treatment",
        }
    ]
    notebook["candidates"] = [
        {
            "candidate_id": "candidate::table-result::one",
            "source_table_id": "table-result",
            "data_type": "Dichotomous",
            "contribution_shape": "arm_level",
            "local_setting": {
                "outcome_label": "pain response",
                "analysis_population": "treatment n=30",
            },
            "arms": [],
            "uncertainties": [],
        }
    ]

    projection = result_blind_notebook(notebook)
    serialized = json.dumps(projection, ensure_ascii=False)
    assert "n=30" not in serialized
    assert "30 participants" not in serialized
    assert "Group treatment n=[hidden]" in serialized


def test_agent_reads_all_tables_resolves_blindly_and_uses_code_for_result() -> None:
    caller = _BinaryCaller()
    result = Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert result["coverage"]["status"] == "complete"
    assert result["coverage"]["read_table_ids"] == [
        "table-result",
        "table-other",
    ]
    assert result["resolution_records"][0]["status"] == "resolved"
    assert result["data_rows"][0]["result_data"] == {
        "experimental_events": 5,
        "experimental_total": 20,
        "control_events": 8,
        "control_total": 20,
    }
    assert (
        result["study_result_rows"][0]["result_items"][0]["study_result_setting"][
            "statistic_type"
        ]
        == "events/N"
    )
    assert [name for name, _ in caller.calls] == [
        "meta_source_workspace_table_census",
        "meta_source_workspace_table_census",
        "meta_source_workspace_investigation",
        "meta_source_workspace_arm_reconciliation",
        "meta_source_workspace_resolution",
        "meta_source_workspace_source_verification",
        "meta_source_workspace_cross_source_adjudication",
    ]
    arm_payload = next(
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_arm_reconciliation"
    )
    assert "targets" not in arm_payload
    resolution_payload = next(
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_resolution"
    )
    assert resolution_payload["evidence_notebook"]["ambiguities"][
        "active_evidence_needs"
    ]
    verification_payload = next(
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_source_verification"
    )
    verification_materials = [
        material
        for candidate in verification_payload["candidate_context"]
        for arm in candidate["arms"]
        for material in arm["materials"]
    ]
    assert all("value" not in material for material in verification_materials)
    assert all("source_quote" not in material for material in verification_materials)


def test_census_allows_cross_table_study_map_evidence_but_keeps_candidate_local() -> None:
    result = Method(
        config={"model": "fake"},
        llm_caller=_CrossTableStudyMapCaller(),
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert result["resolution_records"][0]["status"] == "resolved"
    candidate = result["study_result_rows"][0]["result_items"][0]
    assert candidate["study_local_result"]["source_table_id"] == "table-result"


def test_markerless_tablewide_footnote_is_valid_when_its_text_is_grounded() -> None:
    article = _binary_article()
    article["tables"][0]["raw_xml"] = article["tables"][0]["raw_xml"].replace(
        "</table>",
        "<tfoot><tr><td>Data are presented as counts.</td></tr></tfoot></table>",
    )
    result = Method(
        config={"model": "fake"},
        llm_caller=_MarkerlessFootnoteCaller(),
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=article,
        plan_hash="plan-hash",
    )

    field = result["data_rows"][0]["derivation"]["input_values"][
        "field_selection"
    ]["experimental_events"][0]
    assert field["evidence_scope"]["footnote_links"] == [
        {"marker": None, "text": "Data are presented as counts."}
    ]


def test_no_compatible_table_candidate_has_machine_readable_reason_code() -> None:
    result = Method(
        config={"model": "fake"},
        llm_caller=_NoCompatibleTableCandidateCaller(),
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    row = result["study_result_rows"][0]
    record = result["resolution_records"][0]
    assert row["extraction_status"] == "data_unavailable"
    assert row["extraction_status_reason"] == "no_compatible_table_candidate"
    assert record["failure_code"] == "no_compatible_table_candidate"
    assert result["coverage"]["target_resolution_reasons"]["target-1"][
        "reason_code"
    ] == "no_compatible_table_candidate"


def test_resolution_reason_code_distinguishes_absent_and_incompatible_table_candidates() -> None:
    decision = {"status": "data_unavailable"}
    assert _resolution_reason_code(
        resolution=decision,
        candidates=[],
        target_data_type="Dichotomous",
    ) == "no_eligible_table_candidate"
    assert _resolution_reason_code(
        resolution=decision,
        candidates=[{"data_type": "Dichotomous"}],
        target_data_type="Dichotomous",
    ) == "no_compatible_table_candidate"


def test_source_local_verification_rechecks_structural_footnote_without_fixed_precedence() -> None:
    caller = _FootnoteScopeCaller()
    result = Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_footnote_article(),
        plan_hash="plan-hash",
    )

    assert result["data_rows"][0]["result_data"] == {
        "experimental_events": 5,
        "experimental_total": 20,
        "control_events": 8,
        "control_total": 18,
    }
    assert "meta_source_workspace_source_verification" in [
        name for name, _ in caller.calls
    ]
    assert "meta_source_workspace_scope_audit" not in [
        name for name, _ in caller.calls
    ]
    assert result["coverage"]["scope_audit_target_ids"] == []
    control_selection = result["data_rows"][0]["derivation"]["input_values"][
        "field_selection"
    ]["control_total"][0]
    assert control_selection["evidence_scope"]["footnote_links"][0]["marker"] == "f"


def test_census_keeps_unlocated_auxiliary_material_without_losing_valid_result() -> None:
    caller = _AuxiliaryBadQuoteCaller()
    result = Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert result["resolution_records"][0]["status"] == "resolved"
    assert result["data_rows"][0]["result_data"]["experimental_events"] == 5
    assert [name for name, _ in caller.calls].count(
        "meta_source_workspace_table_census"
    ) == 2


def test_verification_accepts_one_complete_field_set_per_selected_arm() -> None:
    article = _binary_article()
    article["tables"][0]["raw_xml"] = (
        "<table><tr><td>treatment 5/20</td>"
        "<td>treatment-high 7/20</td><td>placebo 8/20</td></tr></table>"
    )

    result = Method(
        config={"model": "fake"},
        llm_caller=_MultiArmCaller(),
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=article,
        plan_hash="plan-hash",
    )

    assert result["resolution_records"][0]["operation"] == (
        "combine_experimental_arms"
    )
    assert result["data_rows"][0]["result_data"] == {
        "experimental_events": 12,
        "experimental_total": 40,
        "control_events": 8,
        "control_total": 20,
    }
    selections = result["data_rows"][0]["derivation"]["input_values"][
        "field_selection"
    ]
    assert [row["arm_label"] for row in selections["experimental_events"]] == [
        "treatment",
        "treatment-high",
    ]


def test_arm_aliases_collapse_to_one_article_arm_identity() -> None:
    result = Method(
        config={"model": "fake"},
        llm_caller=_AliasArmCaller(),
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert result["resolution_records"][0]["status"] == "resolved"
    assert result["resolution_records"][0]["operation"] == "select_direct"
    assert result["data_rows"][0]["result_data"] == {
        "experimental_events": 5,
        "experimental_total": 20,
        "control_events": 8,
        "control_total": 20,
    }


def test_arm_reconciliation_keeps_generic_control_observations_distinct() -> None:
    notebook = empty_notebook(
        workspace=SourceWorkspace.from_article(
            study_id="study-1", article=_binary_article()
        )
    )
    notebook["source_study_maps"] = [
        {
            "source_ref": "table-a",
            "study_map": {
                **_empty_map(),
                "arms": [{"label": "Control", "aliases": [], "role": "control", "description": "placebo"}],
            },
        },
        {
            "source_ref": "table-b",
            "study_map": {
                **_empty_map(),
                "arms": [{"label": "Control", "aliases": [], "role": "control", "description": "usual care"}],
            },
        },
    ]
    observations = arm_observations(notebook)
    reconciliation = normalize_arm_reconciliation_response(
        {
            "canonical_arms": [
                {
                    "canonical_label": "Placebo",
                    "aliases": ["Control"],
                    "role": "control",
                    "description": "placebo",
                    "member_observation_ids": [observations[0]["observation_id"]],
                    "evidence_source_refs": ["table-a"],
                    "rationale": "The source describes placebo.",
                },
                {
                    "canonical_label": "Usual care",
                    "aliases": ["Control"],
                    "role": "control",
                    "description": "usual care",
                    "member_observation_ids": [observations[1]["observation_id"]],
                    "evidence_source_refs": ["table-b"],
                    "rationale": "The source describes usual care.",
                },
            ],
            "unresolved_observation_ids": [],
            "notes": [],
        },
        observations=observations,
        valid_source_refs={"table-a", "table-b"},
    )
    apply_arm_reconciliation(
        notebook, observations=observations, reconciliation=reconciliation
    )

    assert [arm["label"] for arm in notebook["study_map"]["arms"]] == [
        "Placebo",
        "Usual care",
    ]
    assert article_arm_id_for_label("Control", study_map=notebook["study_map"]) is None


def test_shared_role_alias_does_not_collapse_distinct_parenthetical_arms() -> None:
    study_map = merge_study_map(
        _empty_map(),
        {
            **_empty_map(),
            "arms": [
                {
                    "label": "Experimental (ISO-MR)",
                    "aliases": ["ISO-MR", "Experimental"],
                    "role": "experimental",
                    "description": "multiple-repetition isometric exercise",
                },
                {
                    "label": "Experimental (ISO-SR)",
                    "aliases": ["ISO-SR", "Experimental"],
                    "role": "experimental",
                    "description": "single-repetition isometric exercise",
                },
                {
                    "label": "Control",
                    "aliases": ["quiet sitting"],
                    "role": "control",
                    "description": "inactive control",
                },
            ],
        },
    )

    assert [arm["label"] for arm in study_map["arms"]] == [
        "Experimental (ISO-MR)",
        "Experimental (ISO-SR)",
        "Control",
    ]
    assert [arm["arm_id"] for arm in study_map["arms"]] == [
        "article-arm::1",
        "article-arm::2",
        "article-arm::3",
    ]
    assert article_arm_id_for_label(
        "Experimental", study_map=study_map
    ) is None
    assert article_arm_id_for_label(
        "ISO-MR", study_map=study_map
    ) == "article-arm::1"


def test_study_map_keeps_existing_arm_ids_across_alias_updates() -> None:
    initial = merge_study_map(
        _empty_map(),
        {
            **_empty_map(),
            "arms": [
                {
                    "label": "Home-based circuit training",
                    "aliases": ["HBCT"],
                    "role": "experimental",
                    "description": "exercise",
                },
                {
                    "label": "Control",
                    "aliases": [],
                    "role": "control",
                    "description": "usual activity",
                },
            ],
        },
    )
    updated = merge_study_map(
        initial,
        {
            **_empty_map(),
            "arms": [
                {
                    "label": "HBCT",
                    "aliases": ["exercise group"],
                    "role": "experimental",
                    "description": "exercise",
                },
                {
                    "label": "Education",
                    "aliases": [],
                    "role": "control",
                    "description": "education control",
                },
            ],
        },
    )

    assert [(arm["label"], arm["arm_id"]) for arm in updated["arms"]] == [
        ("Home-based circuit training", "article-arm::1"),
        ("Control", "article-arm::2"),
        ("Education", "article-arm::3"),
    ]
    assert article_arm_id_for_label(
        "exercise group", study_map=updated
    ) == "article-arm::1"


def test_candidate_arms_bind_once_and_bridge_uses_ids_not_role_words() -> None:
    study_map = merge_study_map(
        _empty_map(),
        {
            **_empty_map(),
            "arms": [
                {
                    "label": "Experimental (ISO-MR)",
                    "aliases": ["ISO-MR"],
                    "role": "experimental",
                    "description": None,
                },
                {
                    "label": "Experimental (ISO-SR)",
                    "aliases": ["ISO-SR"],
                    "role": "experimental",
                    "description": None,
                },
            ],
        },
    )
    candidate = {
        "arms": [
            {"label": "Experimental (ISO-MR)"},
            {"label": "Experimental (ISO-SR)"},
        ]
    }

    _bind_candidate_arm_ids([candidate], study_map=study_map)

    assert [arm["article_arm_id"] for arm in candidate["arms"]] == [
        "article-arm::1",
        "article-arm::2",
    ]
    assert _unique_arm(
        candidate=candidate,
        requested_arm_id="article-arm::1",
        requested_label="Experimental (ISO-MR)",
    ) is candidate["arms"][0]
    assert _unique_arm(
        candidate=candidate,
        requested_arm_id="article-arm::2",
        requested_label="Experimental (ISO-SR)",
    ) is candidate["arms"][1]


def test_deterministic_assembly_collects_multiarm_materials_by_id() -> None:
    study_map = merge_study_map(
        _empty_map(),
        {
            **_empty_map(),
            "arms": [
                {
                    "label": "Experimental (ISO-MR)",
                    "aliases": ["ISO-MR"],
                    "role": "experimental",
                    "description": None,
                },
                {
                    "label": "Experimental (ISO-SR)",
                    "aliases": ["ISO-SR"],
                    "role": "experimental",
                    "description": None,
                },
            ],
        },
    )
    candidate = {
        "candidate_id": "candidate-1",
        "data_type": "Continuous",
        "local_setting": {},
        "arms": [
            {
                "label": "Experimental (ISO-MR)",
                "article_arm_id": "article-arm::1",
                "materials": [
                    _material("mr-mean", "mean", 2.4, "2.4 (1.9)", applies_to="mean"),
                    _material(
                        "mr-sd",
                        "standard_deviation",
                        1.9,
                        "2.4 (1.9)",
                        applies_to="mean",
                    ),
                    _material(
                        "mr-n",
                        "result_denominator",
                        30,
                        "ISO-MR n=30",
                        applies_to="mean",
                    ),
                ],
            },
            {
                "label": "Experimental (ISO-SR)",
                "article_arm_id": "article-arm::2",
                "materials": [
                    _material("sr-mean", "mean", 2.4, "2.4 (2.3)", applies_to="mean"),
                    _material(
                        "sr-sd",
                        "standard_deviation",
                        2.3,
                        "2.4 (2.3)",
                        applies_to="mean",
                    ),
                    _material(
                        "sr-n",
                        "result_denominator",
                        30,
                        "ISO-SR n=30",
                        applies_to="mean",
                    ),
                ],
            },
        ],
    }

    arms, _, error = _resolved_arms(
        selected=[candidate],
        arm_refs=[
            {"arm_id": "article-arm::1", "label": "Experimental (ISO-MR)"},
            {"arm_id": "article-arm::2", "label": "Experimental (ISO-SR)"},
        ],
        side="experimental",
        data_type="Continuous",
        bindings=[],
        study_map=study_map,
        cross_table=False,
        support_materials=[],
    )

    assert error is None
    assert arms == [
        {"mean": 2.4, "sd": 1.9, "total": 30.0},
        {"mean": 2.4, "sd": 2.3, "total": 30.0},
    ]


def test_verification_proposal_uses_ids_without_repeating_candidate_objects() -> None:
    caller = _BinaryCaller()
    Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    payload = next(
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_source_verification"
    )
    proposal = payload["proposals"][0]
    assert proposal["selected_candidates"] == [
        {"candidate_id": proposal["selected_candidate_ids"][0]}
    ]
    assert "materials" not in json.dumps(proposal)
    assert payload["candidate_context"][0]["arms"]


def test_complete_provisional_resolution_is_sent_to_raw_source_verification() -> None:
    caller = _ProvisionalBinaryCaller()
    result = Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert result["resolution_records"][0]["status"] == "resolved"
    resolution_payload = next(
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_source_verification"
    )
    assert resolution_payload["proposals"][0]["provisional_for_verification"] is True


@pytest.mark.parametrize(
    "caller_type",
    [_PartialProvisionalBinaryCaller, _ReadyPartialBinaryCaller],
)
def test_partial_provisional_resolution_can_be_reconstructed_from_raw_table(
    caller_type: type[_BinaryCaller],
) -> None:
    caller = caller_type()
    result = Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert result["resolution_records"][0]["status"] == "resolved"
    verification_payload = next(
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_source_verification"
    )
    assert verification_payload["raw_source"]
    assert len({row["source_ref"] for row in verification_payload["raw_source"]}) == 1


def test_invalid_structured_output_retries_exactly_once() -> None:
    caller = _BinaryCaller(invalid_first_census=True)
    result = Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert result["resolution_records"][0]["status"] == "resolved"
    assert caller.census_attempts == 3
    census_payloads = [
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_table_census"
    ]
    assert "repair" not in census_payloads[0]
    assert "previous_response" not in census_payloads[1]["repair"]
    assert census_payloads[1]["repair"]["previous_response_shape"]["type"] == (
        "object"
    )


def test_verification_rejects_arm_id_that_conflicts_with_observed_label() -> None:
    with pytest.raises(MetaAnalysisOutputError) as captured:
        Method(
            config={"model": "fake"},
            llm_caller=_ConflictingArmIdCaller(),
            max_table_workers=1,
        ).run(
            review_id="review-1",
            targets=[_target()],
            study_id="study-1",
            article=_binary_article(),
            plan_hash="plan-hash",
        )

    assert captured.value.stage == "source_workspace_source_verification"
    assert captured.value.attempts == 2


def test_evidence_state_limit_is_a_structured_technical_failure() -> None:
    notebook = {
        "candidates": [{} for _ in range(MAX_CANDIDATES_PER_ARTICLE + 1)],
        "support_materials": [],
    }

    with pytest.raises(MetaAnalysisOutputError) as captured:
        _validate_state_size(notebook, context_id="review-1::study-1")

    assert captured.value.stage == "source_workspace_evidence_state"
    assert captured.value.attempts == 1
    assert captured.value.context_id == "review-1::study-1"


def test_cross_source_outcome_denominator_is_verified_before_assembly() -> None:
    result = Method(
        config={"model": "fake"},
        llm_caller=_UnknownDirectionContinuousCaller(),
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target(data_type="Continuous")],
        study_id="study-1",
        article=_continuous_cross_source_article(),
        plan_hash="plan-hash",
    )

    assert result["resolution_records"][0]["status"] == "resolved"
    assert result["resolution_records"][0]["operation"] == "cross_table_assembly"
    assert result["data_rows"][0]["result_data"] == {
        "experimental_mean": 12.0,
        "experimental_sd": 4.0,
        "experimental_total": 20,
        "control_mean": 15.0,
        "control_sd": 5.0,
        "control_total": 18,
    }
    assert result["data_rows"][0]["continuous_effect_alignment"][
        "clinical_direction_status"
    ] == "unknown"
    section_spans = [
        span
        for span in result["data_rows"][0]["source_spans"]
        if span.get("source_id") == "study-1::section::0000"
    ]
    assert {span["text"] for span in section_spans} == {
        "At 12 weeks, pain data were available for all 20 treatment participants",
        "18 placebo participants",
    }
    assert all(span["table_id"] is None for span in section_spans)
    assert all(
        span["section"] == "study-1::section::0000" for span in section_spans
    )


def test_direct_result_contract_uses_reported_uncertainty_not_computed_se() -> None:
    representations = _supported_result_representations(
        _target(data_type="Continuous")
    )
    direct = next(
        row
        for row in representations["alternatives"]
        if row["representation"] == "direct_effect_uncertainty"
    )
    assert direct["required_fields"] == ["direct_effect", "direct_uncertainty"]
    schema = source_verification_schema(
        target_ids=["target-1"],
        candidate_ids=["candidate-1"],
        arm_ids=["article-arm::1", "article-arm::2"],
        source_ref="table-1",
    )
    field_enum = schema["properties"]["source_reviews"]["items"]["properties"][
        "field_evidence"
    ]["items"]["properties"]["field"]["enum"]
    assert "direct_uncertainty" in field_enum
    assert "direct_standard_error" not in field_enum


def test_required_source_verification_excludes_resolver_rejected_candidates() -> None:
    notebook = {
        "candidates": [
            {"candidate_id": "selected", "source_table_id": "table-1"},
            {"candidate_id": "excluded", "source_table_id": "table-1"},
            {"candidate_id": "other-source", "source_table_id": "table-2"},
        ]
    }
    decisions = [
        {
            "candidate_ids": ["selected"],
            "excluded_candidate_ids": ["excluded", "other-source"],
        }
    ]

    assert _source_local_candidate_ids(
        decisions,
        notebook=notebook,
        source_ref="table-1",
    ) == ["selected"]


def test_statistic_policy_limits_continuous_verification_representation() -> None:
    arm_target = _target(data_type="Continuous")
    arm_target["result_selection_policy"] = {
        "statistic_type_priority": [
            "arm mean, standard deviation, analyzed N",
        ]
    }
    direct_target = _target(data_type="Continuous")
    direct_target["result_selection_policy"] = {
        "statistic_type_priority": [
            "direct adjusted mean difference with confidence interval",
        ]
    }

    assert [
        row["representation"]
        for row in _supported_result_representations(arm_target)["alternatives"]
    ] == ["arm_mean_sd_total"]
    assert [
        row["representation"]
        for row in _supported_result_representations(direct_target)["alternatives"]
    ] == ["direct_effect_uncertainty"]


def test_support_material_matching_prefers_article_arm_id_over_generic_label() -> None:
    setting = {
        "outcome_label": "major bleeding",
        "outcome_measure": "participants with major bleeding",
        "timepoint": "postoperative period",
        "population_or_subgroup": "adults",
        "analysis_population": "final analysis",
        "continuous_result_frame": None,
        "change_score_definition": None,
        "unit": "participants",
    }
    materials = [
        {
            "material_id": "n-placebo",
            "kind": "analyzed_total",
            "value": 45,
            "arm_label": "Control",
            "article_arm_id": "article-arm::1",
            "verified_field": "control_total",
            "local_setting": setting,
            "uncertainties": [],
        },
        {
            "material_id": "n-usual-care",
            "kind": "analyzed_total",
            "value": 48,
            "arm_label": "Control",
            "article_arm_id": "article-arm::2",
            "verified_field": "control_total",
            "local_setting": setting,
            "uncertainties": [],
        },
        {
            "material_id": "wrong-side-event",
            "kind": "event_count",
            "value": 3,
            "arm_label": "Control",
            "article_arm_id": "article-arm::2",
            "verified_field": "experimental_events",
            "local_setting": setting,
            "uncertainties": [],
        },
    ]
    selected, index = _compatible_support_materials(
        support_materials=materials,
        arm_id="article-arm::2",
        arm_label="Control",
        side="control",
        candidate_setting=setting,
        study_map={"arms": []},
    )
    assert [row["material_id"] for row in selected] == ["n-usual-care"]
    assert "n-usual-care" in index


def test_best_supported_randomized_denominator_is_kept_with_selection_audit() -> None:
    result = Method(
        config={"model": "fake"},
        llm_caller=_BestSupportedDenominatorCaller(),
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target(data_type="Continuous")],
        study_id="study-1",
        article=_continuous_randomized_denominator_article(),
        plan_hash="plan-hash",
    )

    assert result["data_rows"][0]["result_data"]["experimental_total"] == 20
    assert result["data_rows"][0]["result_data"]["control_total"] == 18
    field_selection = result["data_rows"][0]["derivation"]["input_values"][
        "field_selection"
    ]
    assert field_selection["experimental_total"][0]["basis"] == (
        "supported_inference"
    )
    assert field_selection["control_total"][0]["confidence"] == "medium"
    assert result["data_rows"][0]["derivation"]["method"] == (
        "source_grounded_semantic_verification"
    )
    scope_assessment = result["data_rows"][0]["derivation"]["input_values"][
        "scope_assessment"
    ]
    assert scope_assessment["status"] == "provisional"
    assert "experimental_total" in scope_assessment["provisional_fields"]
    assert (
        result["data_rows"][0]["result_items"][0]["analysis_disposition"]
        == "ready_for_estimate"
    )
    assert result["data_rows"][0]["result_items"][0]["include_in_estimate"] is True


def test_invalid_direct_enrollment_selection_is_repaired_once() -> None:
    caller = _InvalidSelectionThenBestCaller()
    result = Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target(data_type="Continuous")],
        study_id="study-1",
        article=_continuous_randomized_denominator_article(),
        plan_hash="plan-hash",
    )

    assert result["resolution_records"][0]["status"] == "resolved"


def test_table_census_cache_is_keyed_and_reused(tmp_path: Path) -> None:
    first = _BinaryCaller()
    Method(
        config={"model": "fake"},
        llm_caller=first,
        max_table_workers=1,
        cache_dir=tmp_path,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )
    second = _BinaryCaller()
    Method(
        config={"model": "fake"},
        llm_caller=second,
        max_table_workers=1,
        cache_dir=tmp_path,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert [name for name, _ in first.calls].count(
        "meta_source_workspace_table_census"
    ) == 2
    assert [name for name, _ in second.calls].count(
        "meta_source_workspace_table_census"
    ) == 0


def test_raw_table_calls_are_source_isolated_and_adjudication_has_no_raw_tables() -> None:
    caller = _BinaryCaller()
    Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    census_payloads = [
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_table_census"
    ]
    assert len(census_payloads) == 2
    assert all(
        len({source["source_ref"] for source in payload["sources"]}) == 1
        for payload in census_payloads
    )
    source_verification_payloads = [
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_source_verification"
    ]
    assert source_verification_payloads
    assert all(
        len({source["source_ref"] for source in payload["raw_source"]}) == 1
        for payload in source_verification_payloads
    )
    adjudication = next(
        payload
        for name, payload in caller.calls
        if name == "meta_source_workspace_cross_source_adjudication"
    )
    assert adjudication["raw_sources_included"] is False
    assert "raw_source" not in adjudication


def test_generic_role_aliases_are_not_deterministically_collapsed() -> None:
    study_map = _merge_reconciled_study_map(
        _empty_map(),
        {
            **_empty_map(),
            "arms": [
                {
                    "label": "placebo control",
                    "aliases": ["Control"],
                    "role": "control",
                    "description": "matching placebo",
                },
                {
                    "label": "usual-care control",
                    "aliases": ["Control"],
                    "role": "control",
                    "description": "usual care without placebo",
                },
            ],
        },
    )

    assert len(study_map["arms"]) == 2
    assert article_arm_id_for_label("Control", study_map=study_map) is None


def test_failed_table_retry_is_isolated_and_successful_table_cache_survives(
    tmp_path: Path,
) -> None:
    with pytest.raises(MetaAnalysisInvocationError) as captured:
        Method(
            config={"model": "fake"},
            llm_caller=_FailSecondTableCaller(),
            max_table_workers=1,
            cache_dir=tmp_path,
        ).run(
            review_id="review-1",
            targets=[_target()],
            study_id="study-1",
            article=_binary_article(),
            plan_hash="plan-hash",
        )

    assert captured.value.stage == "source_workspace_table_census"
    assert captured.value.attempts == 2
    assert captured.value.failure_code == "provider_timeout"
    second = _BinaryCaller()
    Method(
        config={"model": "fake"},
        llm_caller=second,
        max_table_workers=1,
        cache_dir=tmp_path,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )
    census_sources = [
        payload["sources"][0]["source_ref"]
        for name, payload in second.calls
        if name == "meta_source_workspace_table_census"
    ]
    assert census_sources == ["table-other"]


def test_invalid_table_census_cache_is_discarded_and_refetched(tmp_path: Path) -> None:
    first = _BinaryCaller()
    Method(
        config={"model": "fake"},
        llm_caller=first,
        max_table_workers=1,
        cache_dir=tmp_path,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )
    cache_files = list((tmp_path / "table_census").glob("*.json"))
    assert len(cache_files) == 2
    result_cache = next(
        cache_file
        for cache_file in cache_files
        if json.loads(cache_file.read_text(encoding="utf-8"))["source_observations"][0][
            "source_ref"
        ]
        == "table-result"
    )
    result_cache.write_text(
        json.dumps({"source_observations": []}), encoding="utf-8"
    )

    second = _BinaryCaller()
    Method(
        config={"model": "fake"},
        llm_caller=second,
        max_table_workers=1,
        cache_dir=tmp_path,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert [name for name, _ in second.calls].count(
        "meta_source_workspace_table_census"
    ) == 1


def test_investigation_fetch_is_consumed_before_final_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = _ReadThenFinishCaller()
    monkeypatch.setenv("META_STUDY_EVIDENCE_DEBUG_DIR", str(tmp_path))

    result = Method(
        config={"model": "fake"},
        llm_caller=caller,
        max_table_workers=1,
    ).run(
        review_id="review-1",
        targets=[_target()],
        study_id="study-1",
        article=_binary_article(),
        plan_hash="plan-hash",
    )

    assert caller.investigation_calls == 2
    assert result["coverage"]["investigation_status"] == "finished"
    action_path = next(tmp_path.rglob("investigation_01_action_state.json"))
    action = json.loads(action_path.read_text(encoding="utf-8"))["transition"]
    assert action["action_status"] == "executed"
    assert action["returned_source_refs"] == ["study-1::section::0000"]


def test_ready_resolution_survives_unfinished_article_investigation() -> None:
    workspace = SourceWorkspace.from_article(
        study_id="study-1", article=_binary_article()
    )
    notebook = empty_notebook(workspace=workspace)
    notebook["study_map"]["arms"] = [
        {
            "arm_id": "arm-treatment",
            "label": "treatment",
            "aliases": ["active treatment"],
            "role": "experimental",
        },
        {
            "arm_id": "arm-placebo",
            "label": "placebo",
            "aliases": [],
            "role": "control",
        },
    ]
    notebook["candidates"] = [
        {
            "candidate_id": "candidate-1",
            "source_table_id": "table-result",
            "arms": [],
        }
    ]

    decisions = normalize_resolution_response(
        {
            "decisions": [
                {
                    "target_id": "target-1",
                    "status": "ready",
                    "candidate_ids": ["candidate-1"],
                    "experimental_arm_ids": ["arm-treatment"],
                    "control_arm_ids": ["arm-placebo"],
                    "field_evidence": [],
                    "alternative_material_ids": [],
                    "context_source_refs": [],
                    "excluded_candidate_ids": [],
                    "assumptions": [],
                    "reason": "The candidate is compatible but needs raw verification.",
                }
            ]
        },
        targets=[_target()],
        notebook=notebook,
        table_coverage_complete=True,
        investigation_status="budget_exhausted",
    )

    assert decisions[0]["status"] == "ready"
    assert decisions[0]["provisional_for_verification"] is True
    assert decisions[0]["coverage_basis"] == {
        "table_coverage_complete": True,
        "investigation_status": "budget_exhausted",
    }


def test_alternative_material_source_is_not_a_required_dependency() -> None:
    workspace = SourceWorkspace.from_article(
        study_id="study-1", article=_binary_article()
    )
    notebook = empty_notebook(workspace=workspace)
    notebook["candidates"] = [
        {
            "candidate_id": "candidate-1",
            "source_table_id": "table-result",
            "arms": [],
        }
    ]
    notebook["support_materials"] = [
        {
            "material_id": "material-alternative",
            "source_ref": "table-other",
        }
    ]
    decision = {
        "candidate_ids": ["candidate-1"],
        "field_evidence": [],
        "alternative_material_ids": ["material-alternative"],
        "context_source_refs": [],
    }

    assert decision_required_source_refs(
        decision, notebook=notebook
    ) == ["table-result"]
    assert decision_optional_source_refs(
        decision, notebook=notebook
    ) == ["table-other"]


def test_search_result_limit_is_not_a_context_window_overflow() -> None:
    article = _binary_article()
    article["xml_content"]["sections"].append(
        {
            "section_id": "results",
            "title": "Results",
            "text": "Randomized participants completed the 12 week assessment.",
        }
    )
    workspace = SourceWorkspace.from_article(study_id="study-1", article=article)

    payloads = workspace.search_sections(["randomized"], max_results=1)

    assert payloads[0]["transport_limit_reasons"] == ["search_result_limited"]
    assert payloads[0]["context_budget_exceeded"] is True
    assert _payloads_mark_actual_context_limited(payloads) is False


def test_incomplete_coverage_cannot_become_data_unavailable() -> None:
    workspace = SourceWorkspace.from_article(
        study_id="study-1", article=_binary_article()
    )
    notebook = empty_notebook(workspace=workspace)
    decisions = normalize_resolution_response(
        {
            "decisions": [
                {
                    "target_id": "target-1",
                    "status": "data_unavailable",
                    "candidate_ids": [],
                    "experimental_arm_labels": [],
                    "control_arm_labels": [],
                    "field_evidence": [],
                    "alternative_material_ids": [],
                    "excluded_candidate_ids": [],
                    "assumptions": [],
                    "reason": "No result was identified.",
                }
            ]
        },
        targets=[_target()],
        notebook=notebook,
        coverage_complete=False,
    )

    assert decisions[0]["status"] == "unresolved"
    assert "coverage is incomplete" in decisions[0]["reason"]


def test_unfinished_investigation_cannot_establish_data_unavailable() -> None:
    workspace = SourceWorkspace.from_article(
        study_id="study-1", article=_binary_article()
    )
    notebook = empty_notebook(workspace=workspace)
    decisions = normalize_resolution_response(
        {
            "decisions": [
                {
                    "target_id": "target-1",
                    "status": "data_unavailable",
                    "candidate_ids": [],
                    "experimental_arm_labels": [],
                    "control_arm_labels": [],
                    "field_evidence": [],
                    "alternative_material_ids": [],
                    "excluded_candidate_ids": [],
                    "assumptions": [],
                    "reason": "No compatible table candidate was identified.",
                }
            ]
        },
        targets=[_target()],
        notebook=notebook,
        table_coverage_complete=True,
        investigation_status="budget_exhausted",
    )

    assert decisions[0]["status"] == "unresolved"
    assert "investigation did not finish" in decisions[0]["reason"]


def test_table_window_budget_rotates_across_sources_without_cutting_windows() -> None:
    windows = [
        SourceWindow(
            source_ref=source_ref,
            source_kind="table",
            source_hash=f"hash-{source_ref}",
            title="",
            start=index * 10,
            end=(index + 1) * 10,
            content=f"{source_ref}-window-{index}",
            complete_source=False,
            window_index=index,
            window_count=3,
        )
        for source_ref in ("table-1", "table-2")
        for index in range(3)
    ]

    selected, partial_source_refs = _bounded_table_windows(
        windows,
        max_windows=4,
    )

    assert [
        (row.source_ref, row.window_index, row.content) for row in selected
    ] == [
        ("table-1", 0, "table-1-window-0"),
        ("table-1", 1, "table-1-window-1"),
        ("table-2", 0, "table-2-window-0"),
        ("table-2", 1, "table-2-window-1"),
    ]
    assert partial_source_refs == ["table-1", "table-2"]


def test_partial_table_window_coverage_is_explicit_and_incomplete() -> None:
    workspace = SourceWorkspace.from_article(
        study_id="study-1",
        article=_binary_article(),
    )
    coverage = _coverage(
        study_id="study-1",
        targets=[_target()],
        workspace=workspace,
        notebook=empty_notebook(workspace=workspace),
        status="incomplete_source_coverage",
        omitted_table_refs=[],
        partial_table_refs=["table-result"],
        empty_table_refs=[],
        investigation_finished=True,
    )

    assert coverage["status"] == "incomplete_source_coverage"
    assert coverage["partial_table_ids"] == ["table-result"]
    assert "table_window_cap_exceeded" in coverage["warnings"]
    assert coverage["table_coverage_policy"] == (
        "bounded_raw_table_windows_seen_by_table_census"
    )


def test_source_workspace_production_factory_builds_current_adapter() -> None:
    method = build_production_study_evidence_agent(
        config={"model": "fake"}
    )
    assert method.__class__.__module__.endswith("source_workspace_agent.method")
    assert callable(method.run)


def test_direct_effect_ci_is_converted_to_se_deterministically() -> None:
    standard_error, trace, error = _direct_standard_error(
        effect=-0.77,
        material={
            "kind": "confidence_interval",
            "lower": -1.20,
            "upper": -0.34,
            "confidence_level": 95.0,
        },
    )

    assert error is None
    assert standard_error == pytest.approx(0.21939179)
    assert trace["method"] == "ci_to_se"


def test_direct_effect_ci_accepts_fractional_confidence_level() -> None:
    standard_error, trace, error = _direct_standard_error(
        effect=-0.77,
        material={
            "kind": "confidence_interval",
            "lower": -1.20,
            "upper": -0.34,
            "confidence_level": 0.95,
        },
    )

    assert error is None
    assert standard_error == pytest.approx(0.21939179)
    assert trace["reported_confidence_level"] == 0.95
    assert trace["confidence_level_percent"] == 95.0


def test_direct_effect_ci_rejects_effect_outside_interval() -> None:
    _, _, error = _direct_standard_error(
        effect=2.0,
        material={
            "kind": "confidence_interval",
            "lower": -1.0,
            "upper": 1.0,
            "confidence_level": 95.0,
        },
    )

    assert error == "Direct effect is incompatible with its confidence interval."


def test_cross_source_direction_adjudication_resolves_ambiguous_direct_effect() -> None:
    semantics = _normalize_direct_effect_semantics(
        {
            "comparison_direction": "control_minus_experimental",
            "change_score_direction": "post_minus_baseline",
            "basis": "cross_source_inference",
            "confidence": "high",
            "rationale": (
                "The article identifies sertraline as experimental and placebo as "
                "control; the same result is interpreted as favoring sertraline."
            ),
        },
        data_type="Continuous",
        status="confirmed",
        field_names={"direct_effect", "direct_uncertainty"},
        verified_fields=[
            {
                "field": "direct_effect",
                "evidence_scope": {
                    "result_frame": "change_from_baseline",
                },
            },
            {
                "field": "direct_uncertainty",
                "evidence_scope": {
                    "result_frame": "change_from_baseline",
                },
            },
        ],
    )

    assert semantics["basis"] == "cross_source_inference"
    assert semantics["comparison_direction"] == "control_minus_experimental"


def test_confirmed_direct_effect_cannot_leave_direction_unresolved() -> None:
    with pytest.raises(ValueError, match="resolved comparison direction"):
        _normalize_direct_effect_semantics(
            {
                "comparison_direction": "unclear",
                "change_score_direction": "post_minus_baseline",
                "basis": "cross_source_inference",
                "confidence": "medium",
                "rationale": "The source does not state the subtraction order.",
            },
            data_type="Continuous",
            status="confirmed",
            field_names={"direct_effect", "direct_uncertainty"},
            verified_fields=[
                {
                    "field": "direct_effect",
                    "evidence_scope": {"result_frame": "post_intervention"},
                },
                {
                    "field": "direct_uncertainty",
                    "evidence_scope": {"result_frame": "post_intervention"},
                },
            ],
        )


def test_unresolved_direct_effect_preserves_direction_uncertainty_without_fields() -> None:
    semantics = _normalize_direct_effect_semantics(
        {
            "comparison_direction": "unclear",
            "change_score_direction": "unclear",
            "basis": "insufficient_information",
            "confidence": "low",
            "rationale": "The source reports an unordered contrast without a subtraction order.",
        },
        data_type="Continuous",
        status="unresolved",
        field_names=set(),
        verified_fields=[],
    )

    assert semantics["comparison_direction"] == "unclear"
    assert semantics["basis"] == "insufficient_information"


def test_direct_effect_bridge_applies_adjudicated_direction_deterministically() -> None:
    target = _target(data_type="Continuous")
    study_map = {
        **_empty_map(),
        "arms": [
            {"arm_id": "arm-exp", "label": "sertraline", "role": "experimental"},
            {"arm_id": "arm-ctl", "label": "placebo", "role": "control"},
        ],
    }
    selected = {
        "candidate-1": {
            "candidate_id": "candidate-1",
            "data_type": "Continuous",
            "local_setting": {
                "outcome_label": "PMTS",
                "outcome_measure": "PMTS",
                "continuous_result_frame": "change_from_baseline",
                "scale_direction": "higher_is_worse",
            },
            "arms": [],
        }
    }
    verified_fields = [
        {
            "field": "direct_effect",
            "material": {
                "material_id": "m-effect",
                "kind": "direct_effect",
                "value": 1.88,
                "source_quote": "estimated mean group difference ... 1.88",
            },
            "evidence_scope": {
                "comparison_direction": "unclear",
                "change_score_direction": "unclear",
                "result_frame": "change_from_baseline",
            },
        },
        {
            "field": "direct_uncertainty",
            "material": {
                "material_id": "m-ci",
                "kind": "confidence_interval",
                "lower": 0.01,
                "upper": 3.75,
                "confidence_level": 95.0,
                "source_quote": "95% CI 0.01 to 3.75",
            },
            "evidence_scope": {
                "comparison_direction": "unclear",
                "change_score_direction": "unclear",
                "result_frame": "change_from_baseline",
            },
        },
    ]
    resolution = {
        "experimental_arm_ids": ["arm-exp"],
        "control_arm_ids": ["arm-ctl"],
        "experimental_arm_labels": ["sertraline"],
        "control_arm_labels": ["placebo"],
    }

    row, error = _assemble_direct_effect(
        study_id="giv",
        study_year="2015",
        target=target,
        study_map=study_map,
        resolution=resolution,
        selected=selected,
        verified_fields=verified_fields,
        direct_effect_semantics={
            "comparison_direction": "control_minus_experimental",
            "change_score_direction": "post_minus_baseline",
            "basis": "cross_source_inference",
            "confidence": "high",
            "rationale": "The article's arm identity and interpretation establish the working orientation.",
        },
    )

    assert error is None
    assert row is not None
    assert row["result_data"]["effect_value"] == pytest.approx(-1.88)
    assert row["continuous_effect_alignment"]["effect_multiplier"] == -1
    assert row["derivation"]["input_values"]["comparison_direction_multiplier"] == -1


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "LLM response contained no complete text; finish_reason=None",
            "provider_incomplete_response",
        ),
        ("Expecting value: line 1 column 1 (char 0) JSON decode", "invalid_model_json"),
        ("Unknown source id(s): ['Tab1']", "model_output_source_scope_violation"),
        (
            "Evidence-scope footnote is not present in source T5",
            "model_output_footnote_provenance_invalid",
        ),
        ("Verified direct fields are duplicated", "invalid_model_output"),
    ],
)
def test_output_failure_categories_preserve_real_failure_boundary(
    message: str,
    expected: str,
) -> None:
    assert _output_failure_code(ValueError(message)) == expected
