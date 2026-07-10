"""Metrics for GRADE domain judgement evaluation."""

from __future__ import annotations

from typing import Any


FIELDS = ("downgraded", "severity", "levels", "level_evaluable")


def build_comparisons(predictions: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    predictions_by_id = {str(row.get("instance_id") or ""): row for row in predictions}
    rows: list[dict[str, Any]] = []
    for instance_id, gold in gold_by_id.items():
        prediction = predictions_by_id.get(instance_id) or {"instance_id": instance_id}
        gold_judgement = gold.get("judgement") or {}
        pred_judgement = _prediction_judgement(prediction)
        domain = str(gold.get("domain") or gold_judgement.get("domain") or "")
        for field in FIELDS:
            rows.append(
                {
                    "instance_id": instance_id,
                    "domain": domain,
                    "field": field,
                    "covered": bool(pred_judgement),
                    "gold": gold_judgement.get(field),
                    "prediction": pred_judgement.get(field),
                    "exact_match": _value_equal(gold_judgement.get(field), pred_judgement.get(field)),
                }
            )
    return rows


def evaluate_predictions(predictions: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = build_comparisons(predictions, gold_by_id)
    by_field = {field: [row for row in rows if row["field"] == field] for field in FIELDS}
    missing_prediction_count = sum(1 for instance_id in gold_by_id if instance_id not in {str(row.get("instance_id") or "") for row in predictions})
    metrics = {
        "instance_count": len(gold_by_id),
        "comparison_count": len(rows),
        "missing_prediction_count": missing_prediction_count,
        "judgement_join_rate": _mean([row["covered"] for row in by_field["downgraded"]]),
        "downgraded_exact_rate": _mean([row["exact_match"] for row in by_field["downgraded"]]),
        "severity_exact_rate": _mean([row["exact_match"] for row in by_field["severity"]]),
        "levels_exact_rate": _mean([row["exact_match"] for row in by_field["levels"]]),
        "evaluable_exact_rate": _mean([row["exact_match"] for row in by_field["level_evaluable"]]),
        "all_fields_exact_rate": _all_fields_exact_rate(rows),
    }
    metrics.update(_imprecision_metrics(predictions, gold_by_id))
    return metrics


def _prediction_judgement(prediction: dict[str, Any]) -> dict[str, Any]:
    if isinstance(prediction.get("judgement"), dict):
        return prediction["judgement"]
    payload = prediction.get("prediction")
    if isinstance(payload, dict):
        if isinstance(payload.get("judgement"), dict):
            return payload["judgement"]
        domain = prediction.get("domain") or payload.get("domain")
        sof_row_id = prediction.get("sof_row_id") or payload.get("sof_row_id")
        for row in payload.get("sof_rows") or []:
            if sof_row_id and row.get("sof_row_id") != sof_row_id:
                continue
            judgements = row.get("domain_judgements") or {}
            if domain and isinstance(judgements.get(str(domain)), dict):
                return judgements[str(domain)]
    return {}


def _all_fields_exact_rate(rows: list[dict[str, Any]]) -> float:
    by_instance: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_instance.setdefault(str(row["instance_id"]), []).append(row)
    return _mean([all(row["exact_match"] for row in instance_rows) for instance_rows in by_instance.values()])


def _value_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) is bool(right)
    return str(left) == str(right)


def _mean(values: list[bool]) -> float:
    return sum(1 for value in values if value) / len(values) if values else 0.0


def _imprecision_metrics(predictions: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    predictions_by_id = {str(row.get("instance_id") or ""): row for row in predictions}
    evaluable_rows: list[tuple[int, int]] = []
    downgrade_pairs: list[tuple[str, str]] = []
    eval_records: list[dict[str, Any]] = []
    gold_unclear = 0
    pred_unclear = 0
    threshold_rows: list[dict[str, Any]] = []
    threshold_query_keys: list[str] = []
    threshold_reuse_count = 0

    for instance_id, gold in gold_by_id.items():
        prediction = predictions_by_id.get(instance_id) or {"instance_id": instance_id}
        gold_judgement = gold.get("judgement") or {}
        pred_judgement = _prediction_judgement(prediction)
        gold_level = _numeric_level(gold_judgement)
        pred_level = _numeric_level(pred_judgement)
        gold_is_unclear = gold_level is None
        pred_is_unclear = pred_level is None
        gold_unclear += int(gold_is_unclear)
        pred_unclear += int(pred_is_unclear)

        if gold_level is not None and pred_level is not None:
            evaluable_rows.append((gold_level, pred_level))
            downgrade_pairs.append(("yes" if gold_level > 0 else "no", "yes" if pred_level > 0 else "no"))
        threshold = _threshold_result(prediction)
        if threshold:
            threshold_rows.append(threshold)
        eval_records.append(
            {
                "gold_level": gold_level,
                "pred_level": pred_level,
                "gold_downgraded": "yes" if gold_level is not None and gold_level > 0 else "no" if gold_level == 0 else "unclear",
                "pred_downgraded": "yes" if pred_level is not None and pred_level > 0 else "no" if pred_level == 0 else "unclear",
                "threshold": threshold,
            }
        )
        trace_debug = _prediction_debug(prediction)
        if trace_debug:
            key = trace_debug.get("threshold_query_key")
            if key:
                threshold_query_keys.append(str(key))
            threshold_reuse_count += int(bool(trace_debug.get("threshold_reused")))

    downgrade_prf = _binary_prf(downgrade_pairs)
    level_prf = _level_prf(evaluable_rows)
    level_matrix = _confusion_matrix(evaluable_rows, labels=[0, 1, 2])
    threshold_found = [bool(row.get("threshold_found")) for row in threshold_rows]
    threshold_applicable = [
        bool(row.get("threshold_found")) and str(row.get("source_confidence") or "").lower() in {"high", "medium"}
        for row in threshold_rows
    ]
    confidence_distribution: dict[str, int] = {}
    source_type_distribution: dict[str, int] = {}
    derivation_type_distribution: dict[str, int] = {}
    applicability_distribution: dict[str, int] = {}
    evidence_grade_distribution: dict[str, int] = {}
    llm_failure_count = 0
    cache_eligible_count = 0
    llm_reasoned_fallback_count = 0
    hardcoded_fallback_count = 0
    registry_hit_count = 0
    registry_stored_count = 0
    for row in threshold_rows:
        confidence = str(row.get("source_confidence") or "none").lower()
        confidence_distribution[confidence] = confidence_distribution.get(confidence, 0) + 1
        source_type = str(row.get("threshold_source_type") or "unknown")
        source_type_distribution[source_type] = source_type_distribution.get(source_type, 0) + 1
        derivation_type = str(row.get("derivation_type") or "unknown")
        derivation_type_distribution[derivation_type] = derivation_type_distribution.get(derivation_type, 0) + 1
        applicability = str(row.get("threshold_applicability") or "unknown")
        applicability_distribution[applicability] = applicability_distribution.get(applicability, 0) + 1
        evidence_grade = str(row.get("threshold_evidence_grade") or "unknown")
        evidence_grade_distribution[evidence_grade] = evidence_grade_distribution.get(evidence_grade, 0) + 1
        cache_eligible_count += int(bool(row.get("cache_eligible")))
        registry_hit_count += int(bool(row.get("registry_hit")))
        registry_stored_count += int(bool(row.get("registry_stored")))
        llm_reasoned_fallback_count += int(source_type == "llm_reasoned_fallback")
        hardcoded_fallback_count += int(source_type == "hardcoded_fallback")
        if bool(row.get("fallback_used")):
            llm_failure_count += 1

    strict_source_backed = _stratified_metrics(
        eval_records,
        lambda row: str(row.get("threshold", {}).get("threshold_evidence_grade") or "")
        in {"source_backed_direct", "source_backed_derived"},
    )
    weak_threshold = _stratified_metrics(
        eval_records,
        lambda row: str(row.get("threshold", {}).get("threshold_evidence_grade") or "")
        in {"source_backed_indirect", "general_grade_default", "source_backed_low_confidence", "llm_reasoned_fallback", "unavailable"},
    )
    fallback_threshold = _stratified_metrics(
        eval_records,
        lambda row: str(row.get("threshold", {}).get("threshold_source_type") or "")
        in {"llm_reasoned_fallback", "hardcoded_fallback"},
    )

    return {
        "downgrade_precision_on_evaluable": downgrade_prf["precision"],
        "downgrade_recall_on_evaluable": downgrade_prf["recall"],
        "downgrade_f1_on_evaluable": downgrade_prf["f1"],
        "downgrade_confusion_matrix": downgrade_prf["confusion_matrix"],
        "level_macro_precision_on_evaluable": level_prf["macro_precision"],
        "level_macro_recall_on_evaluable": level_prf["macro_recall"],
        "level_macro_f1_on_evaluable": level_prf["macro_f1"],
        "level_per_class_prf": level_prf["per_class"],
        "level_confusion_matrix": level_matrix,
        "level_ordinal_mae_on_evaluable": _ordinal_mae(evaluable_rows),
        "gold_unclear_count": gold_unclear,
        "prediction_unclear_count": pred_unclear,
        "prediction_unclear_rate": pred_unclear / len(gold_by_id) if gold_by_id else 0.0,
        "evaluable_coverage": len(evaluable_rows) / len(gold_by_id) if gold_by_id else 0.0,
        "threshold_trace_count": len(threshold_rows),
        "threshold_query_key_count": len(set(threshold_query_keys)),
        "threshold_reuse_count": threshold_reuse_count,
        "threshold_found_rate": sum(1 for value in threshold_found if value) / len(threshold_found) if threshold_found else 0.0,
        "threshold_applicable_rate": sum(1 for value in threshold_applicable if value) / len(threshold_applicable) if threshold_applicable else 0.0,
        "threshold_confidence_distribution": confidence_distribution,
        "threshold_source_type_distribution": source_type_distribution,
        "threshold_derivation_type_distribution": derivation_type_distribution,
        "threshold_applicability_distribution": applicability_distribution,
        "threshold_evidence_grade_distribution": evidence_grade_distribution,
        "cache_eligible_threshold_count": cache_eligible_count,
        "threshold_registry_hit_count": registry_hit_count,
        "threshold_registry_stored_count": registry_stored_count,
        "llm_reasoned_fallback_count": llm_reasoned_fallback_count,
        "hardcoded_fallback_count": hardcoded_fallback_count,
        "llm_failure_count": llm_failure_count,
        "strict_source_backed_eval": strict_source_backed,
        "weak_threshold_eval": weak_threshold,
        "fallback_threshold_eval": fallback_threshold,
    }


def _prediction_payload(prediction: dict[str, Any]) -> dict[str, Any]:
    payload = prediction.get("prediction")
    return payload if isinstance(payload, dict) else {}


def _threshold_result(prediction: dict[str, Any]) -> dict[str, Any]:
    debug = _prediction_debug(prediction)
    if isinstance(debug, dict) and isinstance(debug.get("threshold_result"), dict):
        return debug["threshold_result"]
    return {}


def _prediction_debug(prediction: dict[str, Any]) -> dict[str, Any]:
    judgement = _prediction_judgement(prediction)
    debug = judgement.get("debug") if isinstance(judgement, dict) else None
    if isinstance(debug, dict):
        return debug
    payload = _prediction_payload(prediction)
    debug = payload.get("debug") if isinstance(payload, dict) else None
    if isinstance(debug, dict):
        return debug
    return {}


def _numeric_level(judgement: dict[str, Any]) -> int | None:
    if not judgement or not bool(judgement.get("level_evaluable")):
        return None
    value = judgement.get("levels")
    try:
        level = int(value)
    except (TypeError, ValueError):
        return None
    return level if level in {0, 1, 2} else None


def _downgrade_label(judgement: dict[str, Any]) -> str:
    value = str(judgement.get("downgraded") or "").lower()
    return value if value in {"yes", "no"} else "unclear"


def _binary_prf(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    tp = sum(1 for gold, pred in pairs if gold == "yes" and pred == "yes")
    fp = sum(1 for gold, pred in pairs if gold == "no" and pred == "yes")
    fn = sum(1 for gold, pred in pairs if gold == "yes" and pred == "no")
    tn = sum(1 for gold, pred in pairs if gold == "no" and pred == "no")
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def _level_prf(rows: list[tuple[int, int]]) -> dict[str, Any]:
    labels = [0, 1, 2]
    macro_labels = [label for label in labels if any(gold == label or pred == label for gold, pred in rows)]
    if not macro_labels:
        macro_labels = labels
    per_class: dict[str, dict[str, float]] = {}
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    for label in labels:
        tp = sum(1 for gold, pred in rows if gold == label and pred == label)
        fp = sum(1 for gold, pred in rows if gold != label and pred == label)
        fn = sum(1 for gold, pred in rows if gold == label and pred != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[str(label)] = {"precision": precision, "recall": recall, "f1": f1, "support": sum(1 for gold, _ in rows if gold == label)}
        if label in macro_labels:
            precisions.append(precision)
            recalls.append(recall)
            f1s.append(f1)
    return {
        "macro_precision": sum(precisions) / len(precisions),
        "macro_recall": sum(recalls) / len(recalls),
        "macro_f1": sum(f1s) / len(f1s),
        "per_class": per_class,
    }


def _confusion_matrix(rows: list[tuple[int, int]], *, labels: list[int]) -> dict[str, dict[str, int]]:
    return {
        str(gold_label): {
            str(pred_label): sum(1 for gold, pred in rows if gold == gold_label and pred == pred_label)
            for pred_label in labels
        }
        for gold_label in labels
    }


def _ordinal_mae(rows: list[tuple[int, int]]) -> float:
    return sum(abs(pred - gold) for gold, pred in rows) / len(rows) if rows else 0.0


def _stratified_metrics(records: list[dict[str, Any]], predicate: Any) -> dict[str, Any]:
    selected = [record for record in records if predicate(record)]
    evaluable = [
        (record["gold_level"], record["pred_level"])
        for record in selected
        if record.get("gold_level") is not None and record.get("pred_level") is not None
    ]
    downgrade_pairs = [
        (record["gold_downgraded"], record["pred_downgraded"])
        for record in selected
        if record.get("gold_downgraded") in {"yes", "no"} and record.get("pred_downgraded") in {"yes", "no"}
    ]
    downgrade_prf = _binary_prf(downgrade_pairs)
    level_prf = _level_prf(evaluable)
    return {
        "instance_count": len(selected),
        "evaluable_count": len(evaluable),
        "coverage": len(selected) / len(records) if records else 0.0,
        "evaluable_coverage": len(evaluable) / len(records) if records else 0.0,
        "downgrade_precision": downgrade_prf["precision"],
        "downgrade_recall": downgrade_prf["recall"],
        "downgrade_f1": downgrade_prf["f1"],
        "downgrade_confusion_matrix": downgrade_prf["confusion_matrix"],
        "level_macro_f1": level_prf["macro_f1"],
        "level_ordinal_mae": _ordinal_mae(evaluable),
    }
