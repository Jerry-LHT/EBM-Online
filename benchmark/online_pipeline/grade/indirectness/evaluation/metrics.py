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
    metrics.update(_indirectness_metrics(predictions, gold_by_id))
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


def _indirectness_metrics(predictions: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    predictions_by_id = {str(row.get("instance_id") or ""): row for row in predictions}
    evaluable_rows: list[tuple[int, int]] = []
    downgrade_pairs: list[tuple[str, str]] = []
    gold_unclear = 0
    pred_unclear = 0
    for instance_id, gold in gold_by_id.items():
        prediction = predictions_by_id.get(instance_id) or {"instance_id": instance_id}
        gold_level = _numeric_level(gold.get("judgement") or {})
        pred_level = _numeric_level(_prediction_judgement(prediction))
        gold_unclear += int(gold_level is None)
        pred_unclear += int(pred_level is None)
        if gold_level is not None and pred_level is not None:
            evaluable_rows.append((gold_level, pred_level))
            downgrade_pairs.append(("yes" if gold_level > 0 else "no", "yes" if pred_level > 0 else "no"))
    downgrade_prf = _binary_prf(downgrade_pairs)
    level_prf = _level_prf(evaluable_rows)
    return {
        "downgrade_precision_on_evaluable": downgrade_prf["precision"],
        "downgrade_recall_on_evaluable": downgrade_prf["recall"],
        "downgrade_f1_on_evaluable": downgrade_prf["f1"],
        "downgrade_confusion_matrix": downgrade_prf["confusion_matrix"],
        "level_macro_f1_on_evaluable": level_prf["macro_f1"],
        "level_per_class_prf": level_prf["per_class"],
        "level_confusion_matrix": _confusion_matrix(evaluable_rows, labels=[0, 1, 2]),
        "level_ordinal_mae_on_evaluable": _ordinal_mae(evaluable_rows),
        "gold_unclear_count": gold_unclear,
        "prediction_unclear_count": pred_unclear,
        "prediction_unclear_rate": pred_unclear / len(gold_by_id) if gold_by_id else 0.0,
        "evaluable_coverage": len(evaluable_rows) / len(gold_by_id) if gold_by_id else 0.0,
    }


def _numeric_level(judgement: dict[str, Any]) -> int | None:
    if not judgement:
        return None
    level = judgement.get("levels")
    if isinstance(level, bool):
        return None
    try:
        parsed = int(level)
    except (TypeError, ValueError):
        severity = str(judgement.get("severity") or "").lower()
        if severity == "none":
            parsed = 0
        elif severity == "serious":
            parsed = 1
        elif severity == "very_serious":
            parsed = 2
        else:
            return None
    return parsed if parsed in {0, 1, 2} else None


def _binary_prf(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    tp = sum(1 for gold, pred in pairs if gold == "yes" and pred == "yes")
    fp = sum(1 for gold, pred in pairs if gold == "no" and pred == "yes")
    fn = sum(1 for gold, pred in pairs if gold == "yes" and pred == "no")
    tn = sum(1 for gold, pred in pairs if gold == "no" and pred == "no")
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def _level_prf(pairs: list[tuple[int, int]]) -> dict[str, Any]:
    per_class: dict[str, dict[str, float]] = {}
    f1_values = []
    for label in (0, 1, 2):
        tp = sum(1 for gold, pred in pairs if gold == label and pred == label)
        fp = sum(1 for gold, pred in pairs if gold != label and pred == label)
        fn = sum(1 for gold, pred in pairs if gold == label and pred != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[str(label)] = {"precision": precision, "recall": recall, "f1": f1}
        f1_values.append(f1)
    return {"macro_f1": sum(f1_values) / len(f1_values) if f1_values else 0.0, "per_class": per_class}


def _confusion_matrix(pairs: list[tuple[int, int]], *, labels: list[int]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {str(gold): {str(pred): 0 for pred in labels} for gold in labels}
    for gold, pred in pairs:
        matrix.setdefault(str(gold), {str(label): 0 for label in labels})
        matrix[str(gold)][str(pred)] = matrix[str(gold)].get(str(pred), 0) + 1
    return matrix


def _ordinal_mae(pairs: list[tuple[int, int]]) -> float:
    return sum(abs(gold - pred) for gold, pred in pairs) / len(pairs) if pairs else 0.0
