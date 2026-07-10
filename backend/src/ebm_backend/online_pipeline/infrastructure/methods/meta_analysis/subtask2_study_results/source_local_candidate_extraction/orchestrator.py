"""Recall-first orchestrator for targeted extraction methods."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.config import LLMConfig
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.context import (
    ExtractionContext,
    required_fields,
    study_result_tasks,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.completion import (
    complete_candidates,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.debug_artifacts import (
    debug_dir_for,
    write_debug_artifact,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.finalizer import (
    build_study_result_row,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.progress import (
    ProgressLogger,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.skills.discover_candidates import (
    discover_candidates_from_source,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.skills.profile_source import (
    profile_source,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.tools.source_catalog import (
    build_source_catalog,
    source_summary,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.tools.source_signals import (
    build_source_signal_cache,
)


DEFAULT_ACTIVE_STATUSES = {"matched", "possible"}


def extract_study_result_rows(
    *,
    instance: dict[str, Any],
    articles: list[dict[str, Any]],
    config: LLMConfig | dict[str, Any],
    phase: str,
    progress: ProgressLogger | None = None,
) -> list[dict[str, Any]]:
    logger = progress or ProgressLogger(enabled=False)
    setting = instance.get("analysis_setting") or {}
    tasks = study_result_tasks(instance)
    if not tasks:
        return []
    workers = min(max(1, _env_int("SUBTASK2_TARGETED_TASK_WORKERS", 1)), len(tasks))
    if workers <= 1:
        return [
            _extract_one_task(
                instance=instance,
                setting=setting,
                target=task,
                articles=articles,
                config=config,
                phase=phase,
                logger=logger,
            )
            for task in tasks
        ]
    rows_by_index: list[dict[str, Any] | None] = [None] * len(tasks)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _extract_one_task,
                instance=instance,
                setting=setting,
                target=task,
                articles=articles,
                config=config,
                phase=phase,
                logger=logger,
            ): index
            for index, task in enumerate(tasks)
        }
        for future in as_completed(futures):
            rows_by_index[futures[future]] = future.result()
    return [row for row in rows_by_index if row is not None]


def _extract_one_task(
    *,
    instance: dict[str, Any],
    setting: dict[str, Any],
    target: dict[str, Any],
    articles: list[dict[str, Any]],
    config: LLMConfig | dict[str, Any],
    phase: str,
    logger: ProgressLogger,
) -> dict[str, Any]:
    study_id = str(target.get("study_id") or "")
    article = _article_for_target(target=target, articles=articles)
    if article is None:
        context = _context_for(instance=instance, setting=setting, target=target, study_id=study_id, article={})
        return build_study_result_row(
            context=context,
            candidates=[],
            sources=[],
            source_outputs=[],
            stage=phase,
        )

    context = _context_for(instance=instance, setting=setting, target=target, study_id=study_id, article=article)
    context_id = _debug_context_id(context)
    debug_path = debug_dir_for(context_id)
    logger.log("targeted extraction start", instance_id=context.instance_id, study_id=study_id, phase=phase)
    _write_checkpoint(
        path=debug_path,
        method="method_source_local_candidate_extraction",
        context=context,
        phase=phase,
        checkpoint_stage="start",
        extra={
            "target": target,
            "analysis_setting": setting,
        },
    )
    sources, source_audit = _prepare_sources(article)
    _write_checkpoint(
        path=debug_path,
        method="method_source_local_candidate_extraction",
        context=context,
        phase=phase,
        checkpoint_stage="sources_prepared",
        extra={
            "target": target,
            "analysis_setting": setting,
            "sources": [source_summary(source) for source in sources],
            "source_audit": source_audit,
        },
    )
    source_outputs = _discover_source_local_candidates(config=config, context=context, sources=sources)
    source_signal_cache = build_source_signal_cache(source_outputs)
    active_candidates = _active_candidates(source_outputs)
    _write_checkpoint(
        path=debug_path,
        method="method_source_local_candidate_extraction",
        context=context,
        phase=phase,
        checkpoint_stage="discovery_done",
        extra={
            "target": target,
            "analysis_setting": setting,
            "sources": [source_summary(source) for source in sources],
            "source_outputs": source_outputs,
            "source_signal_cache": source_signal_cache,
            "source_audit": source_audit,
            "active_candidates": active_candidates,
        },
    )
    completed_candidates = active_candidates
    completion_audit: dict[str, Any] | None = None
    if phase == "full":
        completed_candidates, completion_audit = complete_candidates(
            config=config,
            context=context,
            candidates=active_candidates,
            sources=sources,
            source_outputs=source_outputs,
            logger=logger,
            debug_path=debug_path,
            method_name="method_source_local_candidate_extraction",
        )
    row = build_study_result_row(
        context=context,
        candidates=completed_candidates,
        sources=sources,
        source_outputs=source_outputs,
        stage=phase,
        source_audit={**source_audit, "completion": completion_audit} if completion_audit is not None else source_audit,
    )
    write_debug_artifact(
        path=debug_path,
        payload={
            "method": "method_source_local_candidate_extraction",
            "instance_id": context.instance_id,
            "study_id": study_id,
            "checkpoint_stage": "final_row",
            "target": target,
            "analysis_setting": setting,
            "sources": [source_summary(source) for source in sources],
            "source_outputs": source_outputs,
            "source_signal_cache": source_signal_cache,
            "source_audit": source_audit,
            "active_candidates": active_candidates,
            "completed_candidates": completed_candidates,
            "completion_audit": completion_audit,
            "final_row": row,
        },
    )
    logger.log(
        "targeted extraction done",
        instance_id=context.instance_id,
        study_id=study_id,
        phase=phase,
        sources=len(sources),
        candidates=len(completed_candidates),
    )
    return row


def _write_checkpoint(
    *,
    path: Any,
    method: str,
    context: ExtractionContext,
    phase: str,
    checkpoint_stage: str,
    extra: dict[str, Any],
) -> None:
    write_debug_artifact(
        path=path,
        payload={
            "method": method,
            "instance_id": context.instance_id,
            "study_id": context.study_id,
            "phase": phase,
            "checkpoint_stage": checkpoint_stage,
            **extra,
        },
    )


def _context_for(
    *,
    instance: dict[str, Any],
    setting: dict[str, Any],
    target: dict[str, Any],
    study_id: str,
    article: dict[str, Any],
) -> ExtractionContext:
    return ExtractionContext(
        instance_id=str(instance.get("instance_id") or ""),
        analysis_setting=setting,
        target=target,
        study_id=study_id,
        article=article,
        required_fields=required_fields(setting.get("data_type") or target.get("data_type")),
    )


def _article_for_target(*, target: dict[str, Any], articles: list[dict[str, Any]]) -> dict[str, Any] | None:
    article_id = str(target.get("article_id") or "")
    study_id = str(target.get("study_id") or "")
    if article_id:
        for article in articles:
            if str(article.get("article_id") or "") == article_id:
                return article
    if study_id:
        for article in articles:
            if str(article.get("study_id") or "") == study_id:
                return article
    return articles[0] if articles else None


def _prepare_sources(article: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_sources = build_source_catalog(article)
    sources = _bounded_sources([source for source in all_sources if str(source.get("source_type") or "") == "table"])
    return sources, {
        "total_source_count": len(all_sources),
        "read_source_count": len(sources),
        "skipped_source_count": max(0, len(all_sources) - len(sources)),
        "source_cap": _optional_env_int("SUBTASK2_TARGETED_MAX_SOURCES"),
        "coverage_truncated": len(sources) < len(all_sources),
        "source_type_counts": _source_type_counts(all_sources),
        "read_source_type_counts": _source_type_counts(sources),
    }


def _bounded_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_sources = _optional_env_int("SUBTASK2_TARGETED_MAX_SOURCES")
    if max_sources is None or max_sources <= 0:
        return sources
    return sources[:max_sources]


def _discover_source_local_candidates(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not sources:
        return []
    workers = min(max(1, _env_int("SUBTASK2_TARGETED_SOURCE_WORKERS", 4)), len(sources))
    if workers <= 1:
        return [_discover_one_source(config=config, context=context, source=source) for source in sources]
    outputs_by_index: list[dict[str, Any] | None] = [None] * len(sources)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_discover_one_source, config=config, context=context, source=source): index
            for index, source in enumerate(sources)
        }
        for future in as_completed(futures):
            outputs_by_index[futures[future]] = future.result()
    return [output for output in outputs_by_index if output is not None]


def _discover_one_source(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    source: dict[str, Any],
) -> dict[str, Any]:
    candidate_output, profile_output = _read_source_semantics(config=config, context=context, source=source)
    source_id = str(source.get("source_id") or "")
    warnings: list[str] = []
    for raw in candidate_output.get("warnings") or []:
        if raw not in warnings:
            warnings.append(raw)
    for raw in profile_output.get("warnings") or []:
        if raw not in warnings:
            warnings.append(raw)
    return {
        "status": candidate_output.get("status") or profile_output.get("status"),
        "brief_summary": candidate_output.get("brief_summary") or profile_output.get("brief_summary"),
        "source_id": source_id,
        "source_type": source.get("source_type"),
        "source_profile": profile_output.get("source_profile") if isinstance(profile_output.get("source_profile"), dict) else {},
        "candidates": [
            _candidate_from_model(
                context=context,
                source_id=source_id,
                index=index,
                raw_candidate=candidate,
            )
            for index, candidate in enumerate(candidate_output.get("candidates") or [], start=1)
            if isinstance(candidate, dict)
        ],
        "warnings": warnings,
    }


def _read_source_semantics(
    *,
    config: LLMConfig | dict[str, Any],
    context: ExtractionContext,
    source: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    workers = min(max(1, _env_int("SUBTASK2_TARGETED_SOURCE_SKILL_WORKERS", 2)), 2)
    if workers <= 1:
        return (
            discover_candidates_from_source(config=config, context=context, source=source),
            profile_source(config=config, context=context, source=source),
        )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        candidate_future = executor.submit(discover_candidates_from_source, config=config, context=context, source=source)
        profile_future = executor.submit(profile_source, config=config, context=context, source=source)
        return candidate_future.result(), profile_future.result()


def _candidate_from_model(
    *,
    context: ExtractionContext,
    source_id: str,
    index: int,
    raw_candidate: dict[str, Any],
) -> dict[str, Any]:
    match_status = _candidate_match_status(context=context, raw_candidate=raw_candidate)
    setting = raw_candidate.get("source_local_result_setting")
    if not isinstance(setting, dict):
        setting = raw_candidate.get("study_result_setting")
    note = raw_candidate.get("source_local_note")
    if note is None:
        note = raw_candidate.get("study_local_note")
    return {
        "candidate_id": f"targeted::{_slug(source_id)}::{index}",
        "source_id": source_id,
        "source_ids": [source_id] if source_id else [],
        "match_status": match_status,
        "candidate_data_type": raw_candidate.get("candidate_data_type"),
        "study_result_setting": _dict_value(setting),
        "study_local_result": _dict_value(raw_candidate.get("study_local_result")),
        "study_local_note": _clean_text(note),
        "alignment_rationale": _clean_text(raw_candidate.get("alignment_rationale")),
        "uncertainties": raw_candidate.get("uncertainties") if isinstance(raw_candidate.get("uncertainties"), list) else [],
        "confidence": raw_candidate.get("confidence"),
    }


def _active_candidates(source_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for output in source_outputs:
        for candidate in output.get("candidates") or []:
            if _normalize_match_status(candidate.get("match_status")) in DEFAULT_ACTIVE_STATUSES:
                candidates.append(candidate)
    return candidates


def _candidate_match_status(*, context: ExtractionContext, raw_candidate: dict[str, Any]) -> str:
    status = _normalize_match_status(raw_candidate.get("match_status"))
    candidate_data_type = str(raw_candidate.get("candidate_data_type") or "").strip().lower()
    target_data_type = str(context.data_type or "").strip().lower()
    if status in {"matched", "possible"} and candidate_data_type and target_data_type:
        if candidate_data_type not in {"mixed", "unclear"} and candidate_data_type != target_data_type:
            return "related"
    return status


def _debug_context_id(context: ExtractionContext) -> str:
    task_id = str(context.target.get("extraction_task_id") or context.target.get("target_id") or "")
    if task_id:
        return f"{context.instance_id}::{task_id}"
    return f"{context.instance_id}::{context.study_id}"


def _source_type_counts(sources: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in sources:
        source_type = str(source.get("source_type") or "unknown")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _normalize_match_status(value: Any) -> str:
    text = str(value or "possible").strip().lower()
    if text in {"match", "matched", "selected", "candidate"}:
        return "matched"
    if text == "possible":
        return "possible"
    if text == "related":
        return "related"
    return "rejected"


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_text(value: Any) -> str | None:
    text = " ".join(str(value).split()) if value else ""
    return text or None


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value).strip("-") or "source"


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
