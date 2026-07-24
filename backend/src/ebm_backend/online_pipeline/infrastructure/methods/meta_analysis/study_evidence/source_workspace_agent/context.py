"""Stage-specific context compilation and request budgeting."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import re
from typing import Any, Iterable

from .evidence_state import candidate_summary, material_summary
from .source_workspace import SourceWorkspace
from .working_state import active_evidence_needs


DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
MIN_ALIAS_CHARS = 32
REQUEST_OVERHEAD_TOKENS = 512
MIN_PROVIDER_HEADROOM_TOKENS = 2_048


@dataclass(frozen=True)
class CallAliases:
    real_to_alias: dict[str, str]

    @classmethod
    def build(
        cls,
        groups: Iterable[tuple[str, Iterable[Any]]],
    ) -> "CallAliases":
        mapping: dict[str, str] = {}
        all_values: set[str] = set()
        normalized_groups: list[tuple[str, list[str]]] = []
        for prefix, values in groups:
            rows = _unique_text(values)
            normalized_groups.append((prefix, rows))
            all_values.update(rows)
        used_aliases: set[str] = set()
        for prefix, values in normalized_groups:
            alias_index = 1
            for value in values:
                if len(value) < MIN_ALIAS_CHARS or value in mapping:
                    continue
                alias = f"@{prefix}{alias_index:02d}"
                while alias in all_values or alias in used_aliases:
                    alias_index += 1
                    alias = f"@{prefix}{alias_index:02d}"
                mapping[value] = alias
                used_aliases.add(alias)
                alias_index += 1
        return cls(real_to_alias=mapping)

    @property
    def alias_to_real(self) -> dict[str, str]:
        return {alias: real for real, alias in self.real_to_alias.items()}

    def encode(self, value: Any) -> Any:
        return _replace_exact_strings(value, self.real_to_alias)

    def decode(self, value: Any) -> Any:
        return _replace_exact_strings(value, self.alias_to_real)

    def artifact_map(self) -> dict[str, str]:
        return dict(sorted(self.alias_to_real.items()))


@dataclass(frozen=True)
class StageContext:
    payload: dict[str, Any]
    aliases: CallAliases


def compile_census_context(
    *,
    targets: list[dict[str, Any]],
    source_payloads: list[dict[str, Any]],
) -> StageContext:
    payload = {
        "task": "coverage_oriented_raw_table_census",
        "targets": [census_target(row) for row in targets],
        "sources": model_source_payloads(source_payloads),
        "source_boundary": (
            "This request contains raw windows from exactly one table source. "
            "Each candidate and supporting material must remain local to that "
            "source; cross-table relationships are resolved later."
        ),
    }
    return _stage_context(
        payload,
        targets=targets,
        source_refs=[row.get("source_ref") for row in source_payloads],
    )


def compile_investigation_context(
    *,
    targets: list[dict[str, Any]],
    workspace: SourceWorkspace,
    notebook: dict[str, Any],
    latest_sources: list[dict[str, Any]],
    remaining_budget: dict[str, int],
    context_budget_exceeded: bool,
    max_total_chars: int,
    source_bundle_status: dict[str, Any] | None = None,
) -> StageContext:
    bundle_status = deepcopy(source_bundle_status or {})
    bundle_status.setdefault(
        "char_budget_limited", bool(context_budget_exceeded)
    )
    bundle_status["context_budget_exceeded"] = bool(context_budget_exceeded)
    bundle_status["max_total_chars"] = max_total_chars
    payload = {
        "task": "need_scoped_article_evidence_investigation",
        "targets": [investigation_target(row) for row in targets],
        "source_catalog": model_source_manifest(workspace),
        "evidence_notebook": {
            "study_map": compact_study_map(notebook.get("study_map") or {}),
            "source_arm_observations": _source_arm_observations(notebook),
            "candidates": [
                navigation_candidate(row) for row in notebook.get("candidates") or []
            ],
            "support_materials": [
                navigation_material(row)
                for row in notebook.get("support_materials") or []
            ],
            "active_evidence_needs": active_evidence_needs(notebook),
            "open_questions": list((notebook.get("open_questions") or [])[-16:]),
            "claims": deepcopy((notebook.get("claims") or [])[-16:]),
            "alternatives": deepcopy((notebook.get("alternatives") or [])[-16:]),
        },
        "latest_raw_sources": model_source_payloads(latest_sources),
        "source_bundle_status": bundle_status,
        "remaining_budget": remaining_budget,
    }
    return _stage_context(
        payload,
        targets=targets,
        source_refs=[*workspace.table_refs, *workspace.section_refs],
        candidate_ids=[row.get("candidate_id") for row in notebook.get("candidates") or []],
        material_ids=_material_ids(notebook),
        arm_ids=_arm_ids(notebook),
        need_ids=[row.get("need_id") for row in active_evidence_needs(notebook)],
    )


def compile_arm_context(
    *,
    observations: list[dict[str, Any]],
    notebook: dict[str, Any],
) -> StageContext:
    payload = {
        "task": "reconcile_source_local_article_arms",
        "source_local_arm_observations": deepcopy(observations),
        "investigator_study_map": compact_study_map(
            notebook.get("investigator_study_map") or {}
        ),
        "source_arm_maps": _source_arm_maps(notebook),
        "identity_boundary": {
            "generic_role_labels_are_not_identity": True,
            "every_observation_requires_one_disposition": True,
            "engineering_assigns_arm_ids": True,
        },
    }
    return _stage_context(
        payload,
        source_refs=[row.get("source_ref") for row in observations],
        candidate_ids=[
            candidate_id
            for row in observations
            for candidate_id in row.get("candidate_ids") or []
        ],
        observation_ids=[row.get("observation_id") for row in observations],
    )


def compile_resolution_context(
    *,
    targets: list[dict[str, Any]],
    notebook: dict[str, Any],
    table_coverage_complete: bool | None = None,
    investigation_status: str = "finished",
    coverage_complete: bool | None = None,
) -> StageContext:
    if table_coverage_complete is None:
        table_coverage_complete = bool(coverage_complete)
    payload = {
        "task": "result_blind_article_contribution_resolution",
        "targets": [resolution_target(row) for row in targets],
        "selection_boundary": {
            "hidden": [
                "numeric_values",
                "effect_direction",
                "effect_magnitude",
                "confidence_interval_values",
                "p_values",
            ],
            "table_coverage_complete": bool(table_coverage_complete),
            "investigation_status": investigation_status,
        },
        "evidence_notebook": {
            "study_map": compact_study_map(
                notebook.get("study_map") or {}, blind_numeric=True
            ),
            "candidates": [
                resolution_candidate(row) for row in notebook.get("candidates") or []
            ],
            "support_materials": [
                resolution_material(row)
                for row in notebook.get("support_materials") or []
            ],
            "ambiguities": {
                "claims": deepcopy(notebook.get("claims") or []),
                "alternatives": deepcopy(notebook.get("alternatives") or []),
                "open_questions": list(notebook.get("open_questions") or []),
                "active_evidence_needs": active_evidence_needs(notebook),
            },
        },
    }
    return _stage_context(
        payload,
        targets=targets,
        source_refs=_source_refs(notebook),
        candidate_ids=[row.get("candidate_id") for row in notebook.get("candidates") or []],
        material_ids=_material_ids(notebook),
        arm_ids=_arm_ids(notebook),
        need_ids=[row.get("need_id") for row in active_evidence_needs(notebook)],
    )


def compile_source_verification_context(
    *,
    targets: list[dict[str, Any]],
    supported_representations: list[dict[str, Any]],
    notebook: dict[str, Any],
    proposals: list[dict[str, Any]],
    candidate_ids: list[str],
    source_materials: list[dict[str, Any]],
    source_payloads: list[dict[str, Any]],
    source_ref: str,
    source_kind: str,
    context_budget_exceeded: bool,
    source_bundle_status: dict[str, Any] | None = None,
) -> StageContext:
    bundle_status = deepcopy(source_bundle_status or {})
    bundle_status.setdefault(
        "char_budget_limited", bool(context_budget_exceeded)
    )
    bundle_status["context_budget_exceeded"] = bool(context_budget_exceeded)
    payload = {
        "task": "verify_one_raw_source_for_proposed_contributions",
        "targets": [verification_target(row) for row in targets],
        "supported_result_representations": deepcopy(supported_representations),
        "study_map": compact_study_map(notebook.get("study_map") or {}),
        "arm_identity": compact_arm_identity(notebook.get("arm_identity") or {}),
        "proposals": deepcopy(proposals),
        "candidate_context": [
            verification_candidate(candidate)
            for candidate in notebook.get("candidates") or []
            if str(candidate.get("candidate_id") or "") in set(candidate_ids)
        ],
        "support_material_context": [
            verification_material(row) for row in source_materials
        ],
        "raw_source": model_source_payloads(source_payloads),
        "source_boundary": {
            "source_ref": source_ref,
            "source_kind": source_kind,
            "contains_other_raw_sources": False,
            "context_budget_exceeded": context_budget_exceeded,
            "transport_status": bundle_status,
        },
    }
    return _stage_context(
        payload,
        targets=targets,
        source_refs=[source_ref],
        candidate_ids=candidate_ids,
        material_ids=_material_ids(notebook),
        arm_ids=_arm_ids(notebook),
    )


def compile_adjudication_context(
    *,
    targets: list[dict[str, Any]],
    supported_representations: list[dict[str, Any]],
    notebook: dict[str, Any],
    proposals: list[dict[str, Any]],
    source_reviews: list[dict[str, Any]],
    verification_dependencies: list[dict[str, Any]] | None = None,
) -> StageContext:
    payload = {
        "task": "adjudicate_verified_cross_source_evidence",
        "targets": [resolution_target(row) for row in targets],
        "supported_result_representations": deepcopy(supported_representations),
        "study_map": compact_study_map(notebook.get("study_map") or {}),
        "arm_identity": compact_arm_identity(notebook.get("arm_identity") or {}),
        "proposals": deepcopy(proposals),
        "verified_source_reviews": deepcopy(source_reviews),
        "verification_dependencies": deepcopy(
            verification_dependencies or []
        ),
        "raw_sources_included": False,
    }
    return _stage_context(
        payload,
        targets=targets,
        source_refs=_source_refs(notebook),
        candidate_ids=[row.get("candidate_id") for row in notebook.get("candidates") or []],
        material_ids=_material_ids(notebook),
        arm_ids=_arm_ids(notebook),
        evidence_ids=[
            evidence.get("evidence_id")
            for review in source_reviews
            for evidence in review.get("verified_evidence") or []
        ],
    )


def census_target(target: dict[str, Any]) -> dict[str, Any]:
    return _target_core(target)


def investigation_target(target: dict[str, Any]) -> dict[str, Any]:
    return _target_core(target)


def resolution_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        **_target_core(target),
        "result_selection_policy": operative_selection_policy(
            target.get("result_selection_policy") or {}
        ),
        "effect_measure_plan": target.get("effect_measure_plan"),
    }


def verification_target(target: dict[str, Any]) -> dict[str, Any]:
    return resolution_target(target)


def operative_selection_policy(policy: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "acceptable_outcome_measures",
        "outcome_measure_priority",
        "analysis_population_priority",
        "continuous_result_frame_priority",
        "statistic_type_priority",
        "source_priority",
        "tie_policy",
    )
    return {key: deepcopy(policy.get(key)) for key in keys}


def model_source_manifest(workspace: SourceWorkspace) -> dict[str, Any]:
    def row(source: Any) -> dict[str, Any]:
        return {
            "source_ref": source.source_ref,
            "source_kind": source.source_kind,
            "title": source.title,
            "char_count": source.char_count,
        }

    return {
        "tables": [row(source) for source in workspace.tables],
        "sections": [row(source) for source in workspace.sections],
    }


def model_source_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in payloads:
        transport = row.get("transport") if isinstance(row.get("transport"), dict) else {}
        source_kind = str(row.get("source_kind") or "")
        content_key = "raw_xml" if source_kind == "table" else "text"
        model_row = {
            "source_ref": row.get("source_ref"),
            "source_kind": source_kind,
            "title": row.get("title"),
            "window": {
                "kind": transport.get("kind"),
                "window_index": transport.get("window_index", 0),
                "window_count": transport.get("window_count", 1),
            },
            content_key: row.get(content_key),
        }
        limit_reasons = list(row.get("transport_limit_reasons") or [])
        if row.get("context_budget_exceeded") and (
            not limit_reasons or "char_budget_limited" in limit_reasons
        ):
            model_row["context_budget_exceeded"] = True
        if limit_reasons:
            model_row["transport_limit_reasons"] = limit_reasons
        result.append(model_row)
    return result


def compact_study_map(
    study_map: dict[str, Any],
    *,
    blind_numeric: bool = False,
) -> dict[str, Any]:
    result = {
        "study_design": study_map.get("study_design"),
        "population": study_map.get("population"),
        "treatment_duration": study_map.get("treatment_duration"),
        "follow_up": list(study_map.get("follow_up") or []),
        "analysis_populations": list(study_map.get("analysis_populations") or []),
        "arms": [
            {
                key: deepcopy(arm.get(key))
                for key in ("arm_id", "label", "aliases", "role", "description")
                if key in arm
            }
            for arm in study_map.get("arms") or []
            if isinstance(arm, dict)
        ],
        "evidence": [
            {
                "fact": row.get("fact"),
                "source_refs": list(row.get("source_refs") or []),
            }
            for row in study_map.get("evidence") or []
            if isinstance(row, dict)
        ],
    }
    return _blind_numeric_strings(result) if blind_numeric else result


def compact_arm_identity(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_arms": deepcopy(value.get("canonical_arms") or []),
        "unresolved": list(value.get("unresolved") or []),
        "observation_to_arm_id": deepcopy(value.get("observation_to_arm_id") or {}),
    }


def navigation_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    summary = candidate_summary(candidate, include_values=False)
    return {
        "candidate_id": summary.get("candidate_id"),
        "source_table_id": summary.get("source_table_id"),
        "data_type": summary.get("data_type"),
        "local_setting": summary.get("local_setting"),
        "arms": [
            {
                "label": arm.get("label"),
                "article_arm_id": arm.get("article_arm_id"),
                "identity_status": arm.get("identity_status"),
                "reported_material_kinds": _unique_text(
                    material.get("kind") for material in arm.get("materials") or []
                ),
            }
            for arm in summary.get("arms") or []
        ],
        "has_uncertainties": summary.get("has_uncertainties"),
    }


def navigation_material(material: dict[str, Any]) -> dict[str, Any]:
    summary = material_summary(material, include_values=False)
    return {
        key: summary.get(key)
        for key in (
            "material_id",
            "kind",
            "statistical_scope",
            "applies_to",
            "arm_label",
            "article_arm_id",
            "identity_status",
            "local_setting",
            "source_ref",
            "source_kind",
            "reported_components",
            "has_uncertainties",
        )
    }


def resolution_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    summary = candidate_summary(candidate, include_values=False)
    for arm in summary.get("arms") or []:
        for material in arm.get("materials") or []:
            material.pop("local_setting", None)
            material.pop("interpretation", None)
            material.pop("uncertainties", None)
            material.pop("trace_warnings", None)
    return summary


def resolution_material(material: dict[str, Any]) -> dict[str, Any]:
    return material_summary(material, include_values=False)


def verification_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return resolution_candidate(candidate)


def verification_material(material: dict[str, Any]) -> dict[str, Any]:
    return material_summary(material, include_values=False)


def request_input_summary(
    *,
    config: dict[str, Any],
    system: str,
    payload: dict[str, Any],
    schema: dict[str, Any],
    max_output_tokens: int,
    alias_map: dict[str, str],
) -> dict[str, Any]:
    context_window = int(
        config.get("context_window_tokens") or DEFAULT_CONTEXT_WINDOW_TOKENS
    )
    provider_headroom = max(MIN_PROVIDER_HEADROOM_TOKENS, context_window // 20)
    system_summary = _value_size(system)
    schema_summary = _value_size(schema)
    payload_components = {
        str(key): _value_size(value) for key, value in payload.items()
    }
    payload_summary = _value_size(payload)
    estimated_input = (
        system_summary["estimated_tokens"]
        + schema_summary["estimated_tokens"]
        + payload_summary["estimated_tokens"]
        + REQUEST_OVERHEAD_TOKENS
    )
    input_budget = max(0, context_window - max_output_tokens - provider_headroom)
    return {
        "task": payload.get("task"),
        "context_window_tokens": context_window,
        "input_token_budget": input_budget,
        "estimated_input_tokens": estimated_input,
        "max_output_tokens": max_output_tokens,
        "provider_headroom_tokens": provider_headroom,
        "estimated_total_context_tokens": estimated_input + max_output_tokens,
        "fits_context_window": estimated_input <= input_budget,
        "components": {
            "system": system_summary,
            "payload": payload_summary,
            "schema": schema_summary,
            "provider_overhead": {
                "chars": 0,
                "utf8_bytes": 0,
                "estimated_tokens": REQUEST_OVERHEAD_TOKENS,
            },
        },
        "payload_components": payload_components,
        "top_level_keys": list(payload),
        "alias_count": len(alias_map),
    }


def estimate_tokens(value: Any) -> int:
    serialized = _serialize(value)
    if not serialized:
        return 0
    return max(1, (len(serialized.encode("utf-8")) + 3) // 4)


def _stage_context(
    payload: dict[str, Any],
    *,
    targets: Iterable[dict[str, Any]] = (),
    source_refs: Iterable[Any] = (),
    candidate_ids: Iterable[Any] = (),
    material_ids: Iterable[Any] = (),
    arm_ids: Iterable[Any] = (),
    observation_ids: Iterable[Any] = (),
    need_ids: Iterable[Any] = (),
    evidence_ids: Iterable[Any] = (),
) -> StageContext:
    aliases = CallAliases.build(
        [
            ("T", (row.get("target_id") for row in targets)),
            ("S", source_refs),
            ("C", candidate_ids),
            ("M", material_ids),
            ("A", arm_ids),
            ("O", observation_ids),
            ("N", need_ids),
            ("E", evidence_ids),
        ]
    )
    return StageContext(payload=payload, aliases=aliases)


def _target_core(target: dict[str, Any]) -> dict[str, Any]:
    timepoint = target.get("timepoint") if isinstance(target.get("timepoint"), dict) else {}
    subgroup = target.get("subgroup") if isinstance(target.get("subgroup"), dict) else {}
    return {
        "target_id": target.get("target_id"),
        "population_scope": target.get("population_scope"),
        "comparison": deepcopy(target.get("comparison") or {}),
        "outcome": deepcopy(target.get("outcome") or {}),
        "timepoint": {
            key: deepcopy(timepoint.get(key))
            for key in (
                "label",
                "strategy",
                "target_value",
                "window_start",
                "window_end",
                "unit",
                "anchor",
            )
        },
        "subgroup": {
            key: deepcopy(subgroup.get(key))
            for key in ("factor", "level", "scope", "membership_relation")
        },
        "data_type": target.get("data_type"),
    }


def _source_arm_observations(notebook: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_map in notebook.get("source_study_maps") or []:
        study_map = source_map.get("study_map") or {}
        rows.append(
            {
                "source_ref": source_map.get("source_ref"),
                "arms": deepcopy(study_map.get("arms") or []),
            }
        )
    return rows


def _source_arm_maps(notebook: dict[str, Any]) -> list[dict[str, Any]]:
    return _source_arm_observations(notebook)


def _source_refs(notebook: dict[str, Any]) -> list[str]:
    refs: list[Any] = []
    for candidate in notebook.get("candidates") or []:
        refs.append(candidate.get("source_table_id"))
    for material in notebook.get("support_materials") or []:
        refs.append(material.get("source_ref") or material.get("source_table_id"))
    for row in (notebook.get("study_map") or {}).get("evidence") or []:
        refs.extend(row.get("source_refs") or [])
    return _unique_text(refs)


def _material_ids(notebook: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for candidate in notebook.get("candidates") or []:
        for arm in candidate.get("arms") or []:
            values.extend(material.get("material_id") for material in arm.get("materials") or [])
    values.extend(
        material.get("material_id") for material in notebook.get("support_materials") or []
    )
    return _unique_text(values)


def _arm_ids(notebook: dict[str, Any]) -> list[str]:
    return _unique_text(
        arm.get("arm_id") for arm in (notebook.get("study_map") or {}).get("arms") or []
    )


def _replace_exact_strings(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_replace_exact_strings(row, mapping) for row in value]
    if isinstance(value, tuple):
        return tuple(_replace_exact_strings(row, mapping) for row in value)
    if isinstance(value, dict):
        return {
            key: _replace_exact_strings(row, mapping) for key, row in value.items()
        }
    return value


def _blind_numeric_strings(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(
            r"(?<![A-Za-z])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:\s*%)?",
            "[hidden]",
            value,
        )
    if isinstance(value, list):
        return [_blind_numeric_strings(row) for row in value]
    if isinstance(value, dict):
        return {key: _blind_numeric_strings(row) for key, row in value.items()}
    return value


def _value_size(value: Any) -> dict[str, int]:
    serialized = _serialize(value)
    return {
        "chars": len(serialized),
        "utf8_bytes": len(serialized.encode("utf-8")),
        "estimated_tokens": estimate_tokens(serialized),
    }


def _serialize(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _unique_text(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in result:
            result.append(value)
    return result
