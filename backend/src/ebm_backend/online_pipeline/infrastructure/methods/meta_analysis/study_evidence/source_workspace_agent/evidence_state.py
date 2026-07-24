"""Evidence-state normalization and source-grounding rules.

The LLM supplies semantic observations.  This module owns stable identifiers,
source checks, state replacement, result-blind projections, and strict decision
contracts.  It intentionally performs no table parsing.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any, Iterable

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent import (
    method as stable_core,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent.calculators import (
    solve_arm,
)

from .schemas import (
    CHANGE_SCORE_DIRECTIONS,
    DENOMINATOR_SCOPES,
    DIRECTION_BASES,
    DIRECTION_CONFIDENCES,
    DIRECT_FIELDS,
    FINAL_FIELDS,
    RESULT_FRAMES,
    SELECTION_BASES,
    SELECTION_CONFIDENCES,
    SCOPE_STATUSES,
)
from .source_workspace import SourceWorkspace
from .working_state import (
    active_evidence_needs,
    apply_evidence_need_updates,
    normalize_evidence_need_updates,
    register_evidence_needs,
    working_state_snapshot,
)


REQUIRED_FINAL_FIELDS = {
    "Dichotomous": {
        "experimental_events",
        "experimental_total",
        "control_events",
        "control_total",
    },
    "Continuous": {
        "experimental_mean",
        "experimental_sd",
        "experimental_total",
        "control_mean",
        "control_sd",
        "control_total",
    },
}

FINAL_FIELD_SETS = {
    "Dichotomous": [REQUIRED_FINAL_FIELDS["Dichotomous"]],
    "Continuous": [
        REQUIRED_FINAL_FIELDS["Continuous"],
        {"direct_effect", "direct_uncertainty"},
        {
            "direct_effect",
            "direct_uncertainty",
            "experimental_total",
            "control_total",
        },
    ],
}

FIELD_KINDS = {
    "experimental_events": {"event_count", "non_event_count", "percentage"},
    "control_events": {"event_count", "non_event_count", "percentage"},
    "experimental_total": {
        "analyzed_total",
        "result_denominator",
        "outcome_complete_count",
        "randomized_total",
        "baseline_total",
    },
    "control_total": {
        "analyzed_total",
        "result_denominator",
        "outcome_complete_count",
        "randomized_total",
        "baseline_total",
    },
    "experimental_mean": {"mean"},
    "control_mean": {"mean"},
    "experimental_sd": {
        "standard_deviation",
        "variance",
        "standard_error",
        "confidence_interval",
    },
    "control_sd": {
        "standard_deviation",
        "variance",
        "standard_error",
        "confidence_interval",
    },
    "direct_effect": {"effect_estimate"},
    "direct_uncertainty": {"standard_error", "confidence_interval"},
}

# A verifier may select these reported materials, but the material is not a
# direct report of the final field.  The semantic conversion/scope inference
# must therefore be explicit and auditable.
NON_DIRECT_FINAL_FIELD_KINDS = {
    "non_event_count",
    "percentage",
    "randomized_total",
    "baseline_total",
    "variance",
    "standard_error",
    "confidence_interval",
}


def empty_notebook(*, workspace: SourceWorkspace) -> dict[str, Any]:
    return {
        "study_map": empty_study_map(),
        "source_study_maps": [],
        "investigator_study_map": empty_study_map(),
        "arm_identity": {"observations": [], "canonical_arms": [], "unresolved": []},
        "candidates": [],
        "support_materials": [],
        "claims": [],
        "alternatives": [],
        "open_questions": [],
        "evidence_needs": [],
        "evidence_need_registry": [],
        "coverage": {
            "read_table_windows": [],
            "read_table_ids": [],
            "read_section_refs": [],
            "section_searches": [],
            "investigation_status": "not_started",
            "investigation_rounds_completed": 0,
            "investigation_pending_action": None,
            "scope_audit_target_ids": [],
            "scope_context_incomplete_target_ids": [],
            "scope_audit_reasons": {},
        },
        "warnings": list(workspace.warnings),
    }


def normalize_census_response(
    value: dict[str, Any],
    *,
    workspace: SourceWorkspace,
    source_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(
        value.get("source_observations"), list
    ):
        raise ValueError("Table census must return source_observations")
    latest_content = _payload_content(source_payloads)
    latest_windows = _payload_windows(source_payloads)
    expected = list(latest_content)
    by_ref: dict[str, dict[str, Any]] = {}
    for raw in value["source_observations"]:
        if not isinstance(raw, dict):
            raise ValueError("Every table census observation must be an object")
        source_ref = str(raw.get("source_ref") or "")
        if source_ref not in latest_content or source_ref in by_ref:
            raise ValueError(f"Invalid or duplicate census source ref: {source_ref}")
        source_status = str(raw.get("source_status") or "")
        if source_status not in {
            "target_relevant",
            "support_only",
            "no_target_evidence",
            "uncertain",
        }:
            raise ValueError(f"Unsupported census source status: {source_status}")
        candidates = [
            normalize_candidate(
                candidate,
                workspace=workspace,
                latest_content=latest_content,
                latest_windows=latest_windows,
                allowed_table_refs={source_ref},
            )
            for candidate in _object_list(raw.get("candidate_blocks"))
        ]
        support = [
            normalize_support_material(
                material,
                workspace=workspace,
                latest_content=latest_content,
                latest_windows=latest_windows,
                allowed_source_refs={source_ref},
            )
            for material in _object_list(raw.get("support_materials"))
        ]
        by_ref[source_ref] = {
            "source_ref": source_ref,
            "source_status": source_status,
            "summary": str(raw.get("summary") or "").strip(),
            "candidates": candidates,
            "support_materials": support,
            "study_map_update": normalize_study_map(
                raw.get("study_map_update"),
                # A census observation still owns candidates from exactly one
                # table.  Study-level facts, however, may legitimately cite a
                # different table supplied in this same raw bundle (for
                # example, Table 3 supplies an outcome while Table 1 defines
                # the randomized arms).  Those references remain bounded to
                # the current provider payload and cannot become candidate
                # evidence by this allowance.
                valid_refs=set(latest_content),
                source_windows_by_ref=latest_windows,
            ),
            "evidence_needs": unique_text(raw.get("evidence_needs")),
        }
    if set(by_ref) != set(expected):
        missing = [source_ref for source_ref in expected if source_ref not in by_ref]
        raise ValueError(f"Table census omitted supplied source refs: {missing}")
    return [by_ref[source_ref] for source_ref in expected]


def merge_census_observations(
    notebook: dict[str, Any],
    *,
    observations: list[dict[str, Any]],
    window_keys: list[str],
) -> None:
    for observation in observations:
        _merge_candidates(notebook, observation["candidates"])
        _merge_support(notebook, observation["support_materials"])
        notebook["source_study_maps"] = unique_dicts(
            [
                *notebook.get("source_study_maps", []),
                {
                    "source_ref": observation["source_ref"],
                    "study_map": deepcopy(observation["study_map_update"]),
                    "candidate_arm_labels": unique_text(
                        arm.get("label")
                        for candidate in observation["candidates"]
                        for arm in candidate.get("arms") or []
                    ),
                },
            ]
        )
        non_arm_update = {
            **observation["study_map_update"],
            # Table-local arm observations remain source-qualified until the
            # article investigator performs semantic reconciliation.  Merging
            # them here by normalized labels would incorrectly collapse generic
            # words such as "control" across distinct real arms.
            "arms": [],
        }
        notebook["study_map"] = merge_study_map(
            notebook["study_map"], non_arm_update
        )
        register_evidence_needs(
            notebook,
            needs=observation["evidence_needs"],
            source_ref=str(observation["source_ref"]),
        )
    notebook["coverage"]["read_table_windows"] = unique_text(
        [*notebook["coverage"]["read_table_windows"], *window_keys]
    )
    notebook["coverage"]["read_table_ids"] = unique_text(
        [
            *notebook["coverage"]["read_table_ids"],
            *[row["source_ref"] for row in observations],
        ]
    )


def normalize_investigator_response(
    value: dict[str, Any],
    *,
    workspace: SourceWorkspace,
    notebook: dict[str, Any],
    latest_source_payloads: list[dict[str, Any]],
    allowed_actions: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Investigator response must be an object")
    action = str(value.get("action") or "")
    valid_actions = allowed_actions or {"finish", "search_sections", "read_sources"}
    if action not in valid_actions:
        raise ValueError(f"Unsupported investigator action: {action}")
    queries = unique_text(value.get("queries"))
    source_refs = unique_text(value.get("source_refs"))
    valid_refs = set(workspace.table_refs) | set(workspace.section_refs)
    invalid_refs = [source_ref for source_ref in source_refs if source_ref not in valid_refs]
    if invalid_refs:
        raise ValueError(f"Investigator requested unknown source refs: {invalid_refs}")
    if action == "search_sections" and not queries:
        raise ValueError("search_sections requires at least one query")
    if action == "read_sources" and not source_refs:
        raise ValueError("read_sources requires at least one source ref")
    if action == "finish":
        queries = []
        source_refs = []

    latest_content = _payload_content(latest_source_payloads)
    latest_windows = _payload_windows(latest_source_payloads)
    known_candidate_refs = {
        str(row.get("source_table_id") or "")
        for row in notebook.get("candidates") or []
    }
    known_material_refs = {
        str(row.get("source_ref") or row.get("source_table_id") or "")
        for row in material_index(notebook).values()
    }
    known_refs = {
        ref for ref in [*known_candidate_refs, *known_material_refs] if ref
    }
    semantic_valid_refs = set(latest_content) | known_refs | set(workspace.section_refs)
    need_update_refs = set(latest_content) | known_refs
    ignored_refs: list[str] = []
    rejected_evidence: list[str] = []
    candidate_blocks = _object_list(value.get("candidate_blocks"))
    support_blocks = _object_list(value.get("support_materials"))
    if (candidate_blocks or support_blocks) and not latest_content:
        raise ValueError("New evidence requires a raw source bundle on this turn")
    candidates: list[dict[str, Any]] = []
    for raw in candidate_blocks:
        source_ref = str(raw.get("source_table_id") or "")
        if source_ref not in latest_content:
            if source_ref in known_candidate_refs:
                ignored_refs.append(source_ref)
                continue
            raise ValueError(
                "A new investigator candidate must come from a current raw table "
                f"window: {source_ref}"
            )
        try:
            candidates.append(
                normalize_candidate(
                    raw,
                    workspace=workspace,
                    latest_content=latest_content,
                    latest_windows=latest_windows,
                    allowed_table_refs=set(latest_content) & set(workspace.table_refs),
                )
            )
        except ValueError as exc:
            rejected_evidence.append(f"candidate:{source_ref}:{exc}")
    support: list[dict[str, Any]] = []
    for raw in support_blocks:
        source_ref = str(raw.get("source_ref") or "")
        if source_ref not in latest_content:
            if source_ref in known_material_refs:
                ignored_refs.append(source_ref)
                continue
            raise ValueError(
                "New investigator support must come from a current raw source "
                f"window: {source_ref}"
            )
        try:
            support.append(
                normalize_support_material(
                    raw,
                    workspace=workspace,
                    latest_content=latest_content,
                    latest_windows=latest_windows,
                    allowed_source_refs=set(latest_content),
                )
            )
        except ValueError as exc:
            rejected_evidence.append(f"support:{source_ref}:{exc}")
    claims = _normalize_claims(
        value.get("claims"), allowed_refs=semantic_valid_refs
    )
    alternatives = _normalize_alternatives(
        value.get("alternatives"), allowed_refs=semantic_valid_refs
    )
    evidence_need_updates = normalize_evidence_need_updates(
        value.get("evidence_need_updates"),
        known_need_ids={
            str(row.get("need_id") or "")
            for row in active_evidence_needs(notebook)
        },
        allowed_source_refs=need_update_refs,
    )
    study_map_update = normalize_study_map(
        value.get("study_map_update"),
        valid_refs=semantic_valid_refs,
        source_windows_by_ref=latest_windows,
    )
    reason = str(value.get("reason") or "").strip()
    if not reason:
        raise ValueError("Investigator action requires a reason")
    return {
        "action": action,
        "queries": queries,
        "source_refs": source_refs,
        "candidates": candidates,
        "support_materials": support,
        "study_map_update": study_map_update,
        "claims": claims,
        "alternatives": alternatives,
        "open_questions": unique_text(value.get("open_questions")),
        "evidence_need_updates": evidence_need_updates,
        "reason": reason,
        "ignored_existing_source_refs": unique_text(ignored_refs),
        "rejected_evidence": unique_text(rejected_evidence),
    }


def merge_investigator_update(
    notebook: dict[str, Any],
    *,
    update: dict[str, Any],
) -> None:
    notebook["investigator_study_map"] = deepcopy(update["study_map_update"])
    notebook["study_map"] = merge_study_map(
        notebook["study_map"], {**update["study_map_update"], "arms": []}
    )
    _merge_candidates(notebook, update["candidates"])
    _merge_support(notebook, update["support_materials"])
    notebook["claims"] = unique_dicts([*notebook["claims"], *update["claims"]])
    notebook["alternatives"] = unique_dicts(
        [*notebook["alternatives"], *update["alternatives"]]
    )
    notebook["open_questions"] = list(update["open_questions"])
    apply_evidence_need_updates(
        notebook,
        updates=list(update.get("evidence_need_updates") or []),
    )
    notebook["warnings"] = unique_text(
        [
            *notebook["warnings"],
            *[
                f"investigator_reused_existing_source:{source_ref}"
                for source_ref in update.get("ignored_existing_source_refs") or []
            ],
            *[
                f"investigator_rejected_evidence:{item}"
                for item in update.get("rejected_evidence") or []
            ],
        ]
    )


def _resolution_proposal_error(
    *,
    target: dict[str, Any],
    selected: list[str],
    field_evidence: list[dict[str, Any]],
    alternatives: list[str],
    material_by_id: dict[str, dict[str, Any]],
) -> str | None:
    """Validate only the structure needed to send a proposal to verification.

    This is deliberately not a semantic denominator rule.  It checks that a
    resolver supplied a source-locatable, type-compatible proposal; the
    verifier is responsible for completing it and deciding which source
    interpretation is best supported.
    """

    if str(target.get("data_type") or "") not in REQUIRED_FINAL_FIELDS:
        return "unsupported target data type"
    if not selected:
        return "at least one candidate is required"
    selected_materials = {
        material_id
        for row in field_evidence
        for material_id in row["material_ids"]
    }
    if selected_materials & set(alternatives):
        return "selected and alternative materials overlap"
    for field_row in field_evidence:
        field = field_row["field"]
        for material_id in field_row["material_ids"]:
            material = material_by_id[material_id]
            if str(material.get("kind") or "") not in FIELD_KINDS[field]:
                return f"material {material_id} cannot support {field}"
            owner = optional_text(material.get("candidate_id"))
            if owner and owner not in selected:
                return f"material {material_id} belongs to an unselected candidate"
    return None


def _resolution_proposal_complete(
    *,
    target: dict[str, Any],
    selected: list[str],
    experimental: list[str],
    control: list[str],
    field_evidence: list[dict[str, Any]],
) -> bool:
    fields = [str(row.get("field") or "") for row in field_evidence]
    required = _matching_final_field_set(
        data_type=str(target.get("data_type") or ""),
        fields=set(fields),
    )
    return bool(
        required is not None
        and selected
        and experimental
        and control
        and len(fields) == len(required)
        and set(fields) == required
    )


def normalize_resolution_response(
    value: dict[str, Any],
    *,
    targets: list[dict[str, Any]],
    notebook: dict[str, Any],
    table_coverage_complete: bool | None = None,
    investigation_status: str = "finished",
    coverage_complete: bool | None = None,
) -> list[dict[str, Any]]:
    # `coverage_complete` is retained for direct callers of the earlier
    # contract.  Runtime orchestration passes the two independent states.
    if table_coverage_complete is None:
        table_coverage_complete = bool(coverage_complete)
    if investigation_status not in {
        "finished",
        "budget_exhausted",
        "provider_failed",
    }:
        raise ValueError(f"Unsupported investigation status: {investigation_status}")
    rows = value.get("decisions") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Resolution must return decisions")
    target_ids = [str(row["target_id"]) for row in targets]
    target_by_id = {str(row["target_id"]): row for row in targets}
    candidate_ids = {str(row["candidate_id"]) for row in notebook["candidates"]}
    material_by_id = material_index(notebook)
    available_source_refs = _available_source_refs(notebook)
    valid_arm_ids = set(article_arm_ids(notebook["study_map"]))
    by_target: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("Every resolution decision must be an object")
        target_id = str(raw.get("target_id") or "")
        if target_id not in target_by_id or target_id in by_target:
            raise ValueError(f"Invalid or duplicate target resolution: {target_id}")
        status = str(raw.get("status") or "")
        if status not in {
            "ready",
            "data_unavailable",
            "unresolved",
            "unsupported_dependency",
        }:
            raise ValueError(f"Unsupported resolution status: {status}")
        selected = validated_ids(raw.get("candidate_ids"), candidate_ids, "candidate")
        excluded = validated_ids(
            raw.get("excluded_candidate_ids"), candidate_ids, "excluded candidate"
        )
        field_evidence = _normalize_field_evidence(
            raw.get("field_evidence"),
            material_by_id=material_by_id,
        )
        alternatives = validated_ids(
            raw.get("alternative_material_ids"),
            set(material_by_id),
            "alternative material",
        )
        context_source_refs = validated_ids(
            raw.get("context_source_refs"),
            available_source_refs,
            "context source",
        )
        experimental_ids = _selected_arm_ids(
            raw.get("experimental_arm_ids"),
            legacy_labels=raw.get("experimental_arm_labels"),
            valid_arm_ids=valid_arm_ids,
            study_map=notebook["study_map"],
        )
        control_ids = _selected_arm_ids(
            raw.get("control_arm_ids"),
            legacy_labels=raw.get("control_arm_labels"),
            valid_arm_ids=valid_arm_ids,
            study_map=notebook["study_map"],
        )
        experimental = [
            article_arm_label(arm_id=arm_id, study_map=notebook["study_map"])
            for arm_id in experimental_ids
        ]
        control = [
            article_arm_label(arm_id=arm_id, study_map=notebook["study_map"])
            for arm_id in control_ids
        ]
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            raise ValueError("Every target resolution requires a reason")

        proposal_error = _resolution_proposal_error(
            target=target_by_id[target_id],
            selected=selected,
            field_evidence=field_evidence,
            alternatives=alternatives,
            material_by_id=material_by_id,
        )
        proposal_complete = _resolution_proposal_complete(
            target=target_by_id[target_id],
            selected=selected,
            experimental=experimental,
            control=control,
            field_evidence=field_evidence,
        )
        provisional_for_verification = False
        if status == "ready":
            if proposal_error:
                raise ValueError(
                    f"Invalid ready resolution for {target_id}: {proposal_error}"
                )
            provisional_for_verification = bool(
                not proposal_complete
                or not table_coverage_complete
                or investigation_status != "finished"
            )
        elif status == "unresolved" and selected:
            if proposal_error:
                raise ValueError(
                    f"Invalid provisional resolution for {target_id}: {proposal_error}"
                )
            # The result-blind resolver cannot inspect the raw evidence needed to
            # settle source-scope questions or recover a missed field.  A
            # plausible selected candidate is therefore a verification input,
            # not a final unresolved result.  The verifier receives the raw
            # candidate table and may reconstruct a complete contribution.
            status = "ready"
            provisional_for_verification = True
            reason = (
                "A plausible contribution was routed to raw-source verification "
                f"for final evidence selection and field recovery. {reason}"
            )
        elif selected or field_evidence or experimental or control:
            if status in {"data_unavailable", "unsupported_dependency"}:
                raise ValueError(f"{status} cannot select a contribution")
        if status == "data_unavailable" and (
            not table_coverage_complete or investigation_status != "finished"
        ):
            status = "unresolved"
            coverage_reason = (
                "raw-table coverage is incomplete"
                if not table_coverage_complete
                else "article investigation did not finish"
            )
            reason = (
                f"Absence cannot be established because {coverage_reason}. "
                + reason
            )

        by_target[target_id] = {
            "target_id": target_id,
            "status": status,
            "candidate_ids": selected,
            "experimental_arm_ids": experimental_ids,
            "control_arm_ids": control_ids,
            "experimental_arm_labels": experimental,
            "control_arm_labels": control,
            "field_evidence": field_evidence,
            "alternative_material_ids": alternatives,
            "context_source_refs": context_source_refs,
            "excluded_candidate_ids": excluded,
            "assumptions": unique_text(raw.get("assumptions")),
            "provisional_for_verification": provisional_for_verification,
            "coverage_basis": {
                "table_coverage_complete": bool(table_coverage_complete),
                "investigation_status": investigation_status,
            },
            "reason": reason,
        }
    if set(by_target) != set(target_ids):
        missing = [target_id for target_id in target_ids if target_id not in by_target]
        raise ValueError(f"Resolution omitted frozen targets: {missing}")
    return [by_target[target_id] for target_id in target_ids]


def normalize_verification_response(
    value: dict[str, Any],
    *,
    decisions: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    notebook: dict[str, Any],
    workspace: SourceWorkspace,
    source_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = value.get("verdicts") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Verification must return verdicts")
    decision_by_target = {
        str(row["target_id"]): row
        for row in decisions
        if row["status"] == "ready"
    }
    target_by_id = {str(row["target_id"]): row for row in targets}
    candidate_by_id = {
        str(row["candidate_id"]): row for row in notebook["candidates"]
    }
    latest_content = _payload_content(source_payloads)
    latest_windows = _payload_windows(source_payloads)
    by_target: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("Every verification verdict must be an object")
        target_id = str(raw.get("target_id") or "")
        if target_id not in decision_by_target or target_id in by_target:
            raise ValueError(f"Invalid or duplicate verification target: {target_id}")
        status = str(raw.get("status") or "")
        if status not in {"confirmed", "corrected", "unresolved"}:
            raise ValueError(f"Unsupported verification status: {status}")
        selected = validated_ids(
            raw.get("selected_candidate_ids"), set(candidate_by_id), "candidate"
        )
        valid_arm_ids = set(article_arm_ids(notebook["study_map"]))
        experimental_ids = _selected_arm_ids(
            raw.get("experimental_arm_ids"),
            legacy_labels=raw.get("experimental_arm_labels"),
            valid_arm_ids=valid_arm_ids,
            study_map=notebook["study_map"],
        )
        control_ids = _selected_arm_ids(
            raw.get("control_arm_ids"),
            legacy_labels=raw.get("control_arm_labels"),
            valid_arm_ids=valid_arm_ids,
            study_map=notebook["study_map"],
        )
        experimental = [
            article_arm_label(arm_id=arm_id, study_map=notebook["study_map"])
            for arm_id in experimental_ids
        ]
        control = [
            article_arm_label(arm_id=arm_id, study_map=notebook["study_map"])
            for arm_id in control_ids
        ]
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            raise ValueError("Every verification verdict requires a reason")
        assumptions = unique_text(raw.get("assumptions"))
        field_rows = _object_list(raw.get("field_evidence"))
        verified_fields: list[dict[str, Any]] = []
        if status != "unresolved":
            if not selected or not experimental or not control:
                raise ValueError(
                    "A confirmed/corrected verdict requires candidates and arm mappings"
                )
            required = _matching_final_field_set(
                data_type=str(target_by_id[target_id].get("data_type") or ""),
                fields={str(row.get("field") or "") for row in field_rows},
            )
            if required is None:
                raise ValueError(
                    f"Verified fields do not form one supported result representation for {target_id}"
                )
            _validate_verified_field_coverage(
                field_rows=field_rows,
                required_fields=required,
                experimental_arm_ids=experimental_ids,
                control_arm_ids=control_ids,
                study_map=notebook["study_map"],
                target_id=target_id,
            )
            for index, field_raw in enumerate(field_rows):
                field = str(field_raw.get("field") or "")
                source_ref = str(field_raw.get("source_ref") or "")
                if source_ref not in latest_content:
                    raise ValueError(
                        f"Verified field {field} is not grounded in the supplied raw bundle"
                    )
                source_kind = str(field_raw.get("source_kind") or "")
                source = workspace.source(source_ref)
                if source_kind != source.source_kind:
                    raise ValueError("Verified source kind does not match source ref")
                candidate_id = optional_text(field_raw.get("candidate_id"))
                if candidate_id and candidate_id not in selected:
                    raise ValueError(
                        f"Verified field {field} names an unselected candidate"
                    )
                if candidate_id and (
                    source_kind != "table"
                    or str(candidate_by_id[candidate_id]["source_table_id"])
                    != source_ref
                ):
                    raise ValueError(
                        "Candidate-owned verification evidence must remain in that "
                        "candidate's raw table; cross-source evidence is supporting evidence"
                    )
                semantic_candidate_id = candidate_id or (selected[0] if selected else None)
                direct_field = field in DIRECT_FIELDS
                observed_arm_label = str(
                    field_raw.get("observed_arm_label")
                    or field_raw.get("arm_label")
                    or ""
                ).strip()
                arm_id = str(field_raw.get("arm_id") or "").strip()
                if direct_field:
                    # Scope audits may echo one observed label/arm for a
                    # comparison header.  Direct fields are comparison-scoped;
                    # retain the label for audit but never use that arm ID as
                    # field ownership.
                    arm_id = ""
                if not direct_field and not arm_id:
                    arm_id = article_arm_id_for_label(
                        observed_arm_label,
                        study_map=notebook["study_map"],
                    ) or ""
                if not direct_field and arm_id not in valid_arm_ids:
                    raise ValueError(f"Verified field {field} has invalid article arm id")
                observed_arm_id = article_arm_id_for_label(
                    observed_arm_label,
                    study_map=notebook["study_map"],
                )
                if not direct_field and observed_arm_id and observed_arm_id != arm_id:
                    raise ValueError(
                        f"Verified field {field} arm id conflicts with its observed label"
                    )
                evidence_scope = normalize_evidence_scope(
                    field_raw.get("evidence_scope"),
                    field=field,
                    arm_label=observed_arm_label,
                    direct_field=direct_field,
                    study_map=notebook["study_map"],
                    workspace=workspace,
                    source_ref=source_ref,
                    source_kind=source_kind,
                    latest_content_by_ref=latest_content,
                )
                material = normalize_material(
                    field_raw.get("material"),
                    workspace=workspace,
                    source_ref=source_ref,
                    latest_content=latest_content[source_ref],
                    latest_windows=latest_windows[source_ref],
                    arm_label=observed_arm_label,
                    local_setting=(
                        deepcopy(candidate_by_id[semantic_candidate_id]["local_setting"])
                        if semantic_candidate_id
                        else _support_local_setting(field_raw)
                    ),
                    material_key=f"verification-{target_id}-{field}-{index}",
                )
                if str(material.get("kind") or "") not in FIELD_KINDS[field]:
                    raise ValueError(
                        f"Verified material {material['material_id']} cannot support {field}"
                    )
                selection_basis = str(field_raw.get("selection_basis") or "")
                if selection_basis not in SELECTION_BASES:
                    raise ValueError(
                        f"Verified field {field} has invalid selection_basis"
                    )
                selection_confidence = str(
                    field_raw.get("selection_confidence") or ""
                )
                if selection_confidence not in SELECTION_CONFIDENCES:
                    raise ValueError(
                        f"Verified field {field} has invalid selection_confidence"
                    )
                selection_rationale = str(
                    field_raw.get("selection_rationale") or ""
                ).strip()
                if not selection_rationale:
                    raise ValueError(
                        f"Verified field {field} requires selection_rationale"
                    )
                material_kind = str(material.get("kind") or "")
                if (
                    selection_basis == "direct"
                    and material_kind in NON_DIRECT_FINAL_FIELD_KINDS
                    and not (
                        field == "direct_uncertainty"
                        and material_kind == "confidence_interval"
                    )
                ):
                    raise ValueError(
                        f"Verified {material_kind} cannot be direct evidence for {field}"
                    )
                if selection_basis == "assumption" and not assumptions:
                    raise ValueError(
                        "An assumption-based field selection requires an explicit "
                        "verdict assumption"
                    )
                material["candidate_id"] = candidate_id
                material["selection_basis"] = selection_basis
                material["selection_confidence"] = selection_confidence
                material["selection_rationale"] = selection_rationale
                material["evidence_scope"] = deepcopy(evidence_scope)
                verified_fields.append(
                    {
                        "field": field,
                        "candidate_id": candidate_id,
                        "source_ref": source_ref,
                        "source_kind": source_kind,
                        "arm_id": arm_id or None,
                        "arm_label": observed_arm_label,
                        "material": material,
                        "evidence_scope": evidence_scope,
                        "selection_basis": selection_basis,
                        "selection_confidence": selection_confidence,
                        "selection_rationale": selection_rationale,
                    }
                )
        elif field_rows:
            raise ValueError("An unresolved verification cannot select final fields")
        by_target[target_id] = {
            "target_id": target_id,
            "status": status,
            "selected_candidate_ids": selected,
            "experimental_arm_ids": experimental_ids,
            "control_arm_ids": control_ids,
            "experimental_arm_labels": experimental,
            "control_arm_labels": control,
            "verified_fields": verified_fields,
            "competing_interpretations": unique_text(
                raw.get("competing_interpretations")
            ),
            "assumptions": assumptions,
            "reason": reason,
        }
    if set(by_target) != set(decision_by_target):
        missing = [target_id for target_id in decision_by_target if target_id not in by_target]
        raise ValueError(f"Verification omitted ready targets: {missing}")
    return [by_target[target_id] for target_id in decision_by_target]


def normalize_source_verification_response(
    value: dict[str, Any],
    *,
    decisions: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    notebook: dict[str, Any],
    workspace: SourceWorkspace,
    source_payloads: list[dict[str, Any]],
    source_ref: str,
) -> list[dict[str, Any]]:
    """Validate partial evidence reconstructed from exactly one raw source."""

    rows = value.get("source_reviews") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Source verification must return source_reviews")
    if {str(row.get("source_ref") or "") for row in source_payloads} != {source_ref}:
        raise ValueError("Source verification payload must contain exactly one source")
    decision_by_target = {
        str(row["target_id"]): row for row in decisions if row["status"] == "ready"
    }
    target_by_id = {str(row["target_id"]): row for row in targets}
    candidate_by_id = {
        str(row["candidate_id"]): row for row in notebook["candidates"]
    }
    valid_candidate_ids = {
        candidate_id
        for candidate_id, candidate in candidate_by_id.items()
        if str(candidate.get("source_table_id") or "") == source_ref
    }
    latest_content = _payload_content(source_payloads)
    latest_windows = _payload_windows(source_payloads)
    valid_arm_ids = set(article_arm_ids(notebook["study_map"]))
    by_target: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("Every source review must be an object")
        target_id = str(raw.get("target_id") or "")
        if target_id not in decision_by_target or target_id in by_target:
            raise ValueError(f"Invalid or duplicate source-review target: {target_id}")
        source_status = str(raw.get("source_status") or "")
        if source_status not in {
            "evidence_found",
            "no_relevant_evidence",
            "unresolved",
        }:
            raise ValueError(f"Unsupported source-review status: {source_status}")
        selected = validated_ids(
            raw.get("selected_candidate_ids"), valid_candidate_ids, "candidate"
        )
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            raise ValueError("Every source review requires a reason")
        field_rows = _object_list(raw.get("field_evidence"))
        evidence: list[dict[str, Any]] = []
        for index, field_raw in enumerate(field_rows):
            field = str(field_raw.get("field") or "")
            if field not in FINAL_FIELDS:
                raise ValueError(f"Unsupported source-review field: {field}")
            if str(field_raw.get("source_ref") or "") != source_ref:
                raise ValueError("Source-review evidence must remain in its current source")
            source_kind = str(field_raw.get("source_kind") or "")
            source = workspace.source(source_ref)
            if source.source_kind != source_kind:
                raise ValueError("Source-review kind does not match source ref")
            candidate_id = optional_text(field_raw.get("candidate_id"))
            if candidate_id and candidate_id not in selected:
                raise ValueError("Source-review evidence names an unselected candidate")
            observed_arm_label = str(
                field_raw.get("observed_arm_label")
                or field_raw.get("arm_label")
                or ""
            ).strip()
            direct_field = field in DIRECT_FIELDS
            arm_id = str(field_raw.get("arm_id") or "").strip()
            if direct_field:
                arm_id = ""
            elif not arm_id:
                arm_id = article_arm_id_for_label(
                    observed_arm_label, study_map=notebook["study_map"]
                ) or ""
            if not direct_field and arm_id not in valid_arm_ids:
                raise ValueError(f"Source-review field {field} has invalid arm id")
            observed_arm_id = article_arm_id_for_label(
                observed_arm_label, study_map=notebook["study_map"]
            )
            if not direct_field and observed_arm_id and observed_arm_id != arm_id:
                raise ValueError(
                    f"Source-review field {field} arm id conflicts with observed label"
                )
            evidence_scope = normalize_evidence_scope(
                field_raw.get("evidence_scope"),
                field=field,
                arm_label=observed_arm_label,
                direct_field=direct_field,
                study_map=notebook["study_map"],
                workspace=workspace,
                source_ref=source_ref,
                source_kind=source_kind,
                latest_content_by_ref=latest_content,
            )
            semantic_candidates = list(
                decision_by_target[target_id].get("candidate_ids") or []
            )
            semantic_candidate_id = candidate_id or (
                semantic_candidates[0] if len(semantic_candidates) == 1 else None
            )
            material = normalize_material(
                field_raw.get("material"),
                workspace=workspace,
                source_ref=source_ref,
                latest_content=latest_content[source_ref],
                latest_windows=latest_windows[source_ref],
                arm_label=observed_arm_label,
                local_setting=(
                    deepcopy(candidate_by_id[semantic_candidate_id]["local_setting"])
                    if semantic_candidate_id
                    else _support_local_setting(field_raw)
                ),
                material_key=f"source-verification-{target_id}-{field}-{index}",
            )
            if str(material.get("kind") or "") not in FIELD_KINDS[field]:
                raise ValueError(
                    f"Source-review material {material['material_id']} cannot support {field}"
                )
            selection_basis = str(field_raw.get("selection_basis") or "")
            if selection_basis not in SELECTION_BASES:
                raise ValueError(f"Source-review field {field} has invalid selection basis")
            selection_confidence = str(
                field_raw.get("selection_confidence") or ""
            )
            if selection_confidence not in SELECTION_CONFIDENCES:
                raise ValueError(
                    f"Source-review field {field} has invalid selection confidence"
                )
            selection_rationale = str(
                field_raw.get("selection_rationale") or ""
            ).strip()
            if not selection_rationale:
                raise ValueError(
                    f"Source-review field {field} requires selection rationale"
                )
            material_kind = str(material.get("kind") or "")
            if (
                selection_basis == "direct"
                and material_kind in NON_DIRECT_FINAL_FIELD_KINDS
                and not (
                    field == "direct_uncertainty"
                    and material_kind == "confidence_interval"
                )
            ):
                raise ValueError(
                    f"Source-review {material_kind} cannot be direct evidence for {field}"
                )
            material["candidate_id"] = candidate_id
            material["selection_basis"] = selection_basis
            material["selection_confidence"] = selection_confidence
            material["selection_rationale"] = selection_rationale
            material["evidence_scope"] = deepcopy(evidence_scope)
            evidence_key = {
                "target_id": target_id,
                "field": field,
                "candidate_id": candidate_id,
                "source_ref": source_ref,
                "arm_id": arm_id or None,
                "material_id": material.get("material_id"),
            }
            evidence.append(
                {
                    "evidence_id": "verified-evidence::"
                    + sha256(_canonical(evidence_key).encode("utf-8")).hexdigest()[:16],
                    "field": field,
                    "candidate_id": candidate_id,
                    "source_ref": source_ref,
                    "source_kind": source_kind,
                    "arm_id": arm_id or None,
                    "arm_label": observed_arm_label,
                    "material": material,
                    "evidence_scope": evidence_scope,
                    "selection_basis": selection_basis,
                    "selection_confidence": selection_confidence,
                    "selection_rationale": selection_rationale,
                }
            )
        if source_status == "evidence_found" and not evidence:
            raise ValueError("evidence_found source review requires field evidence")
        if source_status != "evidence_found" and evidence:
            raise ValueError(f"{source_status} source review cannot select field evidence")
        by_target[target_id] = {
            "target_id": target_id,
            "source_ref": source_ref,
            "source_status": source_status,
            "selected_candidate_ids": selected,
            "verified_evidence": evidence,
            "competing_interpretations": unique_text(
                raw.get("competing_interpretations")
            ),
            "reason": reason,
        }
    if set(by_target) != set(decision_by_target):
        missing = [target_id for target_id in decision_by_target if target_id not in by_target]
        raise ValueError(f"Source verification omitted ready targets: {missing}")
    return [by_target[target_id] for target_id in decision_by_target]


def normalize_cross_source_adjudication_response(
    value: dict[str, Any],
    *,
    decisions: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    notebook: dict[str, Any],
    source_reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble final verdicts from already-grounded source-local evidence cards."""

    rows = value.get("verdicts") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Cross-source adjudication must return verdicts")
    decision_by_target = {
        str(row["target_id"]): row for row in decisions if row["status"] == "ready"
    }
    target_by_id = {str(row["target_id"]): row for row in targets}
    candidate_ids = {str(row["candidate_id"]) for row in notebook["candidates"]}
    evidence_by_id = {
        str(evidence["evidence_id"]): evidence
        for review in source_reviews
        for evidence in review.get("verified_evidence") or []
    }
    valid_arm_ids = set(article_arm_ids(notebook["study_map"]))
    by_target: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("Every cross-source verdict must be an object")
        target_id = str(raw.get("target_id") or "")
        if target_id not in decision_by_target or target_id in by_target:
            raise ValueError(f"Invalid or duplicate adjudication target: {target_id}")
        status = str(raw.get("status") or "")
        if status not in {"confirmed", "corrected", "unresolved"}:
            raise ValueError(f"Unsupported adjudication status: {status}")
        selected = validated_ids(
            raw.get("selected_candidate_ids"), candidate_ids, "candidate"
        )
        experimental_ids = _selected_arm_ids(
            raw.get("experimental_arm_ids"),
            legacy_labels=None,
            valid_arm_ids=valid_arm_ids,
            study_map=notebook["study_map"],
        )
        control_ids = _selected_arm_ids(
            raw.get("control_arm_ids"),
            legacy_labels=None,
            valid_arm_ids=valid_arm_ids,
            study_map=notebook["study_map"],
        )
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            raise ValueError("Every cross-source verdict requires a reason")
        verified_fields: list[dict[str, Any]] = []
        seen_evidence_ids: set[str] = set()
        field_names: list[str] = []
        for field_row in _object_list(raw.get("field_selections")):
            field = str(field_row.get("field") or "")
            if field not in FINAL_FIELDS:
                raise ValueError(f"Invalid adjudication field: {field}")
            field_names.append(field)
            ids = validated_ids(
                field_row.get("evidence_ids"), set(evidence_by_id), "verified evidence"
            )
            if not ids:
                raise ValueError(f"Adjudication field {field} requires evidence")
            for evidence_id in ids:
                if evidence_id in seen_evidence_ids:
                    raise ValueError("Verified evidence cannot support two final fields")
                seen_evidence_ids.add(evidence_id)
                evidence = evidence_by_id[evidence_id]
                if str(evidence.get("field") or "") != field:
                    raise ValueError(
                        f"Verified evidence {evidence_id} does not support {field}"
                    )
                candidate_id = optional_text(evidence.get("candidate_id"))
                if candidate_id and candidate_id not in selected:
                    raise ValueError(
                        "Adjudication selected evidence from an unselected candidate"
                    )
                verified_fields.append(deepcopy(evidence))
        assumptions = unique_text(raw.get("assumptions"))
        data_type = str(target_by_id[target_id].get("data_type") or "")
        scale_direction = str(raw.get("scale_direction") or "")
        scale_basis = str(raw.get("scale_direction_basis") or "")
        scale_confidence = str(raw.get("scale_direction_confidence") or "")
        scale_rationale = str(raw.get("scale_direction_rationale") or "").strip()
        if data_type == "Continuous":
            if scale_direction not in {
                "higher_is_better",
                "higher_is_worse",
                "unclear",
            }:
                raise ValueError("Continuous adjudication requires scale direction")
            if scale_basis not in {
                "source_reported",
                "expert_inference",
                "insufficient_information",
            }:
                raise ValueError("Continuous adjudication requires scale-direction basis")
            if scale_confidence not in {"high", "medium", "low"}:
                raise ValueError(
                    "Continuous adjudication requires scale-direction confidence"
                )
            if not scale_rationale:
                raise ValueError(
                    "Continuous adjudication requires scale-direction rationale"
                )
            if scale_basis == "insufficient_information" and scale_direction != "unclear":
                raise ValueError(
                    "Insufficient scale information must retain an unclear direction"
                )
            if (
                scale_basis in {"source_reported", "expert_inference"}
                and scale_direction == "unclear"
            ):
                raise ValueError(
                    "A supported scale-direction basis must choose a direction"
                )
        else:
            if (
                scale_direction != "not_applicable"
                or scale_basis != "not_applicable"
                or scale_confidence != "not_applicable"
            ):
                raise ValueError(
                    "Dichotomous adjudication must mark scale direction not applicable"
                )
            if not scale_rationale:
                raise ValueError(
                    "Dichotomous adjudication requires a not-applicable rationale"
                )
        direct_effect_semantics = _normalize_direct_effect_semantics(
            raw.get("direct_effect_semantics"),
            data_type=data_type,
            status=status,
            field_names=set(field_names),
            verified_fields=verified_fields,
        )
        if status != "unresolved":
            if not selected or not experimental_ids or not control_ids:
                raise ValueError(
                    "A confirmed/corrected adjudication requires candidates and arms"
                )
            required = _matching_final_field_set(
                data_type=str(target_by_id[target_id].get("data_type") or ""),
                fields=set(field_names),
            )
            if required is None or set(field_names) != required:
                raise ValueError(
                    f"Adjudicated fields do not form a supported result for {target_id}"
                )
            _validate_verified_field_coverage(
                field_rows=verified_fields,
                required_fields=required,
                experimental_arm_ids=experimental_ids,
                control_arm_ids=control_ids,
                study_map=notebook["study_map"],
                target_id=target_id,
            )
        elif verified_fields:
            raise ValueError("An unresolved adjudication cannot select final evidence")
        by_target[target_id] = {
            "target_id": target_id,
            "status": status,
            "selected_candidate_ids": selected,
            "experimental_arm_ids": experimental_ids,
            "control_arm_ids": control_ids,
            "experimental_arm_labels": [
                article_arm_label(arm_id=arm_id, study_map=notebook["study_map"])
                for arm_id in experimental_ids
            ],
            "control_arm_labels": [
                article_arm_label(arm_id=arm_id, study_map=notebook["study_map"])
                for arm_id in control_ids
            ],
            "verified_fields": verified_fields,
            "competing_interpretations": unique_text(
                raw.get("competing_interpretations")
            ),
            "assumptions": assumptions,
            "continuous_semantics": {
                "scale_direction": scale_direction,
                "basis": scale_basis,
                "confidence": scale_confidence,
                "rationale": scale_rationale,
            },
            "direct_effect_semantics": direct_effect_semantics,
            "reason": reason,
        }
    if set(by_target) != set(decision_by_target):
        missing = [target_id for target_id in decision_by_target if target_id not in by_target]
        raise ValueError(f"Adjudication omitted ready targets: {missing}")
    return [by_target[target_id] for target_id in decision_by_target]


def _normalize_direct_effect_semantics(
    raw: Any,
    *,
    data_type: str,
    status: str,
    field_names: set[str],
    verified_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate the adjudicator's working orientation for direct effects.

    Source-local evidence may retain an unknown subtraction order.  A final
    continuous direct-effect verdict must provide a resolved working
    interpretation so deterministic code never defaults a sign.
    """

    value = raw if isinstance(raw, dict) else {}
    comparison_direction = str(
        value.get("comparison_direction") or "not_applicable"
    )
    change_score_direction = str(
        value.get("change_score_direction") or "not_applicable"
    )
    basis = str(value.get("basis") or "")
    confidence = str(value.get("confidence") or "")
    rationale = str(value.get("rationale") or "").strip()
    if basis not in DIRECTION_BASES:
        raise ValueError(
            f"Unsupported direct-effect direction basis: {basis or '<missing>'}"
        )
    if confidence not in DIRECTION_CONFIDENCES:
        raise ValueError(
            "Unsupported direct-effect direction confidence: "
            f"{confidence or '<missing>'}"
        )
    semantics = {
        "comparison_direction": comparison_direction,
        "change_score_direction": change_score_direction,
        "basis": basis,
        "confidence": confidence,
        "rationale": rationale,
    }
    # An unresolved adjudication may intentionally retain the direct-effect
    # orientation as an uncertainty record even though it selects no final
    # fields.  It never reaches deterministic assembly; rejecting it here
    # would erase the distinction between "not applicable" and "not yet
    # interpretable".
    if status == "unresolved" and data_type == "Continuous" and not field_names:
        if basis not in {"insufficient_information", "cross_source_inference"}:
            raise ValueError(
                "Unresolved direct effects require an uncertainty or inference basis"
            )
        if confidence not in {"low", "medium"}:
            raise ValueError(
                "Unresolved direct effects require low or medium confidence"
            )
        if comparison_direction not in {
            "unclear",
            "experimental_minus_control",
            "control_minus_experimental",
        }:
            raise ValueError(
                "Unresolved direct effects require a valid comparison direction"
            )
        if change_score_direction not in {
            "unclear",
            "post_minus_baseline",
            "baseline_minus_post",
        }:
            raise ValueError(
                "Unresolved direct effects require a valid change-score direction"
            )
        if not rationale:
            raise ValueError(
                "Unresolved direct effects require a direction rationale"
            )
        return semantics
    if data_type != "Continuous":
        if (
            comparison_direction != "not_applicable"
            or change_score_direction != "not_applicable"
            or basis != "not_applicable"
            or confidence != "not_applicable"
        ):
            raise ValueError(
                "Dichotomous adjudication must mark direct-effect semantics "
                "not applicable"
            )
        if not rationale:
            raise ValueError(
                "Dichotomous adjudication requires direct-effect rationale"
            )
        return semantics

    has_direct = DIRECT_FIELDS.issubset(field_names)
    if not has_direct:
        if (
            comparison_direction != "not_applicable"
            or change_score_direction != "not_applicable"
            or basis != "not_applicable"
            or confidence != "not_applicable"
        ):
            raise ValueError(
                "Arm-level continuous adjudication must mark direct-effect "
                "semantics not applicable"
            )
        if not rationale:
            raise ValueError(
                "Arm-level continuous adjudication requires direct-effect rationale"
            )
        return semantics

    if status == "unresolved":
        if basis not in {"insufficient_information", "cross_source_inference"}:
            raise ValueError(
                "Unresolved direct effects require an uncertainty or inference basis"
            )
        if confidence not in {"low", "medium"}:
            raise ValueError(
                "Unresolved direct effects require low or medium confidence"
            )
        if not rationale:
            raise ValueError(
                "Unresolved direct effects require a direction rationale"
            )
        return semantics

    if comparison_direction not in {
        "experimental_minus_control",
        "control_minus_experimental",
    }:
        raise ValueError(
            "A confirmed direct effect requires a resolved comparison direction"
        )
    if basis not in {"source_reported", "cross_source_inference"}:
        raise ValueError(
            "A confirmed direct effect requires a supported direction basis"
        )
    if confidence not in {"high", "medium"}:
        raise ValueError(
            "A confirmed direct effect requires high or medium direction confidence"
        )
    if not rationale:
        raise ValueError("A confirmed direct effect requires a direction rationale")

    frames = {
        str((row.get("evidence_scope") or {}).get("result_frame") or "")
        for row in verified_fields
        if str(row.get("field") or "") in DIRECT_FIELDS
    }
    if "change_from_baseline" in frames:
        if change_score_direction not in {
            "post_minus_baseline",
            "baseline_minus_post",
        }:
            raise ValueError(
                "A confirmed change-score direct effect requires a resolved "
                "change-score direction"
            )
    elif change_score_direction not in {"not_applicable", "unclear"}:
        raise ValueError(
            "A post-intervention direct effect cannot declare a change-score direction"
        )
    return semantics


def normalize_evidence_scope(
    value: Any,
    *,
    field: str,
    arm_label: str,
    direct_field: bool = False,
    study_map: dict[str, Any],
    workspace: SourceWorkspace,
    source_ref: str,
    source_kind: str,
    latest_content_by_ref: dict[str, str],
) -> dict[str, Any]:
    """Validate the semantic scope claimed for one final numeric field."""

    if not isinstance(value, dict):
        raise ValueError(f"Verified field {field} requires evidence_scope")
    outcome_label = str(value.get("outcome_label") or "").strip()
    if not outcome_label:
        raise ValueError(f"Verified field {field} requires a scope outcome label")
    scope_arm = str(value.get("arm_label") or "").strip()
    comparison_direction = str(
        value.get("comparison_direction") or "not_applicable"
    )
    if direct_field:
        if comparison_direction not in {
            "experimental_minus_control",
            "control_minus_experimental",
            "unclear",
        }:
            raise ValueError(
                f"Verified direct field {field} requires a comparison direction"
            )
    else:
        if not scope_arm or not stable_core._labels_equivalent(
            scope_arm, arm_label, study_map
        ):
            raise ValueError(f"Verified field {field} scope does not match its arm")
        if comparison_direction != "not_applicable":
            raise ValueError(
                f"Verified arm field {field} cannot declare a comparison direction"
            )
    result_frame = str(value.get("result_frame") or "")
    if result_frame not in RESULT_FRAMES:
        raise ValueError(f"Verified field {field} has invalid result frame")
    change_score_direction = str(
        value.get("change_score_direction")
        or ("not_applicable" if result_frame != "change_from_baseline" else "unclear")
    )
    if change_score_direction not in CHANGE_SCORE_DIRECTIONS:
        raise ValueError(f"Verified field {field} has invalid change-score direction")
    if (
        result_frame == "change_from_baseline"
        and change_score_direction == "not_applicable"
    ):
        raise ValueError(f"Verified change field {field} requires change-score direction")
    denominator_scope = str(value.get("denominator_scope") or "")
    if denominator_scope not in DENOMINATOR_SCOPES:
        raise ValueError(f"Verified field {field} has invalid denominator scope")
    if field.endswith("_total") and denominator_scope == "not_applicable":
        raise ValueError(f"Verified total field {field} requires denominator scope")
    scope_status = str(value.get("scope_status") or "")
    if scope_status not in SCOPE_STATUSES:
        raise ValueError(f"Verified field {field} has invalid scope status")

    visible_source = (
        stable_core._xml_text(latest_content_by_ref[source_ref])
        if source_kind == "table"
        else latest_content_by_ref[source_ref]
    )
    supporting_quotes: list[dict[str, str]] = []
    for raw in _object_list(value.get("supporting_quotes")):
        supporting_source_ref = str(raw.get("source_ref") or "")
        supporting_source_kind = str(raw.get("source_kind") or "")
        quote = str(raw.get("quote") or "").strip()
        if supporting_source_ref not in latest_content_by_ref:
            raise ValueError(
                "Evidence-scope supporting quote must use the current raw bundle"
            )
        supporting_source = workspace.source(supporting_source_ref)
        if supporting_source.source_kind != supporting_source_kind:
            raise ValueError("Evidence-scope supporting source kind does not match")
        if not quote:
            raise ValueError("Evidence-scope supporting quote cannot be empty")
        supporting_visible_source = (
            stable_core._xml_text(latest_content_by_ref[supporting_source_ref])
            if supporting_source_kind == "table"
            else latest_content_by_ref[supporting_source_ref]
        )
        if not _quote_matches_visible_source(quote, supporting_visible_source):
            raise ValueError(
                "Evidence-scope quote is not present in source "
                f"{supporting_source_ref}"
            )
        supporting_quotes.append(
            {
                "source_ref": supporting_source_ref,
                "source_kind": supporting_source_kind,
                "quote": quote,
            }
        )
    footnote_links: list[dict[str, str | None]] = []
    for raw in _object_list(value.get("footnote_links")):
        marker = str(raw.get("marker") or "").strip()
        text = str(raw.get("text") or "").strip()
        # A table-wide footnote often has text but no marker.  The text is the
        # auditable link; a marker adds precision when the source actually has
        # one, but is not a prerequisite for using the footnote.
        if not text:
            raise ValueError("Every evidence-scope footnote link needs text")
        if not _quote_matches_visible_source(text, visible_source):
            raise ValueError(
                f"Evidence-scope footnote is not present in source {source_ref}"
            )
        footnote_links.append({"marker": marker or None, "text": text})

    return {
        "outcome_label": outcome_label,
        "outcome_measure": optional_text(value.get("outcome_measure")),
        "timepoint": optional_text(value.get("timepoint")),
        "arm_label": scope_arm,
        "comparison_direction": comparison_direction,
        "analysis_population": optional_text(value.get("analysis_population")),
        "result_frame": result_frame,
        "change_score_direction": change_score_direction,
        "row_or_item_label": optional_text(value.get("row_or_item_label")),
        "column_header_path": unique_text(value.get("column_header_path")),
        "denominator_scope": denominator_scope,
        "footnote_links": footnote_links,
        "supporting_quotes": supporting_quotes,
        "scope_status": scope_status,
    }


def _validate_verified_field_coverage(
    *,
    field_rows: list[dict[str, Any]],
    required_fields: set[str],
    experimental_arm_ids: list[str],
    control_arm_ids: list[str],
    study_map: dict[str, Any],
    target_id: str,
) -> None:
    """Require one supported result representation for the selected comparison."""

    fields = {str(row.get("field") or "") for row in field_rows}
    if fields != required_fields:
        raise ValueError(f"Verified fields do not cover target {target_id}")

    if DIRECT_FIELDS.issubset(fields):
        direct_rows = [
            row for row in field_rows
            if str(row.get("field") or "") in DIRECT_FIELDS
        ]
        if len(direct_rows) != len(DIRECT_FIELDS):
            raise ValueError(f"Verified direct fields are duplicated for {target_id}")
        total_fields = fields - DIRECT_FIELDS
        if not total_fields:
            return
        expected = {
            *[("experimental_total", arm_id) for arm_id in experimental_arm_ids],
            *[("control_total", arm_id) for arm_id in control_arm_ids],
        }
        actual = {
            (str(row.get("field") or ""), str(row.get("arm_id") or ""))
            for row in field_rows
            if str(row.get("field") or "") in total_fields
        }
        if actual != expected:
            raise ValueError(
                f"Verified direct-effect totals do not cover selected arms for {target_id}"
            )
        return

    expected: set[tuple[str, str]] = set()
    for field in required_fields:
        arm_ids = (
            experimental_arm_ids
            if field.startswith("experimental_")
            else control_arm_ids
        )
        expected.update((field, arm_id) for arm_id in arm_ids)

    actual: set[tuple[str, str]] = set()
    for row in field_rows:
        field = str(row.get("field") or "")
        requested_label = str(
            row.get("observed_arm_label") or row.get("arm_label") or ""
        ).strip()
        arm_id = str(row.get("arm_id") or "").strip()
        if not arm_id:
            arm_id = article_arm_id_for_label(
                requested_label,
                study_map=study_map,
            ) or ""
        selected_arm_ids = (
            experimental_arm_ids
            if field.startswith("experimental_")
            else control_arm_ids
        )
        if arm_id not in selected_arm_ids:
            raise ValueError(
                f"Verified field {field} must identify one selected article arm"
            )
        key = (field, arm_id)
        if key in actual:
            raise ValueError(
                f"Verified field {field} is duplicated for arm {arm_id}"
            )
        actual.add(key)

    if actual != expected:
        raise ValueError(
            f"Verified fields do not provide one complete set per arm for {target_id}"
        )


def _matching_final_field_set(
    *,
    data_type: str,
    fields: set[str],
) -> set[str] | None:
    return next(
        (
            required
            for required in FINAL_FIELD_SETS.get(data_type, [])
            if fields == required
        ),
        None,
    )


def _selected_arm_ids(
    value: Any,
    *,
    legacy_labels: Any,
    valid_arm_ids: set[str],
    study_map: dict[str, Any],
) -> list[str]:
    supplied = unique_text(value)
    if supplied:
        return validated_ids(supplied, valid_arm_ids, "article arm")
    resolved: list[str] = []
    for label in unique_text(legacy_labels):
        arm_id = article_arm_id_for_label(label, study_map=study_map)
        if arm_id is None:
            raise ValueError(f"Article arm label does not map uniquely: {label}")
        resolved.append(arm_id)
    return unique_text(resolved)


def semantic_notebook(notebook: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_map": deepcopy(notebook["study_map"]),
        "source_study_maps": deepcopy(notebook.get("source_study_maps", [])),
        "candidates": [candidate_summary(row, include_values=True) for row in notebook["candidates"]],
        "support_materials": [
            material_summary(row, include_values=True)
            for row in notebook["support_materials"]
        ],
        "claims": deepcopy(notebook["claims"]),
        "alternatives": deepcopy(notebook["alternatives"]),
        "open_questions": list(notebook["open_questions"]),
        "evidence_needs": list(notebook["evidence_needs"]),
        "working_decision_state": working_state_snapshot(notebook),
        "coverage": deepcopy(notebook["coverage"]),
        "warnings": list(notebook["warnings"]),
    }


def result_blind_notebook(notebook: dict[str, Any]) -> dict[str, Any]:
    study_map = deepcopy(notebook["study_map"])
    study_map["notes"] = []
    study_map["analysis_populations"] = [
        _blind_numeric_text(value)
        for value in study_map.get("analysis_populations") or []
    ]
    study_map["arms"] = [
        {
            **arm,
            "description": _blind_numeric_text(arm.get("description")),
        }
        for arm in study_map.get("arms") or []
    ]
    study_map["evidence"] = [
        {
            "source_refs": list(row.get("source_refs") or []),
            "source_windows": deepcopy(row.get("source_windows") or []),
        }
        for row in study_map.get("evidence") or []
    ]
    return {
        "study_map": study_map,
        "candidates": [candidate_summary(row, include_values=False) for row in notebook["candidates"]],
        "support_materials": [
            material_summary(row, include_values=False)
            for row in notebook["support_materials"]
        ],
        "ambiguity_state": {
            "claim_count": len(notebook["claims"]),
            "alternative_count": len(notebook["alternatives"]),
            "open_question_count": len(notebook["open_questions"]),
        },
        "coverage": deepcopy(notebook["coverage"]),
        "warnings": list(notebook["warnings"]),
    }


def investigation_notebook(notebook: dict[str, Any]) -> dict[str, Any]:
    """Compact state for navigation calls; raw values stay in debug state only."""

    return {
        "study_map": deepcopy(notebook["study_map"]),
        "source_study_maps": deepcopy(notebook.get("source_study_maps", [])),
        "candidates": [
            candidate_summary(row, include_values=False)
            for row in notebook["candidates"]
        ],
        "support_materials": [
            material_summary(row, include_values=False)
            for row in notebook["support_materials"]
        ],
        "claims": deepcopy(notebook["claims"][-32:]),
        "alternatives": deepcopy(notebook["alternatives"][-32:]),
        "open_questions": list(notebook["open_questions"][-32:]),
        "evidence_needs": list(notebook["evidence_needs"][-32:]),
        "coverage": deepcopy(notebook["coverage"]),
        "warnings": list(notebook["warnings"]),
    }


def candidate_summary(
    candidate: dict[str, Any],
    *,
    include_values: bool,
) -> dict[str, Any]:
    if include_values:
        uncertainties = list(candidate.get("uncertainties") or [])
        local_setting = deepcopy(candidate["local_setting"])
    else:
        uncertainties = []
        local_setting = _blind_local_setting(candidate.get("local_setting") or {})
    return {
        "candidate_id": candidate["candidate_id"],
        "source_table_id": candidate["source_table_id"],
        "data_type": candidate["data_type"],
        "contribution_shape": candidate.get("contribution_shape") or "arm_level",
        "local_setting": local_setting,
        "arms": [
            {
                "label": arm["label"],
                "article_arm_id": arm.get("article_arm_id"),
                "identity_status": arm.get("identity_status") or "unmapped",
                "materials": [
                    material_summary(material, include_values=include_values)
                    for material in arm.get("materials") or []
                ],
            }
            for arm in candidate.get("arms") or []
        ],
        "uncertainties": uncertainties,
        "has_uncertainties": bool(candidate.get("uncertainties")),
    }


def material_summary(
    material: dict[str, Any],
    *,
    include_values: bool,
) -> dict[str, Any]:
    interpretation = (
        material.get("interpretation") or material.get("notes")
        if include_values
        else None
    )
    result = {
        "material_id": material.get("material_id"),
        "candidate_id": material.get("candidate_id"),
        "kind": material.get("kind"),
        "statistical_scope": material.get("statistical_scope"),
        "applies_to": material.get("applies_to"),
        "arm_label": material.get("arm_label"),
        "arm_observation_id": material.get("arm_observation_id"),
        "article_arm_id": material.get("article_arm_id"),
        "identity_status": material.get("identity_status") or "unmapped",
        "local_setting": (
            deepcopy(material.get("local_setting") or {})
            if include_values
            else _blind_local_setting(material.get("local_setting") or {})
        ),
        "source_ref": material.get("source_ref")
        or material.get("source_table_id"),
        "source_kind": material.get("source_kind") or "table",
        "interpretation": interpretation,
        "uncertainties": (
            list(material.get("uncertainties") or []) if include_values else []
        ),
        "trace_warnings": (
            list(material.get("trace_warnings") or []) if include_values else []
        ),
        "has_uncertainties": bool(material.get("uncertainties")),
        "has_trace_warnings": bool(material.get("trace_warnings")),
    }
    if include_values:
        result.update(
            {
                "value": material.get("value"),
                "lower": material.get("lower"),
                "upper": material.get("upper"),
                "confidence_level": material.get("confidence_level"),
                "decimal_places": material.get("decimal_places"),
                "source_quote": material.get("source_quote"),
            }
        )
    else:
        result["reported_components"] = [
            field
            for field in ("value", "lower", "upper", "confidence_level")
            if material.get(field) is not None
        ]
    return result


def normalize_candidate(
    raw: dict[str, Any],
    *,
    workspace: SourceWorkspace,
    latest_content: dict[str, str],
    latest_windows: dict[str, list[dict[str, Any]]],
    allowed_table_refs: set[str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Every candidate block must be an object")
    source_ref = str(raw.get("source_table_id") or "")
    if source_ref not in allowed_table_refs or source_ref not in workspace.table_refs:
        raise ValueError(
            "A candidate must come from one raw table supplied on the current call"
        )
    data_type = str(raw.get("data_type") or "")
    if data_type not in REQUIRED_FINAL_FIELDS:
        raise ValueError(f"Unsupported candidate data type: {data_type}")
    local_setting = {
        "outcome_label": optional_text(raw.get("outcome_label")),
        "outcome_measure": optional_text(raw.get("outcome_measure")),
        "unit": optional_text(raw.get("unit")),
        "timepoint": optional_text(raw.get("timepoint")),
        "statistic_type": None,
        "population_or_subgroup": optional_text(raw.get("population_or_subgroup")),
        "analysis_population": optional_text(raw.get("analysis_population")),
        "continuous_result_frame": optional_text(raw.get("continuous_result_frame")),
        "change_score_definition": optional_text(raw.get("change_score_definition")),
        "change_score_direction": str(
            raw.get("change_score_direction")
            or (
                "not_applicable"
                if raw.get("continuous_result_frame") != "change_from_baseline"
                else "unclear"
            )
        ),
        "scale_direction": str(raw.get("scale_direction") or "unclear"),
        "table_local_notes": "; ".join(unique_text(raw.get("notes"))) or None,
    }
    if not local_setting["outcome_label"]:
        raise ValueError("Every candidate requires an article-local outcome label")
    arms: list[dict[str, Any]] = []
    uncertainties = unique_text(raw.get("uncertainties"))
    for arm_index, arm_raw in enumerate(_object_list(raw.get("arms"))):
        label = str(arm_raw.get("label") or "").strip()
        if not label:
            raise ValueError("Every candidate arm requires an article-local label")
        materials = [
            normalize_material(
                material_raw,
                workspace=workspace,
                source_ref=source_ref,
                latest_content=latest_content[source_ref],
                latest_windows=latest_windows.get(source_ref, []),
                arm_label=label,
                local_setting=local_setting,
                material_key=f"candidate-{arm_index}-{material_index}",
                strict_source_quote=False,
            )
            for material_index, material_raw in enumerate(
                _object_list(arm_raw.get("materials"))
            )
        ]
        calculation = solve_arm(data_type=data_type, materials=materials)
        uncertainties.extend(calculation.warnings)
        arms.append(
            {
                "label": label,
                "events": calculation.values.get("events"),
                "total": calculation.values.get("total"),
                "mean": calculation.values.get("mean"),
                "sd": calculation.values.get("sd"),
                "materials": materials,
                "field_traces": calculation.field_traces,
                "source_quote": " ... ".join(
                    unique_text(
                        material.get("source_quote") for material in materials
                    )
                ),
            }
        )
    profile = stable_core._statistic_profile(
        data_type=data_type,
        arms=arms,
        block_materials=[],
        reported_statistic_type=None,
    )
    local_setting.update(
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
    uncertainties.extend(profile["warnings"])
    candidate_key_payload = {
        "source_ref": source_ref,
        "local_setting": local_setting,
        "arm_labels": [arm["label"] for arm in arms],
    }
    candidate_key = sha256(_canonical(candidate_key_payload).encode("utf-8")).hexdigest()
    candidate_id = (
        f"candidate::{stable_core._slug(source_ref)}::{candidate_key[:14]}"
    )
    for arm in arms:
        for material in arm["materials"]:
            material["candidate_id"] = candidate_id
    return {
        "candidate_id": candidate_id,
        "candidate_key": candidate_key,
        "source_table_id": source_ref,
        "source_hash": workspace.source(source_ref).source_hash,
        "data_type": data_type,
        "local_setting": local_setting,
        "arms": arms,
        "block_materials": [],
        "contribution_shape": "arm_level" if arms else "non_arm_result",
        "uncertainties": unique_text(uncertainties),
        "source_spans": source_spans(
            [material for arm in arms for material in arm["materials"]]
        ),
    }


def normalize_support_material(
    raw: dict[str, Any],
    *,
    workspace: SourceWorkspace,
    latest_content: dict[str, str],
    latest_windows: dict[str, list[dict[str, Any]]],
    allowed_source_refs: set[str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Every supporting material must be an object")
    source_ref = str(raw.get("source_ref") or "")
    source_kind = str(raw.get("source_kind") or "")
    if source_ref not in allowed_source_refs:
        raise ValueError("Supporting material must come from the current raw source bundle")
    source = workspace.source(source_ref)
    if source.source_kind != source_kind:
        raise ValueError("Supporting material source kind does not match source ref")
    local_setting = {
        "outcome_label": optional_text(raw.get("outcome_label")),
        "outcome_measure": optional_text(raw.get("outcome_measure")),
        "timepoint": optional_text(raw.get("timepoint")),
        "population_or_subgroup": optional_text(raw.get("population_or_subgroup")),
        "analysis_population": optional_text(raw.get("analysis_population")),
    }
    material = normalize_material(
        raw.get("material"),
        workspace=workspace,
        source_ref=source_ref,
        latest_content=latest_content[source_ref],
        latest_windows=latest_windows.get(source_ref, []),
        arm_label=optional_text(raw.get("arm_label")),
        local_setting=local_setting,
        material_key="support",
        strict_source_quote=False,
    )
    material["source_kind"] = source_kind
    return material


def normalize_material(
    raw: Any,
    *,
    workspace: SourceWorkspace,
    source_ref: str,
    latest_content: str,
    latest_windows: list[dict[str, Any]],
    arm_label: str | None,
    local_setting: dict[str, Any],
    material_key: str,
    strict_source_quote: bool = True,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Every numeric material must be an object")
    quote = str(raw.get("source_quote") or "").strip()
    if not quote and strict_source_quote:
        raise ValueError("Every numeric material requires a source quote")
    source = workspace.source(source_ref)
    source_visible_content = (
        stable_core._xml_text(latest_content)
        if source.source_kind == "table"
        else latest_content
    )
    quote_grounded = bool(quote) and _quote_matches_visible_source(
        quote, source_visible_content
    )
    if not quote_grounded and strict_source_quote:
        raise ValueError(
            f"Material quote is not present in the current source window: {source_ref}"
        )
    table_payload = {
        "table_id": source_ref,
        "raw_xml": source.content,
        "source_hash": source.source_hash,
    }
    normalized = stable_core._normalize_material(
        raw={
            "kind": raw.get("kind"),
            "value": raw.get("value"),
            "lower": raw.get("lower"),
            "upper": raw.get("upper"),
            "confidence_level": raw.get("confidence_level"),
            "decimal_places": raw.get("decimal_places"),
            "statistical_scope": raw.get("statistical_scope"),
            "applies_to": raw.get("applies_to"),
            "source_quote": quote,
            "notes": raw.get("interpretation"),
            "uncertainties": raw.get("uncertainties"),
        },
        arm_label=arm_label,
        local_setting=local_setting,
        table=table_payload,
        material_key=(
            f"{material_key}-"
            f"{sha256(_canonical(raw).encode('utf-8')).hexdigest()[:10]}"
        ),
    )
    if normalized is None:
        raise ValueError("Numeric material could not be normalized")
    if not quote:
        normalized["trace_warnings"] = unique_text(
            [*(normalized.get("trace_warnings") or []), "source_quote_missing"]
        )
    elif not quote_grounded:
        normalized["trace_warnings"] = unique_text(
            [
                *(normalized.get("trace_warnings") or []),
                "source_quote_not_found_in_source_window",
            ]
        )
    normalized["source_ref"] = source_ref
    normalized["source_kind"] = source.source_kind
    normalized["interpretation"] = str(raw.get("interpretation") or "").strip()
    normalized["source_windows"] = _matching_source_windows(
        source_ref=source_ref,
        source_kind=source.source_kind,
        quote=quote,
        source_windows=latest_windows,
    )
    return normalized


def empty_study_map() -> dict[str, Any]:
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


def normalize_study_map(
    value: Any,
    *,
    valid_refs: set[str],
    source_windows_by_ref: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("study_map_update must be an object")
    arms = []
    for raw in _object_list(value.get("arms")):
        label = str(raw.get("label") or "").strip()
        if not label:
            continue
        role = str(raw.get("role") or "unclear")
        if role not in {"experimental", "control", "other", "unclear"}:
            raise ValueError(f"Unsupported article arm role: {role}")
        arms.append(
            {
                "label": label,
                "aliases": unique_text(raw.get("aliases")),
                "role": role,
                "description": optional_text(raw.get("description")),
            }
        )
    evidence = []
    for raw in _object_list(value.get("evidence")):
        fact = str(raw.get("fact") or "").strip()
        refs = validated_ids(raw.get("source_refs"), valid_refs, "source")
        if fact and refs:
            evidence.append(
                {
                    "fact": fact,
                    "source_refs": refs,
                    "source_windows": [
                        _transport_locator(row)
                        for source_ref in refs
                        for row in (source_windows_by_ref or {}).get(source_ref, [])
                    ],
                }
            )
    return {
        "study_design": optional_text(value.get("study_design")),
        "population": optional_text(value.get("population")),
        "treatment_duration": optional_text(value.get("treatment_duration")),
        "follow_up": unique_text(value.get("follow_up")),
        "analysis_populations": unique_text(value.get("analysis_populations")),
        "arms": arms,
        "notes": unique_text(value.get("notes")),
        "evidence": evidence,
    }


def _merge_reconciled_study_map(
    current: dict[str, Any], update: dict[str, Any]
) -> dict[str, Any]:
    """Accept investigator arms as article-level semantic entities.

    Source-local table maps are intentionally not merged by normalized role
    labels.  The investigator has seen all local observations and must emit a
    canonical article arm plus supported aliases.  Engineering validates the
    identity contract and assigns stable IDs; it does not decide that two
    generic labels are semantically the same arm.
    """

    non_arm_update = {**update, "arms": []}
    merged = stable_core._merge_study_map(current, non_arm_update)
    arms = [
        deepcopy(arm)
        for arm in update.get("arms") or []
        if isinstance(arm, dict) and str(arm.get("label") or "").strip()
    ]
    canonical_keys = [_article_arm_identity_key(str(arm["label"])) for arm in arms]
    if len(canonical_keys) != len(set(canonical_keys)):
        raise ValueError(
            "Investigator StudyMap must use one unique canonical label per real arm"
        )
    merged["arms"] = arms
    merged["evidence"] = unique_dicts(
        [*(current.get("evidence") or []), *(update.get("evidence") or [])]
    )
    return _assign_article_arm_ids(merged)


def arm_observations(notebook: dict[str, Any]) -> list[dict[str, Any]]:
    """Build source-qualified arm entities without cross-source string merging."""

    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for source_map in notebook.get("source_study_maps") or []:
        source_ref = str(source_map.get("source_ref") or "")
        study_map = source_map.get("study_map") or {}
        for arm in study_map.get("arms") or []:
            if not isinstance(arm, dict):
                continue
            label = str(arm.get("label") or "").strip()
            key = (source_ref, _article_arm_identity_key(label))
            if not source_ref or not key[1]:
                continue
            by_key[key] = {
                "observation_id": _arm_observation_id(source_ref, label),
                "source_ref": source_ref,
                "observed_label": label,
                "aliases": unique_text(arm.get("aliases")),
                "role": str(arm.get("role") or "unclear"),
                "description": optional_text(arm.get("description")),
                "candidate_ids": [],
            }
    for candidate in notebook.get("candidates") or []:
        source_ref = str(candidate.get("source_table_id") or "")
        candidate_id = str(candidate.get("candidate_id") or "")
        for arm in candidate.get("arms") or []:
            label = str(arm.get("label") or "").strip()
            key = (source_ref, _article_arm_identity_key(label))
            if not source_ref or not key[1]:
                continue
            observation = by_key.setdefault(
                key,
                {
                    "observation_id": _arm_observation_id(source_ref, label),
                    "source_ref": source_ref,
                    "observed_label": label,
                    "aliases": [],
                    "role": "unclear",
                    "description": None,
                    "candidate_ids": [],
                },
            )
            observation["candidate_ids"] = unique_text(
                [*observation["candidate_ids"], candidate_id]
            )
            arm["arm_observation_id"] = observation["observation_id"]
    return sorted(
        by_key.values(),
        key=lambda row: (
            str(row["source_ref"]),
            str(row["observed_label"]).casefold(),
        ),
    )


def normalize_arm_reconciliation_response(
    value: dict[str, Any],
    *,
    observations: list[dict[str, Any]],
    valid_source_refs: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Arm reconciliation must return an object")
    observation_ids = {str(row["observation_id"]) for row in observations}
    canonical_arms: list[dict[str, Any]] = []
    assigned: set[str] = set()
    canonical_keys: set[str] = set()
    for raw in _object_list(value.get("canonical_arms")):
        label = str(raw.get("canonical_label") or "").strip()
        key = _article_arm_identity_key(label)
        if not key or key in canonical_keys:
            raise ValueError("Canonical article arm labels must be non-empty and unique")
        canonical_keys.add(key)
        members = validated_ids(
            raw.get("member_observation_ids"), observation_ids, "arm observation"
        )
        if not members:
            raise ValueError("Every canonical article arm requires source observations")
        overlap = assigned.intersection(members)
        if overlap:
            raise ValueError(
                f"Arm observations cannot belong to multiple canonical arms: {sorted(overlap)}"
            )
        assigned.update(members)
        role = str(raw.get("role") or "")
        if role not in {"experimental", "control", "other", "unclear"}:
            raise ValueError(f"Unsupported canonical arm role: {role}")
        evidence_refs = validated_ids(
            raw.get("evidence_source_refs"), valid_source_refs, "source"
        )
        rationale = str(raw.get("rationale") or "").strip()
        if not evidence_refs or not rationale:
            raise ValueError(
                "Every canonical arm requires evidence sources and a rationale"
            )
        canonical_arms.append(
            {
                "canonical_label": label,
                "aliases": unique_text(raw.get("aliases")),
                "role": role,
                "description": optional_text(raw.get("description")),
                "member_observation_ids": members,
                "evidence_source_refs": evidence_refs,
                "rationale": rationale,
            }
        )
    unresolved = validated_ids(
        value.get("unresolved_observation_ids"), observation_ids, "arm observation"
    )
    overlap = assigned.intersection(unresolved)
    if overlap:
        raise ValueError(
            f"Resolved arm observations cannot also be unresolved: {sorted(overlap)}"
        )
    covered = assigned | set(unresolved)
    if covered != observation_ids:
        missing = sorted(observation_ids - covered)
        raise ValueError(f"Arm reconciliation omitted observations: {missing}")
    return {
        "canonical_arms": canonical_arms,
        "unresolved_observation_ids": unresolved,
        "notes": unique_text(value.get("notes")),
    }


def apply_arm_reconciliation(
    notebook: dict[str, Any],
    *,
    observations: list[dict[str, Any]],
    reconciliation: dict[str, Any],
) -> None:
    observation_by_id = {
        str(row["observation_id"]): row for row in observations
    }
    arms: list[dict[str, Any]] = []
    for group in reconciliation["canonical_arms"]:
        members = [
            observation_by_id[observation_id]
            for observation_id in group["member_observation_ids"]
        ]
        canonical_label = str(group["canonical_label"])
        aliases = unique_text(
            [
                *group["aliases"],
                *[str(member["observed_label"]) for member in members],
                *[
                    alias
                    for member in members
                    for alias in member.get("aliases") or []
                ],
            ]
        )
        aliases = [
            alias
            for alias in aliases
            if _article_arm_identity_key(alias)
            != _article_arm_identity_key(canonical_label)
        ]
        arms.append(
            {
                "label": canonical_label,
                "aliases": aliases,
                "role": group["role"],
                "description": group["description"],
                "member_observation_ids": list(group["member_observation_ids"]),
                "identity_rationale": group["rationale"],
                "identity_source_refs": list(group["evidence_source_refs"]),
            }
        )
    final_map = stable_core._merge_study_map(
        notebook["study_map"],
        {**notebook.get("investigator_study_map", empty_study_map()), "arms": []},
    )
    final_map["arms"] = arms
    final_map = _assign_article_arm_ids(final_map)
    observation_to_arm: dict[str, str] = {}
    for arm in final_map["arms"]:
        for observation_id in arm.get("member_observation_ids") or []:
            observation_to_arm[str(observation_id)] = str(arm["arm_id"])
    notebook["study_map"] = final_map
    notebook["arm_identity"] = {
        "observations": deepcopy(observations),
        "canonical_arms": deepcopy(reconciliation["canonical_arms"]),
        "unresolved": list(reconciliation["unresolved_observation_ids"]),
        "observation_to_arm_id": observation_to_arm,
        "notes": list(reconciliation["notes"]),
    }
    _bind_candidate_arm_ids(
        notebook["candidates"],
        study_map=final_map,
        observation_to_arm_id=observation_to_arm,
    )
    for material in notebook["support_materials"]:
        source_ref = str(
            material.get("source_ref") or material.get("source_table_id") or ""
        )
        arm_label = str(material.get("arm_label") or "")
        observation_id = _arm_observation_id(source_ref, arm_label)
        material["arm_observation_id"] = observation_id
        material["article_arm_id"] = observation_to_arm.get(observation_id)
        material["identity_status"] = (
            "bound" if material["article_arm_id"] else "unmapped"
        )


def _arm_observation_id(source_ref: str, label: str) -> str:
    payload = {"source_ref": source_ref, "label": _article_arm_identity_key(label)}
    digest = sha256(_canonical(payload).encode("utf-8")).hexdigest()[:16]
    return f"arm-observation::{stable_core._slug(source_ref)}::{digest}"


def merge_study_map(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = stable_core._merge_study_map(current, update)
    merged["arms"] = _merge_explicit_arm_aliases(merged.get("arms") or [])
    merged = _assign_article_arm_ids(merged)
    merged["evidence"] = unique_dicts(
        [*(current.get("evidence") or []), *(update.get("evidence") or [])]
    )
    return merged


def _merge_explicit_arm_aliases(arms: list[Any]) -> list[dict[str, Any]]:
    """Collapse only a unique canonical-label/alias identity relation.

    Alias-to-alias overlap is deliberately insufficient.  Generic aliases such
    as ``experimental group`` may legitimately be shared by several distinct
    arms and must not turn those arms into one connected component.
    """

    groups: list[dict[str, Any]] = []
    for raw in arms:
        if not isinstance(raw, dict):
            continue
        incoming = deepcopy(raw)
        incoming_label = _article_arm_identity_key(
            str(incoming.get("label") or "")
        )
        canonical_matches = [
            index
            for index, existing in enumerate(groups)
            if incoming_label
            and incoming_label
            == _article_arm_identity_key(str(existing.get("label") or ""))
        ]
        matching = canonical_matches or [
            index
            for index, existing in enumerate(groups)
            if _has_label_alias_identity(first=existing, second=incoming)
        ]
        if len(matching) != 1:
            groups.append(incoming)
            continue
        target_index = matching[0]
        groups[target_index] = _merge_article_arm_objects(
            groups[target_index], incoming
        )
    return groups


def _has_label_alias_identity(
    *,
    first: dict[str, Any],
    second: dict[str, Any],
) -> bool:
    first_label = _article_arm_identity_key(str(first.get("label") or ""))
    second_label = _article_arm_identity_key(str(second.get("label") or ""))
    first_aliases = {
        _article_arm_identity_key(str(value))
        for value in first.get("aliases") or []
        if _article_arm_identity_key(str(value))
    }
    second_aliases = {
        _article_arm_identity_key(str(value))
        for value in second.get("aliases") or []
        if _article_arm_identity_key(str(value))
    }
    return bool(
        (second_label and second_label in first_aliases)
        or (first_label and first_label in second_aliases)
    )


def _merge_article_arm_objects(
    first: dict[str, Any],
    second: dict[str, Any],
) -> dict[str, Any]:
    label = str(first.get("label") or second.get("label") or "").strip()
    aliases = unique_text(
        [
            *(first.get("aliases") or []),
            str(second.get("label") or ""),
            *(second.get("aliases") or []),
        ]
    )
    aliases = [
        value
        for value in aliases
        if _article_arm_identity_key(value) != _article_arm_identity_key(label)
    ]
    first_role = str(first.get("role") or "unclear")
    second_role = str(second.get("role") or "unclear")
    role = (
        second_role
        if first_role == "unclear"
        else first_role
        if second_role in {"unclear", first_role}
        else "unclear"
    )
    result = {
        "label": label,
        "aliases": aliases,
        "role": role,
        "description": first.get("description") or second.get("description"),
    }
    arm_id = str(first.get("arm_id") or second.get("arm_id") or "")
    if arm_id:
        result["arm_id"] = arm_id
    return result


def _article_arm_identity_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def article_arm_ids(study_map: dict[str, Any]) -> list[str]:
    return [
        str(arm.get("arm_id") or "")
        for arm in study_map.get("arms") or []
        if isinstance(arm, dict) and str(arm.get("arm_id") or "")
    ]


def article_arm_label(*, arm_id: str, study_map: dict[str, Any]) -> str:
    arm = _article_arm_by_id(arm_id=arm_id, study_map=study_map)
    if arm is None:
        raise ValueError(f"Unknown article arm id: {arm_id}")
    return str(arm.get("label") or "")


def article_arm_id_for_label(
    label: str,
    *,
    study_map: dict[str, Any],
) -> str | None:
    key = _article_arm_identity_key(label)
    if not key:
        return None
    canonical_matches = [
        str(arm.get("arm_id") or "")
        for arm in study_map.get("arms") or []
        if isinstance(arm, dict)
        and str(arm.get("arm_id") or "")
        and key == _article_arm_identity_key(str(arm.get("label") or ""))
    ]
    unique = unique_text(canonical_matches)
    if len(unique) == 1:
        return unique[0]
    if unique:
        return None
    alias_matches = [
        str(arm.get("arm_id") or "")
        for arm in study_map.get("arms") or []
        if isinstance(arm, dict)
        and str(arm.get("arm_id") or "")
        and key
        in {
            _article_arm_identity_key(str(value))
            for value in arm.get("aliases") or []
        }
    ]
    unique = unique_text(alias_matches)
    return unique[0] if len(unique) == 1 else None


def _assign_article_arm_ids(study_map: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(study_map)
    arms = [deepcopy(arm) for arm in result.get("arms") or [] if isinstance(arm, dict)]
    used: set[str] = set()
    next_index = 1
    for arm in arms:
        arm_id = str(arm.get("arm_id") or "")
        if arm_id and arm_id not in used:
            used.add(arm_id)
            continue
        while f"article-arm::{next_index}" in used:
            next_index += 1
        arm["arm_id"] = f"article-arm::{next_index}"
        used.add(str(arm["arm_id"]))
        next_index += 1
    result["arms"] = arms
    return result


def _bind_candidate_arm_ids(
    candidates: list[dict[str, Any]],
    *,
    study_map: dict[str, Any],
    observation_to_arm_id: dict[str, str] | None = None,
) -> None:
    valid_ids = set(article_arm_ids(study_map))
    for candidate in candidates:
        for arm in candidate.get("arms") or []:
            existing = str(arm.get("article_arm_id") or "")
            observation_id = str(arm.get("arm_observation_id") or "")
            resolved = str(
                (observation_to_arm_id or {}).get(observation_id) or ""
            ) or article_arm_id_for_label(
                str(arm.get("label") or ""), study_map=study_map
            )
            if existing in valid_ids and (resolved is None or resolved == existing):
                arm["identity_status"] = "bound"
                continue
            arm["article_arm_id"] = resolved
            arm["identity_status"] = "bound" if resolved else "unmapped"


def _article_arm_by_id(
    *,
    arm_id: str,
    study_map: dict[str, Any],
) -> dict[str, Any] | None:
    matches = [
        arm
        for arm in study_map.get("arms") or []
        if isinstance(arm, dict) and str(arm.get("arm_id") or "") == arm_id
    ]
    return matches[0] if len(matches) == 1 else None


def semantic_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        **stable_core._semantic_target(target),
        "analysis_model_plan": target.get("analysis_model_plan"),
        "notes": target.get("notes"),
    }


def default_section_queries(
    *,
    targets: list[dict[str, Any]],
    notebook: dict[str, Any],
    limit: int = 8,
) -> list[str]:
    values: list[str] = [
        str(row.get("text") or "") for row in active_evidence_needs(notebook)
    ]
    values.extend(notebook.get("open_questions") or [])
    for target in targets:
        outcome = target.get("outcome") or {}
        comparison = target.get("comparison") or {}
        for value in (
            target.get("population_scope"),
            outcome.get("label"),
            outcome.get("measure"),
            comparison.get("experimental"),
            comparison.get("comparator"),
            (target.get("timepoint") or {}).get("label"),
        ):
            text = str(value or "").strip()
            if text:
                values.append(text)
    return unique_text(values)[:limit]


def material_index(notebook: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {
        str(material["material_id"]): material
        for candidate in notebook["candidates"]
        for arm in candidate.get("arms") or []
        for material in arm.get("materials") or []
    }
    result.update(
        {
            str(material["material_id"]): material
            for material in notebook["support_materials"]
        }
    )
    return result


def decision_source_refs(
    decision: dict[str, Any],
    *,
    notebook: dict[str, Any],
) -> list[str]:
    """Return every source named by a decision, including audit alternatives.

    Production source verification uses `decision_required_source_refs`.
    This broader helper remains available to legacy scope-audit paths that
    intentionally inspect alternatives.
    """

    return unique_text(
        [
            *decision_required_source_refs(decision, notebook=notebook),
            *decision_optional_source_refs(decision, notebook=notebook),
        ]
    )


def decision_required_source_refs(
    decision: dict[str, Any],
    *,
    notebook: dict[str, Any],
) -> list[str]:
    """Return sources that must succeed before the proposal can be adjudicated."""

    candidate_by_id = {
        str(row["candidate_id"]): row for row in notebook["candidates"]
    }
    materials = material_index(notebook)
    refs = [
        str(candidate_by_id[candidate_id]["source_table_id"])
        for candidate_id in decision["candidate_ids"]
        if candidate_id in candidate_by_id
    ]
    material_ids = [
        material_id
        for field in decision["field_evidence"]
        for material_id in field["material_ids"]
    ]
    refs.extend(
        str(
            materials[material_id].get("source_ref")
            or materials[material_id].get("source_table_id")
            or ""
        )
        for material_id in material_ids
        if material_id in materials
    )
    refs.extend(str(ref) for ref in decision.get("context_source_refs") or [])
    return unique_text(refs)


def decision_optional_source_refs(
    decision: dict[str, Any],
    *,
    notebook: dict[str, Any],
) -> list[str]:
    """Return audit-only sources that must not block selected evidence."""

    materials = material_index(notebook)
    required = set(decision_required_source_refs(decision, notebook=notebook))
    refs = [
        str(
            materials[material_id].get("source_ref")
            or materials[material_id].get("source_table_id")
            or ""
        )
        for material_id in decision.get("alternative_material_ids") or []
        if material_id in materials
    ]
    return [ref for ref in unique_text(refs) if ref not in required]


def decision_evidence_locators(
    decision: dict[str, Any],
    *,
    notebook: dict[str, Any],
) -> list[dict[str, Any]]:
    return unique_dicts(
        [
            *decision_required_evidence_locators(
                decision,
                notebook=notebook,
            ),
            *_decision_optional_evidence_locators(
                decision,
                notebook=notebook,
            ),
        ]
    )


def decision_required_evidence_locators(
    decision: dict[str, Any],
    *,
    notebook: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return locators for selected fields and explicit context sources."""

    materials = material_index(notebook)
    ids = [
        material_id
        for field in decision["field_evidence"]
        for material_id in field["material_ids"]
    ]
    locators: list[dict[str, Any]] = []
    for material_id in ids:
        material = materials.get(material_id)
        if not material:
            continue
        for source_window in material.get("source_windows") or []:
            locators.append(
                {
                    **deepcopy(source_window),
                    "source_quote": str(material.get("source_quote") or ""),
                }
            )
    context_refs = set(unique_text(decision.get("context_source_refs")))
    for evidence in notebook["study_map"].get("evidence") or []:
        if not context_refs.intersection(evidence.get("source_refs") or []):
            continue
        locators.extend(deepcopy(evidence.get("source_windows") or []))
    return unique_dicts(locators)


def _decision_optional_evidence_locators(
    decision: dict[str, Any],
    *,
    notebook: dict[str, Any],
) -> list[dict[str, Any]]:
    materials = material_index(notebook)
    locators: list[dict[str, Any]] = []
    for material_id in decision.get("alternative_material_ids") or []:
        material = materials.get(material_id)
        if not material:
            continue
        for source_window in material.get("source_windows") or []:
            locators.append(
                {
                    **deepcopy(source_window),
                    "source_quote": str(material.get("source_quote") or ""),
                }
            )
    return unique_dicts(locators)


def source_spans(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for material in materials:
        quote = str(material.get("source_quote") or "")
        source_ref = str(
            material.get("source_ref") or material.get("source_table_id") or ""
        )
        source_kind = str(material.get("source_kind") or "table")
        if quote and source_ref:
            rows.append(
                {
                    "source_id": source_ref,
                    "table_id": source_ref if source_kind == "table" else None,
                    "section": source_ref if source_kind == "section" else None,
                    "text": quote,
                    "source_windows": deepcopy(material.get("source_windows") or []),
                }
            )
    return unique_dicts(rows)


def _normalize_field_evidence(
    value: Any,
    *,
    material_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _object_list(value):
        field = str(raw.get("field") or "")
        if field not in FINAL_FIELDS or field in seen:
            raise ValueError(f"Invalid or duplicate final field: {field}")
        seen.add(field)
        ids = validated_ids(
            raw.get("material_ids"), set(material_by_id), "material"
        )
        if not ids:
            raise ValueError(f"Field {field} requires at least one material")
        rows.append({"field": field, "material_ids": ids})
    return rows


def _normalize_claims(value: Any, *, allowed_refs: set[str]) -> list[dict[str, Any]]:
    result = []
    for raw in _object_list(value):
        claim = str(raw.get("claim") or "").strip()
        scope = str(raw.get("scope") or "").strip()
        refs = validated_ids(raw.get("source_refs"), allowed_refs, "claim source")
        if claim and refs:
            result.append({"claim": claim, "scope": scope, "source_refs": refs})
    return result


def _normalize_alternatives(
    value: Any, *, allowed_refs: set[str]
) -> list[dict[str, Any]]:
    result = []
    for raw in _object_list(value):
        question = str(raw.get("question") or "").strip()
        interpretations = unique_text(raw.get("interpretations"))
        refs = validated_ids(
            raw.get("source_refs"), allowed_refs, "alternative source"
        )
        if question and interpretations and refs:
            result.append(
                {
                    "question": question,
                    "interpretations": interpretations,
                    "source_refs": refs,
                }
            )
    return result


def _merge_candidates(notebook: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    by_key = {str(row["candidate_key"]): row for row in notebook["candidates"]}
    for row in rows:
        by_key[str(row["candidate_key"])] = row
    notebook["candidates"] = list(by_key.values())


def _merge_support(notebook: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    by_id = {
        str(row["material_id"]): row for row in notebook["support_materials"]
    }
    for row in rows:
        by_id[str(row["material_id"])] = row
    notebook["support_materials"] = list(by_id.values())


def _payload_content(payloads: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in payloads:
        if not isinstance(row, dict):
            continue
        source_ref = str(row.get("source_ref") or "")
        content = str(row.get("raw_xml") or row.get("text") or "")
        if not source_ref:
            continue
        if source_ref in result:
            result[source_ref] = f"{result[source_ref]}\n{content}"
        else:
            result[source_ref] = content
    return result


def _payload_windows(
    payloads: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in payloads:
        if not isinstance(row, dict):
            continue
        source_ref = str(row.get("source_ref") or "")
        if not source_ref:
            continue
        locator = _transport_locator(row)
        locator["_content"] = str(row.get("raw_xml") or row.get("text") or "")
        result.setdefault(source_ref, []).append(locator)
    return result


def _transport_locator(row: dict[str, Any]) -> dict[str, Any]:
    transport = row.get("transport") if isinstance(row.get("transport"), dict) else {}
    return {
        "source_ref": str(row.get("source_ref") or ""),
        "source_kind": str(row.get("source_kind") or ""),
        "source_hash": str(row.get("source_hash") or ""),
        "transport": {
            "start": transport.get("start", 0),
            "end": transport.get("end", 0),
            "window_index": transport.get("window_index", 0),
            "window_count": transport.get("window_count", 1),
        },
    }


def _matching_source_windows(
    *,
    source_ref: str,
    source_kind: str,
    quote: str,
    source_windows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return windows whose visible source contains the quoted evidence."""

    fragments = [
        fragment.strip()
        for fragment in re.split(r"\s*(?:\.\.\.|\u2026)\s*", quote)
        if fragment.strip()
    ]
    matches: list[dict[str, Any]] = []
    for window in source_windows:
        content = str(window.get("_content") or "")
        if not content:
            continue
        visible = (
            stable_core._xml_text(content) if source_kind == "table" else content
        )
        if fragments and all(
            _quote_matches_visible_source(fragment, visible)
            for fragment in fragments
        ):
            matches.append(_transport_locator(window))
    if matches:
        return matches
    # A quote may intentionally bridge overlapping transport windows.  Keep all
    # windows for this source in that rare case; verification remains bounded by
    # the caller's source-window limits and the original source cap.
    return [_transport_locator(window) for window in source_windows]


def _available_source_refs(notebook: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for candidate in notebook.get("candidates") or []:
        refs.add(str(candidate.get("source_table_id") or ""))
    for material in material_index(notebook).values():
        refs.add(str(material.get("source_ref") or ""))
    for evidence in notebook.get("study_map", {}).get("evidence") or []:
        refs.update(str(ref) for ref in evidence.get("source_refs") or [])
    return {ref for ref in refs if ref}


def _quote_matches_visible_source(quote: str, visible_source: str) -> bool:
    """Validate copied visible evidence without assuming table separators.

    LLMs often render a table row with a pipe or omit an intervening cell while
    preserving the cited cell's text.  Continuous matching remains preferred;
    the fallback only accepts all alphanumeric tokens in source order.  It does
    not infer rows, columns, denominators, or values.
    """

    visible_quote = stable_core._xml_text(quote) if "<" in quote and ">" in quote else quote
    if stable_core._quote_matches_source(visible_quote, visible_source):
        return True
    source_tokens = [
        token.casefold() for token in re.findall(r"[A-Za-z0-9]+", visible_source)
    ]
    fragments = [
        [token.casefold() for token in re.findall(r"[A-Za-z0-9]+", fragment)]
        for fragment in re.split(r"\s*(?:\.\.\.|\u2026)\s*", visible_quote)
    ]
    cursor = 0
    for fragment in (row for row in fragments if row):
        for token in fragment:
            try:
                cursor = source_tokens.index(token, cursor) + 1
            except ValueError:
                return False
    return bool(source_tokens and cursor > 0)


def _blind_local_setting(value: dict[str, Any]) -> dict[str, Any]:
    """Keep semantic matching fields while excluding free-form result notes."""

    allowed = {
        "outcome_label",
        "outcome_measure",
        "unit",
        "timepoint",
        "population_or_subgroup",
        "analysis_population",
        "continuous_result_frame",
        "change_score_definition",
        "scale_direction",
        "reported_statistic_type",
        "statistic_type",
        "analysis_input_representation",
        "reported_statistic_kinds",
        "statistic_type_status",
    }
    result = {key: deepcopy(value[key]) for key in allowed if key in value}
    if "analysis_population" in result:
        result["analysis_population"] = _blind_numeric_text(
            result["analysis_population"]
        )
    return result


def _blind_numeric_text(value: Any) -> str | None:
    """Hide numeric result hints while retaining the surrounding semantic text."""

    if value is None:
        return None
    return re.sub(
        r"(?<![A-Za-z])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:\s*%)?",
        "[hidden]",
        str(value),
    )


def _support_local_setting(field_raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "outcome_label": None,
        "outcome_measure": None,
        "timepoint": None,
        "population_or_subgroup": None,
        "analysis_population": None,
    }


def validated_ids(value: Any, allowed: set[str], label: str) -> list[str]:
    result = unique_text(value)
    invalid = [item for item in result if item not in allowed]
    if invalid:
        raise ValueError(f"Unknown {label} id(s): {invalid}")
    return result


def optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def unique_text(values: Iterable[Any] | Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)) and not hasattr(values, "__iter__"):
        return []
    if isinstance(values, (str, bytes, dict)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def unique_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = _canonical(value)
        if key not in seen:
            seen.add(key)
            result.append(deepcopy(value))
    return result


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("Expected a list of objects")
    if any(not isinstance(row, dict) for row in value):
        raise ValueError("Every list item must be an object")
    return list(value)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
