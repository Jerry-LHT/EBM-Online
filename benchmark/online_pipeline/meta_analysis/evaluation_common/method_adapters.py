"""Benchmark-side method adapters for meta-analysis subtasks."""

from __future__ import annotations

from copy import deepcopy
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.factory import (
    build_production_study_evidence_agent as build_study_evidence_method,
)
from benchmark.online_pipeline.meta_analysis.subtask3_analysis_methods.methods.method_test import (
    build_method as build_analysis_methods_method,
)
from benchmark.online_pipeline.meta_analysis.subtask4_subgroup_analysis.methods.method_test import (
    build_method as build_subgroup_analysis_method,
)
from benchmark.online_pipeline.meta_analysis.subtask5_overall_estimates.methods.method_test import (
    build_method as build_overall_estimates_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.analysis_method_selection.contextual.method import (
    build_method as build_production_analysis_methods_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subgroup_analysis.statistical.method import (
    build_method as build_production_subgroup_analysis_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.overall_estimation.statistical.method import (
    build_method as build_production_overall_estimates_method,
)
from benchmark.online_pipeline.meta_analysis.evaluation_common.article_store import load_articles_for_instance


def predict_subtask2(
    *,
    instance: dict[str, Any],
    gold: dict[str, Any],
    method: str,
    dataset_dir: str | Path,
    llm_config: str | Path | None = None,
    hint_policy: str = "none",
) -> dict[str, Any]:
    targets = build_subtask2_targets(instance=instance, gold=gold, hint_policy=hint_policy)
    if method in {"gold", "official_csv_oracle", "subtask2_official_csv_oracle"}:
        if gold.get("study_result_candidate_sets"):
            return {
                "instance_id": instance["instance_id"],
                "review_id": instance["review_id"],
                "study_result_rows": _gold_candidate_sets_as_rows(
                    gold.get("study_result_candidate_sets") or [],
                    analysis_setting=instance.get("analysis_setting") or {},
                ),
            }
        return {
            "instance_id": instance["instance_id"],
            "review_id": instance["review_id"],
            "study_result_rows": _gold_rows_with_target_ids(gold.get("study_result_rows") or [], targets=targets),
    }
    if method == "method_article_evidence_agent":
        articles = load_articles_for_instance(dataset_dir=dataset_dir, instance=instance)
        setting = instance.get("analysis_setting") or {}
        evidence_targets = [
            _article_evidence_target(target=target, setting=setting)
            for target in targets
        ]
        with _temporary_subtask2_llm_config(llm_config):
            method_obj = build_study_evidence_method()
            rows: list[dict[str, Any]] = []
            for article in articles:
                study_id = str(article.get("study_id") or "")
                study_targets = [
                    target
                    for target in evidence_targets
                    if str(target.get("study_id") or "") == study_id
                ]
                if not study_id or not study_targets:
                    continue
                result = method_obj.run(
                    review_id=str(instance["review_id"]),
                    targets=study_targets,
                    study_id=study_id,
                    article=article,
                    plan_hash=str(instance.get("plan_hash") or instance.get("instance_id") or "benchmark"),
                )
                rows.extend(result.get("study_result_rows") or [])
            return {
                "instance_id": instance["instance_id"],
                "review_id": instance["review_id"],
                "study_result_rows": rows,
            }
    raise ValueError(f"Unknown Subtask 2 method: {method}")


@contextmanager
def _temporary_subtask2_llm_config(llm_config: str | Path | None):
    if llm_config is None:
        yield
        return
    old_value = os.environ.get("LLM_CONFIG_PATH")
    os.environ["LLM_CONFIG_PATH"] = str(llm_config)
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop("LLM_CONFIG_PATH", None)
        else:
            os.environ["LLM_CONFIG_PATH"] = old_value


def _article_evidence_target(
    *,
    target: dict[str, Any],
    setting: dict[str, Any],
) -> dict[str, Any]:
    """Add the frozen case setting without consulting benchmark gold values."""

    return {
        **target,
        "population_scope": setting.get("population_scope"),
        "comparison": setting.get("comparison"),
        "outcome": setting.get("outcome"),
        "timepoint": setting.get("timepoint"),
        "subgroup": setting.get("subgroup"),
        "data_type": setting.get("data_type"),
        "result_selection_policy": setting.get("result_selection_policy"),
        "effect_measure_plan": setting.get("effect_measure_plan"),
    }


def build_subtask2_tasks(*, instance: dict[str, Any], gold: dict[str, Any] | None = None, hint_policy: str = "none") -> list[dict[str, Any]]:
    setting = instance.get("analysis_setting") or {}
    setting_id = str(setting.get("setting_id") or instance.get("instance_id") or "setting")
    article_id_by_study = {
        str(link.get("study_id") or ""): str(link.get("article_id") or "")
        for link in instance.get("article_study_links") or []
        if link.get("study_id")
    }
    tasks: list[dict[str, Any]] = []
    for candidate in setting.get("eligible_study_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        study_id = str(candidate.get("study_id") or "")
        if not study_id:
            continue
        task_id = str(candidate.get("extraction_task_id") or _task_id(setting_id=setting_id, study_id=study_id))
        tasks.append(
            _task_payload(
                extraction_task_id=task_id,
                setting_id=setting_id,
                study_id=study_id,
                article_id=_clean_hint_text(candidate.get("article_id")) or article_id_by_study.get(study_id),
                extraction_hint=_hint_from_parts(
                    candidate.get("extraction_hint_parts"),
                    policy=hint_policy,
                    fallback=_candidate_legacy_hint(candidate),
                ),
            )
        )
    if tasks:
        return tasks
    if gold and gold.get("study_result_candidate_sets"):
        return [
            _task_payload(
                extraction_task_id=str(item.get("extraction_task_id") or _task_id(setting_id=setting_id, study_id=str(item.get("study_id") or ""))),
                setting_id=str(item.get("setting_id") or setting_id),
                study_id=str(item.get("study_id") or ""),
                article_id=_clean_hint_text(item.get("article_id")),
                extraction_hint=_hint_from_parts(item.get("extraction_hint_parts"), policy=hint_policy),
            )
            for item in gold.get("study_result_candidate_sets") or []
            if item.get("study_id")
        ]
    return [
        _task_payload(
            extraction_task_id=_task_id(setting_id=setting_id, study_id=str(study_id)),
            setting_id=setting_id,
            study_id=str(study_id),
            article_id=article_id_by_study.get(str(study_id)),
            extraction_hint=None,
        )
        for study_id in (instance.get("included_studies") or [])
    ]


def _task_payload(
    *,
    extraction_task_id: str,
    setting_id: str,
    study_id: str,
    article_id: str | None,
    extraction_hint: str | None,
) -> dict[str, Any]:
    payload = {
        "extraction_task_id": extraction_task_id,
        "target_id": extraction_task_id,
        "setting_id": setting_id,
        "study_id": study_id,
        "article_id": article_id,
    }
    if extraction_hint:
        payload["extraction_hint"] = extraction_hint
    return payload


def build_subtask2_targets(*, instance: dict[str, Any], gold: dict[str, Any] | None = None, hint_policy: str = "none") -> list[dict[str, Any]]:
    setting = instance.get("analysis_setting") or {}
    setting_id = str(setting.get("setting_id") or instance.get("instance_id") or "setting")
    article_id_by_study = {
        str(link.get("study_id") or ""): str(link.get("article_id") or "")
        for link in instance.get("article_study_links") or []
        if link.get("study_id")
    }
    planned_targets = _targets_from_eligible_study_candidates(setting=setting, setting_id=setting_id, article_id_by_study=article_id_by_study, hint_policy=hint_policy)
    if planned_targets and gold is None:
        return planned_targets
    if planned_targets and gold is not None and gold.get("study_result_rows"):
        return _targets_in_gold_row_order(gold_rows=gold.get("study_result_rows") or [], planned_targets=planned_targets, setting_id=setting_id)
    if planned_targets:
        return planned_targets
    if gold is not None and gold.get("study_result_rows"):
        rows = list(gold.get("study_result_rows") or [])
        counts: dict[tuple[str, str], int] = {}
        hints_by_study = _source_context_hints_by_study(instance.get("source_context") or {})
        targets = []
        for row in rows:
            study_id = str(row.get("study_id") or "")
            key = (str(row.get("setting_id") or setting_id), study_id)
            slot = counts.get(key, 0)
            counts[key] = slot + 1
            targets.append(
                {
                    "target_id": _target_id(setting_id=key[0], study_id=study_id, slot=slot),
                    "setting_id": key[0],
                    "study_id": study_id,
                    "article_id": article_id_by_study.get(study_id),
                    "slot": slot,
                    "extraction_hint": _hint_from_parts(
                        _legacy_extraction_hint_parts(setting=setting, hints=hints_by_study.get(study_id) or [], slot=slot),
                        policy=hint_policy,
                        fallback=_target_extraction_hint_from_source_context(hints=hints_by_study.get(study_id) or [], slot=slot),
                    ),
                }
            )
        return targets
    linked_study_ids = list(dict.fromkeys(article_id_by_study))
    included_study_ids = [str(study_id) for study_id in instance.get("included_studies") or []]
    study_ids = linked_study_ids or included_study_ids
    return [
        {
            "target_id": _target_id(setting_id=setting_id, study_id=study_id, slot=0),
            "setting_id": setting_id,
            "study_id": study_id,
            "article_id": article_id_by_study.get(study_id),
            "slot": 0,
            "extraction_hint": None,
        }
        for study_id in study_ids
    ]


def _targets_from_eligible_study_candidates(
    *,
    setting: dict[str, Any],
    setting_id: str,
    article_id_by_study: dict[str, str],
    hint_policy: str = "none",
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for candidate in setting.get("eligible_study_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        study_id = str(candidate.get("study_id") or "")
        if not study_id:
            continue
        article_id = _clean_hint_text(candidate.get("article_id")) or article_id_by_study.get(study_id)
        extraction_targets = candidate.get("extraction_targets") or []
        if not extraction_targets:
            extraction_targets = [
                {
                    "target_id": _target_id(setting_id=setting_id, study_id=study_id, slot=0),
                    "extraction_hint": _hint_from_parts(
                        candidate.get("extraction_hint_parts"),
                        policy=hint_policy,
                        fallback=_candidate_legacy_hint(candidate),
                    ),
                }
            ]
        for slot, target in enumerate(extraction_targets):
            if not isinstance(target, dict):
                continue
            targets.append(
                {
                    "target_id": str(target.get("target_id") or _target_id(setting_id=setting_id, study_id=study_id, slot=slot)),
                    "setting_id": str(target.get("setting_id") or setting_id),
                    "study_id": study_id,
                    "article_id": _clean_hint_text(target.get("article_id")) or article_id,
                    "slot": slot,
                    "extraction_hint": _hint_from_parts(
                        target.get("extraction_hint_parts") or candidate.get("extraction_hint_parts"),
                        policy=hint_policy,
                        fallback=target.get("extraction_hint") or _candidate_legacy_hint(candidate),
                    ),
                }
            )
    return targets


def _targets_in_gold_row_order(*, gold_rows: list[dict[str, Any]], planned_targets: list[dict[str, Any]], setting_id: str) -> list[dict[str, Any]]:
    targets_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    counters: dict[str, int] = {}
    for target in planned_targets:
        study_id = str(target.get("study_id") or "")
        slot = counters.get(study_id, 0)
        counters[study_id] = slot + 1
        targets_by_key[(study_id, slot)] = target
    row_counters: dict[str, int] = {}
    ordered: list[dict[str, Any]] = []
    for row in gold_rows:
        study_id = str(row.get("study_id") or "")
        slot = row_counters.get(study_id, 0)
        row_counters[study_id] = slot + 1
        target = targets_by_key.get((study_id, slot))
        if target is not None:
            ordered.append(target)
        else:
            ordered.append(
                {
                    "target_id": _target_id(setting_id=str(row.get("setting_id") or setting_id), study_id=study_id, slot=slot),
                    "setting_id": str(row.get("setting_id") or setting_id),
                    "study_id": study_id,
                    "article_id": None,
                    "slot": slot,
                    "extraction_hint": None,
                }
            )
    return ordered


def _hint_from_parts(parts: Any, *, policy: str, fallback: Any = None) -> str | None:
    normalized_policy = str(policy or "none").strip().lower()
    if normalized_policy in {"", "none", "off", "false", "0"}:
        return None
    if not isinstance(parts, dict):
        if normalized_policy in {"full", "row_hint", "footnote_only", "legacy"}:
            return _clean_hint_text(fallback)
        return None
    if normalized_policy == "legacy":
        return _clean_hint_text(fallback)

    lines: list[str] = []
    if normalized_policy in {"full", "analysis_labels", "analysis_name", "analysis_name_subgroup"}:
        analysis_name = _clean_hint_text(parts.get("analysis_name"))
        if analysis_name:
            lines.append(f"Analysis name: {analysis_name}")
    if normalized_policy in {"full", "analysis_labels", "analysis_name_subgroup"}:
        analysis_group_name = _clean_hint_text(parts.get("analysis_group_name"))
        if analysis_group_name:
            lines.append(f"Analysis group name: {analysis_group_name}")
        setting_subgroup = _clean_hint_text(parts.get("setting_subgroup"))
        if setting_subgroup:
            lines.append(f"Setting subgroup: {setting_subgroup}")
    if normalized_policy in {"full", "row_hint", "footnote_only", "legacy"}:
        row_hints = parts.get("study_row_hints") if isinstance(parts.get("study_row_hints"), list) else []
        rendered = []
        for hint in row_hints:
            if not isinstance(hint, dict):
                continue
            pieces = []
            subgroup = _clean_hint_text(hint.get("subgroup"))
            footnote = _clean_hint_text(hint.get("footnote"))
            applicability = _clean_hint_text(hint.get("applicability"))
            if subgroup:
                pieces.append(f"subgroup={subgroup}")
            if footnote:
                pieces.append(f"footnote={footnote}")
            if applicability:
                pieces.append(f"applicability={applicability}")
            if pieces:
                rendered.append("; ".join(pieces))
        if rendered:
            lines.append("Study row hints: " + " | ".join(rendered))
        elif normalized_policy in {"full", "row_hint", "footnote_only", "legacy"}:
            fallback_text = _clean_hint_text(fallback)
            if fallback_text:
                lines.append(fallback_text)
    return _clean_hint_text("\n".join(lines))


def _candidate_legacy_hint(candidate: dict[str, Any]) -> str | None:
    for target in candidate.get("extraction_targets") or []:
        if isinstance(target, dict):
            text = _clean_hint_text(target.get("extraction_hint"))
            if text:
                return text
    return _clean_hint_text(candidate.get("extraction_hint"))


def _legacy_extraction_hint_parts(*, setting: dict[str, Any], hints: list[dict[str, Any]], slot: int) -> dict[str, Any]:
    subgroup = setting.get("subgroup") if isinstance(setting.get("subgroup"), dict) else {}
    hint = hints[slot] if slot < len(hints) else None
    return {
        "analysis_name": _clean_hint_text(setting.get("analysis_name")),
        "analysis_group_name": _clean_hint_text(setting.get("analysis_group_name")),
        "setting_subgroup": _clean_hint_text(subgroup.get("level")),
        "study_row_hints": [
            {
                "subgroup": _clean_hint_text(hint.get("subgroup")),
                "footnote": _clean_hint_text(hint.get("footnote")),
                "applicability": _clean_hint_text(hint.get("applicability")),
            }
        ]
        if isinstance(hint, dict)
        else [],
        "source": "official_analysis_non_numeric_context",
    }


def _clean_hint_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _source_context_hints_by_study(source_context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    hints_by_study: dict[str, list[dict[str, Any]]] = {}
    for item in source_context.get("study_row_footnotes") or []:
        if not isinstance(item, dict):
            continue
        study_id = str(item.get("study_id") or "")
        if not study_id:
            continue
        hints_by_study.setdefault(study_id, []).append(item)
    for hints in hints_by_study.values():
        hints.sort(key=lambda item: _optional_int(item.get("row_index")) or 0)
    return hints_by_study


def _target_extraction_hint_from_source_context(*, hints: list[dict[str, Any]], slot: int) -> str | None:
    hint = hints[slot] if slot < len(hints) else None
    if hint is None:
        return None
    values = [hint.get("subgroup"), hint.get("footnote")]
    return _clean_hint_text(" ; ".join(str(value) for value in values if value))


def _optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _gold_rows_with_target_ids(rows: list[dict[str, Any]], *, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated = []
    for row, target in zip(rows, targets):
        existing_items = row.get("result_items") if isinstance(row.get("result_items"), list) else None
        if existing_items is not None:
            updated_row = {key: value for key, value in row.items() if key != "candidate_results"}
            updated.append({**updated_row, "row_id": target["target_id"], "result_items": existing_items})
            continue
        result_data = row.get("result_data") if isinstance(row.get("result_data"), dict) else None
        result_item = {
            "candidate_id": f"gold-candidate::{row.get('row_id') or target['target_id']}",
            "source_row_id": row.get("row_id"),
            "match_status": "matched",
            "analysis_disposition": "ready_for_estimate",
            "include_in_estimate": True,
            "study_result_setting": {
                "row_label": (row.get("subgroup") or {}).get("level"),
                "outcome_label": (row.get("outcome") or {}).get("label"),
                "timepoint": (row.get("outcome") or {}).get("timepoint"),
                "experimental_arm_label": (row.get("comparison") or {}).get("experimental_arm"),
                "control_arm_label": (row.get("comparison") or {}).get("control_arm"),
                "table_local_notes": row.get("footnote"),
            },
            "data_type": row.get("data_type"),
            "result_data": result_data,
            "source": row.get("source") or {},
        }
        updated_row = {key: value for key, value in row.items() if key not in {"result_data", "candidate_results"}}
        updated.append({**updated_row, "row_id": target["target_id"], "result_items": [result_item]})
    return updated


def targetize_subtask2_gold(*, instance: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    if gold.get("study_result_candidate_sets"):
        return gold
    targets = build_subtask2_targets(instance=instance, gold=gold)
    return {
        **gold,
        "study_result_rows": _gold_rows_with_target_ids(gold.get("study_result_rows") or [], targets=targets),
    }


def _target_id(*, setting_id: str, study_id: str, slot: int) -> str:
    return f"target::{setting_id}::{_slug(study_id)}::{slot}"


def _task_id(*, setting_id: str, study_id: str) -> str:
    return f"task::{setting_id}::{_slug(study_id)}"


def _gold_candidate_sets_as_rows(candidate_sets: list[dict[str, Any]], *, analysis_setting: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    comparison = analysis_setting.get("comparison") or {}
    outcome = analysis_setting.get("outcome") or {}
    subgroup = analysis_setting.get("subgroup") or {}
    for candidate_set in candidate_sets:
        candidates = candidate_set.get("gold_candidate_results") if isinstance(candidate_set.get("gold_candidate_results"), list) else []
        estimable = [
            {
                **candidate,
                "match_status": "matched",
                "analysis_disposition": "ready_for_estimate",
                "include_in_estimate": True,
            }
            for candidate in candidates
            if isinstance(candidate, dict)
        ]
        rows.append(
            {
                "row_id": str(candidate_set.get("extraction_task_id") or ""),
                "setting_id": candidate_set.get("setting_id") or analysis_setting.get("setting_id"),
                "study_id": candidate_set.get("study_id"),
                "study_year": None,
                "extraction_status": "extracted",
                "data_type": analysis_setting.get("data_type"),
                "comparison": {
                    "experimental_arm": comparison.get("experimental"),
                    "control_arm": comparison.get("comparator"),
                },
                "outcome": {
                    "label": outcome.get("label"),
                    "timepoint": (analysis_setting.get("timepoint") or {}).get("label"),
                },
                "subgroup": subgroup,
                "result_items": estimable,
                "source": {"method": "official_csv_oracle", "article_id": candidate_set.get("article_id")},
            }
        )
    return rows


def _slug(value: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return cleaned or "study"


def predict_subtask3(*, instance: dict[str, Any], gold: dict[str, Any], method: str) -> dict[str, Any]:
    if method in {"gold", "official_csv_oracle", "subtask3_official_csv_oracle"}:
        return {
            "instance_id": instance["instance_id"],
            "review_id": instance["review_id"],
            "analysis_methods": gold.get("analysis_methods") or [],
        }
    if method in {"method_test", "analysis_methods_rule_v1"}:
        method_obj = build_analysis_methods_method()
        return {
            "instance_id": instance["instance_id"],
            "review_id": instance["review_id"],
            "analysis_methods": method_obj.run(instance=instance),
        }
    if method in {"method_production", "contextual_v1"}:
        method_obj = build_production_analysis_methods_method()
        production_instance = _production_compatible_instance(instance)
        return {
            "instance_id": instance["instance_id"],
            "review_id": instance["review_id"],
            "analysis_methods": method_obj.run(instance=production_instance),
        }
    raise ValueError(f"Unknown Subtask 3 method: {method}")


def predict_subtask4(*, instances: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]], method: str) -> list[dict[str, Any]]:
    if method in {"gold", "official_csv_oracle", "subtask4_official_csv_oracle"}:
        return [
            {
                "instance_id": instance["instance_id"],
                "review_id": instance["review_id"],
                "subgroup_results": (gold_by_id[str(instance["instance_id"])].get("subgroup_results") or {"subgroup_estimates": [], "subgroup_difference_tests": []}),
            }
            for instance in instances
        ]
    if method in {"method_test", "stats_pooling_v1"}:
        method_obj = build_subgroup_analysis_method()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for instance in instances:
            family_id = str(instance["analysis_setting"]["setting_family_id"])
            grouped.setdefault(family_id, []).append(instance)
        predictions_by_id: dict[str, dict[str, Any]] = {}
        for family_instances in grouped.values():
            family_payload = method_obj.run(instances=family_instances)
            predictions_by_id.update(family_payload)
        return [
            {
                "instance_id": instance["instance_id"],
                "review_id": instance["review_id"],
                "subgroup_results": predictions_by_id.get(str(instance["instance_id"]), {"subgroup_estimates": [], "subgroup_difference_tests": []}),
            }
            for instance in instances
        ]
    if method in {"method_production", "statistical_v1"}:
        method_obj = build_production_subgroup_analysis_method()
        grouped: dict[str, list[dict[str, Any]]] = {}
        production_instances = [
            _production_compatible_instance(instance) for instance in instances
        ]
        for production_instance in production_instances:
            family_id = str(
                production_instance["analysis_setting"]["setting_family_id"]
            )
            grouped.setdefault(family_id, []).append(production_instance)
        predictions_by_id: dict[str, dict[str, Any]] = {}
        for family_instances in grouped.values():
            family_payload = method_obj.run(instances=family_instances)
            instances_by_id = {
                str(item["instance_id"]): item for item in family_instances
            }
            for instance_id, payload in family_payload.items():
                predictions_by_id[instance_id] = _with_benchmark_candidate_ids(
                    payload,
                    instance=instances_by_id[instance_id],
                )
        return [
            {
                "instance_id": instance["instance_id"],
                "review_id": instance["review_id"],
                "subgroup_results": predictions_by_id.get(str(instance["instance_id"]), {"subgroup_estimates": [], "subgroup_difference_tests": []}),
            }
            for instance in instances
        ]
    raise ValueError(f"Unknown Subtask 4 method: {method}")


def predict_subtask5(*, instance: dict[str, Any], gold: dict[str, Any], method: str) -> dict[str, Any]:
    if method in {"gold", "official_csv_oracle", "subtask5_official_csv_oracle"}:
        return {
            "instance_id": instance["instance_id"],
            "review_id": instance["review_id"],
            "overall_estimates": gold.get("overall_estimates") or [],
        }
    if method in {"method_test", "stats_pooling_v1"}:
        method_obj = build_overall_estimates_method()
        return {
            "instance_id": instance["instance_id"],
            "review_id": instance["review_id"],
            "overall_estimates": method_obj.run(instance=instance),
        }
    if method in {"method_production", "statistical_v1"}:
        method_obj = build_production_overall_estimates_method()
        production_instance = _production_compatible_instance(instance)
        payload = method_obj.run(instance=production_instance)
        if isinstance(payload, list):
            payload = {"overall_estimates": payload}
        estimates = _rows_with_benchmark_candidate_id(
            payload.get("overall_estimates") or [],
            instance=instance,
        )
        return {
            "instance_id": instance["instance_id"],
            "review_id": instance["review_id"],
            "overall_estimates": estimates,
        }
    raise ValueError(f"Unknown Subtask 5 method: {method}")


def _production_compatible_instance(instance: dict[str, Any]) -> dict[str, Any]:
    """Adapt legacy benchmark rows without weakening the backend contract.

    Historical Subtask 3-5 datasets predate explicit endpoint/change and SMD
    direction metadata. Their continuous values were already evaluated in the
    reported direction, so the benchmark adapter marks them as pre-aligned
    post-intervention rows. Real backend workflows must obtain this metadata
    from planning, extraction, and candidate resolution.
    """

    result = deepcopy(instance)
    setting = (
        result.get("analysis_setting")
        if isinstance(result.get("analysis_setting"), dict)
        else {}
    )
    if str(setting.get("data_type") or "") != "Continuous":
        return result
    source_context = (
        setting.get("source_context")
        if isinstance(setting.get("source_context"), dict)
        else {}
    )
    definition = (
        source_context.get("setting_definition")
        if isinstance(source_context.get("setting_definition"), dict)
        else {}
    )
    definition.setdefault("continuous_result_frame_priority", ["post_intervention"])
    source_context["setting_definition"] = definition
    setting["source_context"] = source_context
    result["analysis_setting"] = setting

    legacy_rows = result.get("meta_analysis_data_rows")
    if not isinstance(legacy_rows, list):
        legacy_rows = result.get("study_result_rows") or []
    data_rows = []
    for row in legacy_rows:
        if not isinstance(row, dict):
            continue
        normalized = dict(row)
        normalized.setdefault("data_row_id", normalized.get("row_id") or f"data-row::{normalized.get('study_id')}")
        normalized.setdefault("setting_family_id", setting.get("setting_family_id") or setting.get("setting_id"))
        data_rows.append(normalized)
    result["meta_analysis_data_rows"] = data_rows

    alignment = {
        "result_frame": "post_intervention",
        "change_score_definition": "not_applicable",
        "scale_direction": "higher_is_better",
        "effect_multiplier": 1,
        "status": "ready",
        "rationale": "Legacy benchmark row treated as already direction-aligned.",
    }
    for row in result.get("meta_analysis_data_rows") or []:
        if not isinstance(row, dict):
            continue
        row.setdefault("continuous_effect_alignment", dict(alignment))
        for field in ("result_items", "candidate_results"):
            for item in row.get(field) or []:
                if isinstance(item, dict):
                    item.setdefault("continuous_effect_alignment", dict(alignment))
    return result


def _with_benchmark_candidate_ids(
    payload: dict[str, Any],
    *,
    instance: dict[str, Any],
) -> dict[str, Any]:
    return {
        **payload,
        "subgroup_estimates": _rows_with_benchmark_candidate_id(
            payload.get("subgroup_estimates") or [],
            instance=instance,
        ),
        "subgroup_difference_tests": _rows_with_benchmark_candidate_id(
            payload.get("subgroup_difference_tests") or [],
            instance=instance,
        ),
    }


def _rows_with_benchmark_candidate_id(
    rows: list[dict[str, Any]],
    *,
    instance: dict[str, Any],
) -> list[dict[str, Any]]:
    setting = (
        instance.get("analysis_setting")
        if isinstance(instance.get("analysis_setting"), dict)
        else {}
    )
    candidate_id = str(
        setting.get("candidate_id") or setting.get("setting_family_id") or ""
    )
    return [
        {**row, "candidate_id": candidate_id}
        for row in rows
        if isinstance(row, dict)
    ]
