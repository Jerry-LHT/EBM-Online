"""Build StudyResultRow dictionaries from targeted extraction candidates."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.context import (
    ExtractionContext,
)


DEFAULT_ACTIVE_STATUSES = {"matched", "possible"}


def build_study_result_row(
    *,
    context: ExtractionContext,
    candidates: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    source_outputs: list[dict[str, Any]],
    stage: str,
    source_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    visible_items = [_candidate_item(context=context, candidate=candidate, stage=stage) for candidate in candidates]
    visible_items = [item for item in visible_items if item is not None]
    status = _row_status(visible_items)
    reason = _status_reason(status=status, visible_items=visible_items, sources=sources, stage=stage)
    setting = context.analysis_setting
    return {
        "row_id": context.target.get("target_id") or context.target.get("row_id") or f"{context.setting_id}::{context.study_id}",
        "setting_id": context.setting_id,
        "study_id": context.study_id,
        "extraction_task_id": context.target.get("extraction_task_id"),
        "study_year": context.target.get("study_year"),
        "extraction_status": status,
        "extraction_status_reason": reason,
        "data_type": context.data_type,
        "comparison": _comparison(setting.get("comparison") or {}),
        "outcome": _outcome(setting=setting),
        "subgroup": setting.get("subgroup") or {},
        "source_spans": _source_spans(visible_items),
        "result_items": visible_items,
        "study_result_note": reason,
        "notes": reason,
        "source": {
            "method": "method_source_local_candidate_extraction",
            "phase": stage,
            "source_count": len(sources),
            "source_audit": source_audit or {},
            "candidate_status_counts": _candidate_status_counts(source_outputs),
            "source_outputs": _source_output_summaries(source_outputs),
        },
    }


def _candidate_item(*, context: ExtractionContext, candidate: dict[str, Any], stage: str) -> dict[str, Any] | None:
    match_status = _normalize_match_status(candidate.get("match_status"))
    if match_status not in DEFAULT_ACTIVE_STATUSES:
        return None
    candidate_id = str(candidate.get("candidate_id") or "")
    source_ids = _source_ids(candidate)
    study_result_setting = candidate.get("study_result_setting") if isinstance(candidate.get("study_result_setting"), dict) else {}
    study_local_result = candidate.get("study_local_result") if isinstance(candidate.get("study_local_result"), dict) else {}
    completion = candidate.get("completion") if isinstance(candidate.get("completion"), dict) else {}
    result_data = completion.get("result_data") if isinstance(completion.get("result_data"), dict) else {}
    numeric_extraction = completion.get("numeric_extraction") if isinstance(completion.get("numeric_extraction"), dict) else {
        "fields": {},
        "missing_fields": context.required_fields,
        "phase": "not_run",
    }
    disposition = _analysis_disposition(match_status=match_status, completion=completion)
    resolution_reason = _resolution_reason(stage=stage, completion=completion)
    return {
        "candidate_id": candidate_id,
        "match_status": match_status,
        "study_result_setting": study_result_setting,
        "data_type": context.data_type,
        "result_data": result_data,
        "include_in_estimate": disposition == "ready_for_estimate",
        "analysis_disposition": disposition,
        "resolution_reason": resolution_reason,
        "derivation": completion.get("derivation"),
        "source_spans": [{"source_id": sid, "label": sid, "quote": None} for sid in source_ids],
        "confidence": candidate.get("confidence"),
        "study_local_note": candidate.get("study_local_note"),
        "study_local_result": study_local_result,
        "setting_alignment": {
            "alignment_rationale": candidate.get("alignment_rationale"),
            "uncertainties": candidate.get("uncertainties") or [],
        },
        "numeric_extraction": numeric_extraction,
        "note": candidate.get("study_local_note"),
    }


def _row_status(visible_items: list[dict[str, Any]]) -> str:
    if not visible_items:
        return "data_unavailable"
    ready = [item for item in visible_items if item.get("analysis_disposition") == "ready_for_estimate"]
    if len(ready) == 1 and len(visible_items) == 1:
        return "extracted"
    if len(visible_items) > 1:
        return "ambiguous"
    if any(item.get("analysis_disposition") == "needs_resolution" for item in visible_items):
        return "partial"
    return "candidate_only"


def _status_reason(*, status: str, visible_items: list[dict[str, Any]], sources: list[dict[str, Any]], stage: str) -> str:
    if status == "data_unavailable":
        if not sources:
            return f"{stage}: no article sources available"
        return f"{stage}: no matched or possible article-local candidate recovered"
    if status == "extracted":
        return f"{stage}: completed one active candidate with full result_data"
    if status == "ambiguous":
        return f"{stage}: recovered {len(visible_items)} active candidates"
    if status == "partial":
        return f"{stage}: one active candidate recovered but required fields remain incomplete"
    return f"{stage}: active candidates recovered without estimate-ready numeric completion"


def _comparison(comparison: dict[str, Any]) -> dict[str, Any]:
    return {
        "experimental_arm": comparison.get("experimental") or comparison.get("experimental_arm"),
        "control_arm": comparison.get("comparator") or comparison.get("control_arm"),
    }


def _outcome(*, setting: dict[str, Any]) -> dict[str, Any]:
    outcome = setting.get("outcome") if isinstance(setting.get("outcome"), dict) else {}
    timepoint = setting.get("timepoint") if isinstance(setting.get("timepoint"), dict) else {}
    return {
        "label": outcome.get("label"),
        "timepoint": timepoint.get("label"),
    }


def _source_spans(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans = []
    seen = set()
    for item in items:
        for span in item.get("source_spans") or []:
            source_id = str(span.get("source_id") or "")
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            spans.append(span)
    return spans


def _source_ids(candidate: dict[str, Any]) -> list[str]:
    values = candidate.get("source_ids") if isinstance(candidate.get("source_ids"), list) else []
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "")
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _source_output_summaries(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for output in outputs:
        summaries.append(
            {
                "source_id": output.get("source_id"),
                "candidate_count": len(output.get("candidates") or []),
                "warnings": output.get("warnings") or [],
            }
        )
    return summaries


def _candidate_status_counts(outputs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for output in outputs:
        for candidate in output.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            status = _normalize_match_status(candidate.get("match_status"))
            counts[status] = counts.get(status, 0) + 1
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


def _analysis_disposition(*, match_status: str, completion: dict[str, Any]) -> str:
    result_state = str(completion.get("result_state") or "")
    result_data = completion.get("result_data")
    if result_state == "complete" and isinstance(result_data, dict) and result_data:
        return "ready_for_estimate" if match_status == "matched" else "needs_resolution"
    if result_state in {"partial", "ambiguous", "unresolved"}:
        return "needs_resolution"
    return "candidate_only"


def _resolution_reason(*, stage: str, completion: dict[str, Any]) -> str:
    if not completion:
        return f"{stage}: candidate semantics only; numeric completion not run"
    missing = ((completion.get("numeric_extraction") or {}).get("missing_fields") or []) if isinstance(completion.get("numeric_extraction"), dict) else []
    result_state = str(completion.get("result_state") or "unresolved")
    if result_state == "complete":
        return f"{stage}: completed required numeric fields"
    if missing:
        return f"{stage}: incomplete; missing fields: {', '.join(str(field) for field in missing)}"
    return f"{stage}: result_state={result_state}"
