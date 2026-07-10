"""Metrics for Meta Analysis Subtask 2 evaluation."""

from __future__ import annotations

from typing import Any

from benchmark.online_pipeline.meta_analysis.evaluation_common.metrics import _mean, _value_close


REQUIRED_FIELDS_BY_DATA_TYPE = {
    "Dichotomous": (
        "experimental_events",
        "experimental_total",
        "control_events",
        "control_total",
    ),
    "Continuous": (
        "experimental_mean",
        "experimental_sd",
        "experimental_total",
        "control_mean",
        "control_sd",
        "control_total",
    ),
}


def _value_fields_for_data_type(data_type: str) -> tuple[str, ...]:
    return tuple(field for field in REQUIRED_FIELDS_BY_DATA_TYPE.get(data_type, ()) if not field.endswith("_total"))


def _denominator_fields_for_data_type(data_type: str) -> tuple[str, ...]:
    return tuple(field for field in REQUIRED_FIELDS_BY_DATA_TYPE.get(data_type, ()) if field.endswith("_total"))


def build_comparisons(predictions: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if any(gold.get("study_result_candidate_sets") for gold in gold_by_id.values()):
        return _build_candidate_set_comparisons(predictions, gold_by_id)
    return _build_legacy_comparisons(predictions, gold_by_id)


def evaluate_predictions(predictions: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = build_comparisons(predictions, gold_by_id)
    if any(row.get("comparison_type") == "candidate_set" for row in rows):
        return _evaluate_candidate_set_rows(rows=rows, instance_count=len(gold_by_id))
    return _evaluate_legacy_rows(rows=rows, instance_count=len(gold_by_id))


def _build_candidate_set_comparisons(predictions: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    predictions_by_id = {str(row["instance_id"]): row for row in predictions}
    rows: list[dict[str, Any]] = []
    for instance_id, gold in gold_by_id.items():
        prediction = predictions_by_id.get(instance_id) or {"instance_id": instance_id, "study_result_rows": []}
        pred_rows_by_task = _prediction_rows_by_task(prediction.get("study_result_rows") or [])
        for candidate_set in gold.get("study_result_candidate_sets") or []:
            task_id = str(candidate_set.get("extraction_task_id") or "")
            pred_row = pred_rows_by_task.get(task_id)
            gold_candidates = _candidate_rows_from_gold_set(candidate_set)
            pred_candidates = _candidate_rows(pred_row)
            matched_pairs = _match_candidates(gold_candidates=gold_candidates, pred_candidates=pred_candidates)
            field_results = _candidate_set_field_results(gold_candidates=gold_candidates, pred_candidates=pred_candidates)
            value_only_field_results = _candidate_set_field_results(
                gold_candidates=gold_candidates,
                pred_candidates=pred_candidates,
                field_selector=_value_fields_for_data_type,
            )
            denominator_field_results = _candidate_set_field_results(
                gold_candidates=gold_candidates,
                pred_candidates=pred_candidates,
                field_selector=_denominator_fields_for_data_type,
            )
            estimable_pred = [candidate for candidate in pred_candidates if _is_ready_item(candidate)]
            estimable_pairs = _match_candidates(gold_candidates=gold_candidates, pred_candidates=estimable_pred)
            ready_pred = [candidate for candidate in pred_candidates if _is_ready_item(candidate)]
            ready_pairs = _match_candidates(gold_candidates=gold_candidates, pred_candidates=ready_pred)
            resolution_pred = [candidate for candidate in pred_candidates if str(candidate.get("analysis_disposition") or "") == "needs_resolution"]
            resolution_pairs = _match_candidates(gold_candidates=gold_candidates, pred_candidates=resolution_pred)
            value_only_pairs = _match_candidates(
                gold_candidates=gold_candidates,
                pred_candidates=pred_candidates,
                matcher=_candidate_value_only_close,
            )
            item_match_summaries = [
                _candidate_item_match_summary(gold_candidate=gold_candidate, pred_candidates=pred_candidates)
                for gold_candidate in gold_candidates
            ]
            rows.append(
                {
                    "comparison_type": "candidate_set",
                    "instance_id": instance_id,
                    "key": task_id,
                    "study_id": candidate_set.get("study_id"),
                    "gold_candidate_count": len(gold_candidates),
                    "pred_candidate_count": len(pred_candidates),
                    "matched_candidate_count": len(matched_pairs),
                    "value_only_matched_candidate_count": len(value_only_pairs),
                    "estimable_matched_candidate_count": len(estimable_pairs),
                    "ready_matched_candidate_count": len(ready_pairs),
                    "needs_resolution_matched_candidate_count": len(resolution_pairs),
                    "ready_candidate_count": len(ready_pred),
                    "needs_resolution_candidate_count": len(resolution_pred),
                    "extraction_status": str((pred_row or {}).get("extraction_status") or ""),
                    "covered": pred_row is not None,
                    "full_set_recalled": len(gold_candidates) > 0 and len(matched_pairs) == len(gold_candidates),
                    "candidate_item_match_summaries": item_match_summaries,
                    "field_results": field_results,
                    "value_only_field_results": value_only_field_results,
                    "denominator_field_results": denominator_field_results,
                    "review_label": candidate_set.get("review_label"),
                }
            )
    return rows


def _evaluate_candidate_set_rows(*, rows: list[dict[str, Any]], instance_count: int) -> dict[str, Any]:
    gold_total = sum(int(row["gold_candidate_count"]) for row in rows)
    pred_total = sum(int(row["pred_candidate_count"]) for row in rows)
    matched_total = sum(int(row["matched_candidate_count"]) for row in rows)
    value_only_matched_total = sum(int(row["value_only_matched_candidate_count"]) for row in rows)
    estimable_total = sum(int(row["estimable_matched_candidate_count"]) for row in rows)
    ready_total = sum(int(row.get("ready_matched_candidate_count") or 0) for row in rows)
    resolution_total = sum(int(row.get("needs_resolution_matched_candidate_count") or 0) for row in rows)
    field_rows = [field for row in rows for field in row["field_results"]]
    value_only_field_rows = [field for row in rows for field in row["value_only_field_results"]]
    denominator_field_rows = [field for row in rows for field in row["denominator_field_results"]]
    item_match_summaries = [
        summary
        for row in rows
        for summary in row.get("candidate_item_match_summaries") or []
    ]
    recall = matched_total / gold_total if gold_total else 0.0
    value_only_recall = value_only_matched_total / gold_total if gold_total else 0.0
    precision = matched_total / pred_total if pred_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "instance_count": instance_count,
        "comparison_count": len(rows),
        "evaluable_target_count": len(rows),
        "duplicate_gold_target_count": 0,
        "candidate_gold_row_count": gold_total,
        "candidate_pred_row_count": pred_total,
        "candidate_matched_row_count": matched_total,
        "candidate_row_recall": recall,
        "candidate_row_precision": precision,
        "candidate_row_f1": f1,
        "candidate_value_only_recall": value_only_recall,
        "candidate_item_complete_recall": recall,
        "candidate_item_any_value_recall": _mean([summary["any_value_match"] for summary in item_match_summaries]),
        "candidate_item_field_coverage": _numeric_mean([summary["field_coverage"] for summary in item_match_summaries]),
        "full_set_recall_rate": _mean([row["full_set_recalled"] for row in rows]),
        "field_recall_rate": _mean([row["close"] for row in field_rows]),
        "field_recall_rates": _field_close_rates(field_rows),
        "value_only_field_recall_rate": _mean([row["close"] for row in value_only_field_rows]),
        "value_only_field_recall_rates": _field_close_rates(value_only_field_rows),
        "denominator_field_recall_rate": _mean([row["close"] for row in denominator_field_rows]),
        "denominator_field_recall_rates": _field_close_rates(denominator_field_rows),
        "downstream_ready_rate": estimable_total / gold_total if gold_total else 0.0,
        "ready_item_numeric_close_rate": ready_total / gold_total if gold_total else 0.0,
        "needs_resolution_gold_item_rate": resolution_total / gold_total if gold_total else 0.0,
        "avg_ready_item_count": _numeric_mean([row.get("ready_candidate_count") for row in rows]),
        "avg_needs_resolution_item_count": _numeric_mean([row.get("needs_resolution_candidate_count") for row in rows]),
        "ambiguous_candidate_recall_rate": _mean(
            [row["matched_candidate_count"] > 0 for row in rows if row["extraction_status"] == "ambiguous"]
        ),
        "avg_gold_candidate_count": _numeric_mean([row["gold_candidate_count"] for row in rows]),
        "avg_pred_candidate_count": _numeric_mean([row["pred_candidate_count"] for row in rows]),
        # Legacy aliases for existing summaries.
        "target_completion_rate": _mean([row["covered"] for row in rows]),
        "target_extracted_rate": _mean([row["extraction_status"] == "extracted" for row in rows]),
        "target_numeric_close_rate": recall,
        "target_value_only_close_rate": value_only_recall,
        "field_close_rate": _mean([row["close"] for row in field_rows]),
        "field_close_rates": _field_close_rates(field_rows),
        "value_only_field_close_rate": _mean([row["close"] for row in value_only_field_rows]),
        "value_only_field_close_rates": _field_close_rates(value_only_field_rows),
        "denominator_field_close_rate": _mean([row["close"] for row in denominator_field_rows]),
        "denominator_field_close_rates": _field_close_rates(denominator_field_rows),
        "candidate_numeric_recall_rate": recall,
        "candidate_field_recall_rate": _mean([row["close"] for row in field_rows]),
        "candidate_field_recall_rates": _field_close_rates(field_rows),
        "candidate_value_only_field_recall_rate": _mean([row["close"] for row in value_only_field_rows]),
        "candidate_value_only_field_recall_rates": _field_close_rates(value_only_field_rows),
        "candidate_denominator_field_recall_rate": _mean([row["close"] for row in denominator_field_rows]),
        "candidate_denominator_field_recall_rates": _field_close_rates(denominator_field_rows),
        "ambiguous_with_gold_candidate_rate": _mean(
            [row["matched_candidate_count"] > 0 for row in rows if row["extraction_status"] == "ambiguous"]
        ),
        "avg_candidate_count": _numeric_mean([row["pred_candidate_count"] for row in rows]),
        "review_label_counts": _label_counts([str(row["review_label"]) for row in rows if row.get("review_label")]),
        **_audit_subset_metrics(rows),
    }


def _prediction_rows_by_task(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("extraction_task_id") or row.get("row_id") or "")
        indexed.setdefault(key, row)
    return indexed


def _candidate_rows_from_gold_set(candidate_set: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = candidate_set.get("gold_candidate_results") if isinstance(candidate_set.get("gold_candidate_results"), list) else []
    return [candidate for candidate in candidates if isinstance(candidate, dict)]


def _is_ready_item(candidate: dict[str, Any]) -> bool:
    disposition = str(candidate.get("analysis_disposition") or "").strip().lower()
    if disposition:
        return disposition == "ready_for_estimate"
    return candidate.get("include_in_estimate") is True


def _match_candidates(
    *,
    gold_candidates: list[dict[str, Any]],
    pred_candidates: list[dict[str, Any]],
    matcher: Any = None,
) -> list[tuple[int, int]]:
    if matcher is None:
        matcher = _candidate_numeric_close
    used_pred: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for gold_index, gold in enumerate(gold_candidates):
        for pred_index, pred in enumerate(pred_candidates):
            if pred_index in used_pred:
                continue
            if matcher(gold_candidate=gold, pred_candidate=pred):
                used_pred.add(pred_index)
                pairs.append((gold_index, pred_index))
                break
    return pairs


def _candidate_set_field_results(
    *,
    gold_candidates: list[dict[str, Any]],
    pred_candidates: list[dict[str, Any]],
    field_selector: Any = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for gold in gold_candidates:
        data_type = str(gold.get("data_type") or "")
        required_fields = field_selector(data_type) if field_selector is not None else REQUIRED_FIELDS_BY_DATA_TYPE.get(data_type, ())
        gold_data = gold.get("result_data") or {}
        for field in required_fields:
            rows.append(
                {
                    "field": field,
                    "close": any(
                        _value_close(gold_data.get(field), _candidate_field_value(candidate or {}, field), field=field)
                        for candidate in pred_candidates
                    ),
                }
            )
    return rows


def _candidate_numeric_close(*, gold_candidate: dict[str, Any], pred_candidate: dict[str, Any]) -> bool:
    data_type = str(gold_candidate.get("data_type") or pred_candidate.get("data_type") or "")
    required_fields = REQUIRED_FIELDS_BY_DATA_TYPE.get(data_type, ())
    if not required_fields:
        return False
    gold_data = gold_candidate.get("result_data") or {}
    pred_data = pred_candidate.get("result_data") or {}
    return all(_value_close(gold_data.get(field), pred_data.get(field), field=field) for field in required_fields)


def _candidate_value_only_close(*, gold_candidate: dict[str, Any], pred_candidate: dict[str, Any]) -> bool:
    data_type = str(gold_candidate.get("data_type") or pred_candidate.get("data_type") or "")
    required_fields = _value_fields_for_data_type(data_type)
    if not required_fields:
        return False
    gold_data = gold_candidate.get("result_data") or {}
    return all(_value_close(gold_data.get(field), _candidate_field_value(pred_candidate, field), field=field) for field in required_fields)


def _candidate_item_match_summary(
    *,
    gold_candidate: dict[str, Any],
    pred_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score one gold item against one best prediction item without field mixing."""

    data_type = str(gold_candidate.get("data_type") or "")
    required_fields = REQUIRED_FIELDS_BY_DATA_TYPE.get(data_type, ())
    if not required_fields:
        return {"matched_field_count": 0, "required_field_count": 0, "any_value_match": False, "field_coverage": 0.0}
    gold_data = gold_candidate.get("result_data") or {}
    best_count = 0
    for candidate in pred_candidates:
        candidate_data_type = str(candidate.get("data_type") or data_type)
        if candidate_data_type != data_type:
            continue
        matched_count = sum(
            _value_close(gold_data.get(field), _candidate_field_value(candidate, field), field=field)
            for field in required_fields
        )
        best_count = max(best_count, matched_count)
    return {
        "matched_field_count": best_count,
        "required_field_count": len(required_fields),
        "any_value_match": best_count > 0,
        "field_coverage": best_count / len(required_fields),
    }


def _build_legacy_comparisons(predictions: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    predictions_by_id = {str(row["instance_id"]): row for row in predictions}
    rows: list[dict[str, Any]] = []
    for instance_id, gold in gold_by_id.items():
        prediction = predictions_by_id.get(instance_id) or {"instance_id": instance_id}
        pred_rows_by_key = _prediction_rows_by_legacy_keys(prediction.get("study_result_rows") or [])
        used_prediction_rows: set[int] = set()
        for gold_row in gold.get("study_result_rows") or []:
            keys = _legacy_match_keys(gold_row)
            key = keys[0] if keys else ""
            pred_row, matched_key = _first_matching_prediction_row(
                pred_rows_by_key=pred_rows_by_key,
                keys=keys,
                used_prediction_rows=used_prediction_rows,
            )
            if pred_row is not None:
                used_prediction_rows.add(id(pred_row))
            field_results = _field_results(gold_row=gold_row, pred_row=pred_row)
            value_only_field_results = _field_results(
                gold_row=gold_row,
                pred_row=pred_row,
                field_selector=_value_fields_for_data_type,
            )
            denominator_field_results = _field_results(
                gold_row=gold_row,
                pred_row=pred_row,
                field_selector=_denominator_fields_for_data_type,
            )
            candidate_field_results = _legacy_candidate_field_results(gold_row=gold_row, pred_row=pred_row)
            candidate_value_only_field_results = _legacy_candidate_field_results(
                gold_row=gold_row,
                pred_row=pred_row,
                field_selector=_value_fields_for_data_type,
            )
            candidate_denominator_field_results = _legacy_candidate_field_results(
                gold_row=gold_row,
                pred_row=pred_row,
                field_selector=_denominator_fields_for_data_type,
            )
            item_match_summary = _candidate_item_match_summary(
                gold_candidate={
                    "data_type": gold_row.get("data_type"),
                    "result_data": _row_result_data(gold_row),
                },
                pred_candidates=_candidate_rows(pred_row),
            )
            rows.append(
                {
                    "comparison_type": "legacy_target",
                    "instance_id": instance_id,
                    "key": key,
                    "matched_key": matched_key,
                    "evaluable": True,
                    "duplicate_gold_key": False,
                    "covered": pred_row is not None,
                    "extraction_status": str((pred_row or {}).get("extraction_status") or ""),
                    "numeric_close": bool(field_results) and all(row["close"] for row in field_results),
                    "value_only_numeric_close": bool(value_only_field_results) and all(row["close"] for row in value_only_field_results),
                    "field_results": field_results,
                    "value_only_field_results": value_only_field_results,
                    "denominator_field_results": denominator_field_results,
                    "candidate_count": len(_candidate_rows(pred_row)),
                    "candidate_numeric_close": _legacy_candidate_numeric_close(gold_row=gold_row, pred_row=pred_row),
                    "candidate_value_only_close": _legacy_candidate_numeric_close(
                        gold_row=gold_row,
                        pred_row=pred_row,
                        field_selector=_value_fields_for_data_type,
                    ),
                    "candidate_field_results": candidate_field_results,
                    "candidate_value_only_field_results": candidate_value_only_field_results,
                    "candidate_denominator_field_results": candidate_denominator_field_results,
                    "candidate_item_match_summary": item_match_summary,
                    "review_label": gold_row.get("review_label"),
                }
            )
    return rows


def _evaluate_legacy_rows(*, rows: list[dict[str, Any]], instance_count: int) -> dict[str, Any]:
    evaluable_rows = [row for row in rows if row["evaluable"]]
    field_rows = [field for row in evaluable_rows for field in row["field_results"]]
    value_only_field_rows = [field for row in evaluable_rows for field in row["value_only_field_results"]]
    denominator_field_rows = [field for row in evaluable_rows for field in row["denominator_field_results"]]
    candidate_field_rows = [field for row in evaluable_rows for field in row["candidate_field_results"]]
    candidate_value_only_field_rows = [field for row in evaluable_rows for field in row["candidate_value_only_field_results"]]
    candidate_denominator_field_rows = [field for row in evaluable_rows for field in row["candidate_denominator_field_results"]]
    item_match_summaries = [row["candidate_item_match_summary"] for row in evaluable_rows]
    return {
        "instance_count": instance_count,
        "comparison_count": len(rows),
        "evaluable_target_count": len(evaluable_rows),
        "duplicate_gold_target_count": 0,
        "target_completion_rate": _mean([row["covered"] for row in evaluable_rows]),
        "target_extracted_rate": _mean([row["extraction_status"] == "extracted" for row in evaluable_rows]),
        "target_numeric_close_rate": _mean([row["numeric_close"] for row in evaluable_rows]),
        "target_value_only_close_rate": _mean([row["value_only_numeric_close"] for row in evaluable_rows]),
        "field_close_rate": _mean([row["close"] for row in field_rows]),
        "field_close_rates": _field_close_rates(field_rows),
        "value_only_field_close_rate": _mean([row["close"] for row in value_only_field_rows]),
        "value_only_field_close_rates": _field_close_rates(value_only_field_rows),
        "denominator_field_close_rate": _mean([row["close"] for row in denominator_field_rows]),
        "denominator_field_close_rates": _field_close_rates(denominator_field_rows),
        "candidate_numeric_recall_rate": _mean([row["candidate_numeric_close"] for row in evaluable_rows]),
        "candidate_item_complete_recall": _mean([row["candidate_numeric_close"] for row in evaluable_rows]),
        "candidate_item_any_value_recall": _mean([summary["any_value_match"] for summary in item_match_summaries]),
        "candidate_item_field_coverage": _numeric_mean([summary["field_coverage"] for summary in item_match_summaries]),
        "candidate_value_only_recall_rate": _mean([row["candidate_value_only_close"] for row in evaluable_rows]),
        "candidate_field_recall_rate": _mean([row["close"] for row in candidate_field_rows]),
        "candidate_field_recall_rates": _field_close_rates(candidate_field_rows),
        "candidate_value_only_field_recall_rate": _mean([row["close"] for row in candidate_value_only_field_rows]),
        "candidate_value_only_field_recall_rates": _field_close_rates(candidate_value_only_field_rows),
        "candidate_denominator_field_recall_rate": _mean([row["close"] for row in candidate_denominator_field_rows]),
        "candidate_denominator_field_recall_rates": _field_close_rates(candidate_denominator_field_rows),
        "ambiguous_with_gold_candidate_rate": _mean(
            [row["candidate_numeric_close"] for row in evaluable_rows if row["extraction_status"] == "ambiguous"]
        ),
        "avg_candidate_count": _numeric_mean([row["candidate_count"] for row in evaluable_rows]),
        "review_label_counts": _label_counts([str(row["review_label"]) for row in evaluable_rows if row.get("review_label")]),
        **_audit_subset_metrics(evaluable_rows),
    }


def _target_id(row: dict[str, Any]) -> str:
    return str(row.get("row_id") or "")


def _prediction_rows_by_legacy_keys(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in _legacy_match_keys(row):
            indexed.setdefault(key, row)
    return indexed


def _legacy_match_keys(row: dict[str, Any]) -> list[str]:
    keys = []
    for value in (row.get("row_id"), row.get("extraction_task_id")):
        text = str(value or "")
        if text:
            keys.append(text)
    setting_id = str(row.get("setting_id") or "")
    study_id = str(row.get("study_id") or "")
    if setting_id and study_id:
        keys.append(_study_setting_key(setting_id=setting_id, study_id=study_id))
        keys.append(f"task::{setting_id}::{_slug(study_id)}")
    return list(dict.fromkeys(keys))


def _first_matching_prediction_row(
    *,
    pred_rows_by_key: dict[str, dict[str, Any]],
    keys: list[str],
    used_prediction_rows: set[int],
) -> tuple[dict[str, Any] | None, str | None]:
    for key in keys:
        row = pred_rows_by_key.get(key)
        if row is not None and id(row) not in used_prediction_rows:
            return row, key
    return None, None


def _study_setting_key(*, setting_id: str, study_id: str) -> str:
    return f"study-setting::{setting_id}::{study_id}"


def _slug(value: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return cleaned or "study"


def _field_results(
    *,
    gold_row: dict[str, Any],
    pred_row: dict[str, Any] | None,
    field_selector: Any = None,
) -> list[dict[str, Any]]:
    data_type = str(gold_row.get("data_type") or "")
    required_fields = field_selector(data_type) if field_selector is not None else REQUIRED_FIELDS_BY_DATA_TYPE.get(data_type, ())
    gold_data = _row_result_data(gold_row)
    pred_data = _row_result_data(pred_row or {})
    return [
        {
            "field": field,
            "close": pred_row is not None and _value_close(gold_data.get(field), pred_data.get(field), field=field),
        }
        for field in required_fields
    ]


def _legacy_candidate_field_results(
    *,
    gold_row: dict[str, Any],
    pred_row: dict[str, Any] | None,
    field_selector: Any = None,
) -> list[dict[str, Any]]:
    data_type = str(gold_row.get("data_type") or "")
    required_fields = field_selector(data_type) if field_selector is not None else REQUIRED_FIELDS_BY_DATA_TYPE.get(data_type, ())
    gold_data = _row_result_data(gold_row)
    candidates = _candidate_rows(pred_row)
    return [
        {
            "field": field,
            "close": any(
                _value_close(gold_data.get(field), _candidate_field_value(candidate or {}, field), field=field)
                for candidate in candidates
            ),
        }
        for field in required_fields
    ]


def _legacy_candidate_numeric_close(
    *,
    gold_row: dict[str, Any],
    pred_row: dict[str, Any] | None,
    field_selector: Any = None,
) -> bool:
    gold_candidate = {
        "data_type": gold_row.get("data_type"),
        "result_data": _row_result_data(gold_row),
    }
    matcher = _candidate_numeric_close if field_selector is None else _candidate_value_only_close
    if field_selector is _denominator_fields_for_data_type:
        matcher = _candidate_denominator_only_close
    return any(matcher(gold_candidate=gold_candidate, pred_candidate=candidate) for candidate in _candidate_rows(pred_row))


def _candidate_denominator_only_close(*, gold_candidate: dict[str, Any], pred_candidate: dict[str, Any]) -> bool:
    data_type = str(gold_candidate.get("data_type") or pred_candidate.get("data_type") or "")
    required_fields = _denominator_fields_for_data_type(data_type)
    if not required_fields:
        return False
    gold_data = gold_candidate.get("result_data") or {}
    return all(_value_close(gold_data.get(field), _candidate_field_value(pred_candidate, field), field=field) for field in required_fields)


def _candidate_field_value(candidate: dict[str, Any], field: str) -> Any:
    result_data = candidate.get("result_data") if isinstance(candidate.get("result_data"), dict) else {}
    if field in result_data and result_data.get(field) is not None:
        return result_data.get(field)
    # Legacy runs emitted partial_result_data separately. Current methods put
    # all known values in result_data, which may be partial or complete.
    partial = candidate.get("partial_result_data") if isinstance(candidate.get("partial_result_data"), dict) else {}
    if field in partial:
        return partial.get(field)
    numeric = candidate.get("numeric_extraction") if isinstance(candidate.get("numeric_extraction"), dict) else {}
    fields = numeric.get("fields") if isinstance(numeric.get("fields"), dict) else {}
    field_item = fields.get(field) if isinstance(fields.get(field), dict) else {}
    if str(field_item.get("status") or "").strip().lower() in {"direct", "semantic_derived", "calculated"}:
        return field_item.get("value")
    return None


def _candidate_rows(pred_row: dict[str, Any] | None) -> list[dict[str, Any]]:
    candidates = (pred_row or {}).get("result_items") or (pred_row or {}).get("candidate_results") or []
    return [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
        and str(candidate.get("match_status") or "possible").strip().lower() in {"matched", "possible", "selected", "candidate"}
        and str(candidate.get("analysis_disposition") or "candidate").strip().lower() != "exclude"
    ]


def _row_result_data(row: dict[str, Any]) -> dict[str, Any]:
    candidates = row.get("result_items") if isinstance(row.get("result_items"), list) else None
    if candidates is None:
        candidates = row.get("candidate_results") if isinstance(row.get("candidate_results"), list) else None
    if candidates:
        ready = [candidate for candidate in candidates if isinstance(candidate, dict) and _is_ready_item(candidate)]
        source = ready[0] if ready else next((candidate for candidate in candidates if isinstance(candidate, dict)), None)
        if isinstance(source, dict) and isinstance(source.get("result_data"), dict):
            return source["result_data"]
    return row.get("result_data") if isinstance(row.get("result_data"), dict) else {}


def _field_close_rates(field_rows: list[dict[str, Any]]) -> dict[str, float]:
    fields = sorted({str(row["field"]) for row in field_rows})
    return {
        field: _mean([row["close"] for row in field_rows if row["field"] == field])
        for field in fields
    }


def _numeric_mean(values: list[Any]) -> float:
    numeric_values: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            numeric_values.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(numeric_values) / len(numeric_values) if numeric_values else 0.0


def _label_counts(labels: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def _audit_subset_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    material_problem_label = "source_data_missing_not_for_eval"
    gold_mismatch_label = "gold_source_mismatch_suggested_for_audit"
    material_rows = [row for row in rows if row.get("review_label") == material_problem_label]
    gold_mismatch_rows = [row for row in rows if row.get("review_label") == gold_mismatch_label]
    included_rows = [row for row in rows if row.get("review_label") != material_problem_label]
    return {
        "audit_material_problem_target_count": len(material_rows),
        "audit_gold_source_mismatch_target_count": len(gold_mismatch_rows),
        "audit_included_target_count": len(included_rows),
        "audit_included_target_completion_rate": _mean([row.get("covered") for row in included_rows]),
        "audit_included_target_extracted_rate": _mean([row.get("extraction_status") == "extracted" for row in included_rows]),
        "audit_included_target_numeric_close_rate": _audit_numeric_rate(included_rows),
        "audit_included_target_value_only_close_rate": _audit_value_only_rate(included_rows),
    }


def _audit_numeric_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    if any("full_set_recalled" in row for row in rows):
        return _mean([row.get("full_set_recalled") for row in rows])
    return _mean([row.get("numeric_close") for row in rows])


def _audit_value_only_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    if any("value_only_matched_candidate_count" in row for row in rows):
        return _mean([(row.get("value_only_matched_candidate_count") or 0) > 0 for row in rows])
    return _mean([row.get("value_only_numeric_close") for row in rows])
