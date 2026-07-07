"""Claim-level metrics for Study PIO evaluation."""

from __future__ import annotations

from typing import Any


FIELDS = ("population", "intervention_comparator", "outcomes")


def evaluate_match_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts_by_field = {field: {"tp": 0, "fp": 0, "fn": 0} for field in FIELDS}
    complete_instances: dict[str, set[str]] = {}
    instance_ids: set[str] = set()
    sample_f1_values: list[float] = []

    for row in rows:
        instance_id = str(row.get("instance_id") or "")
        if instance_id:
            instance_ids.add(instance_id)
        field = str(row.get("field") or "")
        if field not in counts_by_field:
            continue
        tp = len(row.get("matches") or [])
        fp = len(row.get("unmatched_predicted_indices") or [])
        fn = len(row.get("unmatched_gold_indices") or [])
        counts_by_field[field]["tp"] += tp
        counts_by_field[field]["fp"] += fp
        counts_by_field[field]["fn"] += fn
        if row.get("predicted_claims") and not row.get("unmatched_gold_indices"):
            complete_instances.setdefault(instance_id, set()).add(field)
        sample_f1_values.append(_f1(_precision(tp, fp), _recall(tp, fn)))

    metrics: dict[str, Any] = {"instance_count": len(instance_ids)}
    total_tp = total_fp = total_fn = 0
    field_f1_values = []
    field_precision_values = []
    field_recall_values = []
    for field in FIELDS:
        counts = counts_by_field[field]
        tp = counts["tp"]
        fp = counts["fp"]
        fn = counts["fn"]
        total_tp += tp
        total_fp += fp
        total_fn += fn
        precision = _precision(tp, fp)
        recall = _recall(tp, fn)
        f1 = _f1(precision, recall)
        metrics[f"{field}_precision"] = precision
        metrics[f"{field}_recall"] = recall
        metrics[f"{field}_f1"] = f1
        metrics[f"{field}_tp"] = tp
        metrics[f"{field}_fp"] = fp
        metrics[f"{field}_fn"] = fn
        field_precision_values.append(precision)
        field_recall_values.append(recall)
        field_f1_values.append(f1)

    micro_precision = _precision(total_tp, total_fp)
    micro_recall = _recall(total_tp, total_fn)
    metrics.update(
        {
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            "micro_precision": micro_precision,
            "micro_recall": micro_recall,
            "micro_f1": _f1(micro_precision, micro_recall),
            "macro_precision": _mean(field_precision_values),
            "macro_recall": _mean(field_recall_values),
            "macro_f1": _mean(field_f1_values),
            "sample_macro_f1": _mean(sample_f1_values),
            "critical_fields_complete_rate": _critical_fields_complete_rate(complete_instances, instance_count=len(instance_ids)),
        }
    )
    metrics.update(_pio_alias_metrics(metrics))
    return metrics


def _pio_alias_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Expose concise P/I/O aliases while preserving existing metric names."""
    aliases: dict[str, Any] = {}
    field_aliases = {
        "p": "population",
        "i": "intervention_comparator",
        "o": "outcomes",
    }
    for alias, field in field_aliases.items():
        for suffix in ("precision", "recall", "f1", "tp", "fp", "fn"):
            aliases[f"{alias}_{suffix}"] = metrics[f"{field}_{suffix}"]
    aliases["pio_macro_precision"] = metrics["macro_precision"]
    aliases["pio_macro_recall"] = metrics["macro_recall"]
    aliases["pio_macro_f1"] = metrics["macro_f1"]
    aliases["pio_micro_precision"] = metrics["micro_precision"]
    aliases["pio_micro_recall"] = metrics["micro_recall"]
    aliases["pio_micro_f1"] = metrics["micro_f1"]
    return aliases


def _precision(tp: int, fp: int) -> float:
    denominator = tp + fp
    return tp / denominator if denominator else 0.0


def _recall(tp: int, fn: int) -> float:
    denominator = tp + fn
    return tp / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    denominator = precision + recall
    return (2 * precision * recall / denominator) if denominator else 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _critical_fields_complete_rate(complete_instances: dict[str, set[str]], *, instance_count: int) -> float:
    if instance_count <= 0:
        return 0.0
    return sum(1 for fields in complete_instances.values() if set(FIELDS).issubset(fields)) / instance_count
