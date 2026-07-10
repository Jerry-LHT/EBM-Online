"""Audit reports for GRADE imprecision benchmark runs."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    report = build_audit_report(run_dir)
    output_json = Path(args.output_json) if args.output_json else run_dir / "audit.json"
    output_md = Path(args.output_md) if args.output_md else run_dir / "audit.md"
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(output_md)


def build_audit_report(run_dir: Path) -> dict[str, Any]:
    comparisons = _read_jsonl(run_dir / "comparisons.jsonl")
    traces = _read_jsonl(run_dir / "threshold_traces.jsonl")
    metrics = _read_json(run_dir / "metrics.json")
    by_instance = _instances_from_comparisons(comparisons)
    trace_by_id = {str(row.get("instance_id") or ""): row for row in traces}
    rows = [_audit_row(instance_id, fields, trace_by_id.get(instance_id) or {}) for instance_id, fields in by_instance.items()]
    return {
        "run_dir": str(run_dir),
        "instance_count": len(rows),
        "metrics_snapshot": {
            key: metrics.get(key)
            for key in [
                "downgrade_f1_on_evaluable",
                "downgrade_precision_on_evaluable",
                "downgrade_recall_on_evaluable",
                "level_macro_f1_on_evaluable",
                "level_ordinal_mae_on_evaluable",
                "prediction_unclear_rate",
                "threshold_found_rate",
                "threshold_applicable_rate",
            ]
        },
        "overall": _slice_metrics(rows),
        "by_threshold_evidence_grade": _group_metrics(rows, lambda row: row["threshold_evidence_grade"]),
        "by_threshold_source_type": _group_metrics(rows, lambda row: row["threshold_source_type"]),
        "by_derivation_type": _group_metrics(rows, lambda row: row["derivation_type"]),
        "by_applicability": _group_metrics(rows, lambda row: row["threshold_applicability"]),
        "by_decision_reason_group": _group_metrics(rows, lambda row: row["decision_reason_group"]),
        "by_ois_reason": _group_metrics(rows, lambda row: row["ois_reason"]),
        "by_data_type": _group_metrics(rows, lambda row: row["data_type"]),
        "level_error_distribution": _counter_dict((row["gold_level_label"], row["pred_level_label"]) for row in rows if row["level_error"]),
        "level_error_by_grade": _nested_counter(
            rows,
            outer=lambda row: row["threshold_evidence_grade"],
            inner=lambda row: f"{row['gold_level_label']}->{row['pred_level_label']}",
            predicate=lambda row: row["level_error"],
        ),
        "binary_error_by_grade": _nested_counter(
            rows,
            outer=lambda row: row["threshold_evidence_grade"],
            inner=lambda row: row["binary_error_type"],
            predicate=lambda row: row["binary_error_type"] in {"fp", "fn"},
        ),
        "decision_reason_for_errors": _counter_dict(row["decision_reason_group"] for row in rows if row["level_error"]),
        "ois_reason_for_errors": _counter_dict(row["ois_reason"] for row in rows if row["level_error"]),
        "threshold_validation_notes": _counter_dict(note for row in rows for note in row["threshold_validation_notes"]),
        "rejected_material_reasons": _counter_dict(reason for row in rows for reason in row["rejected_material_reasons"]),
        "accepted_candidate_types": _counter_dict(kind for row in rows for kind in row["accepted_candidate_types"]),
        "examples": {
            "false_positives": _examples(rows, lambda row: row["binary_error_type"] == "fp"),
            "false_negatives": _examples(rows, lambda row: row["binary_error_type"] == "fn"),
            "level_overcalls": _examples(rows, lambda row: row["numeric_level_error"] is not None and row["numeric_level_error"] > 0),
            "level_undercalls": _examples(rows, lambda row: row["numeric_level_error"] is not None and row["numeric_level_error"] < 0),
            "source_backed_wrong": _examples(
                rows,
                lambda row: row["level_error"] and row["threshold_source_type"] == "source_backed",
            ),
            "fallback_wrong": _examples(
                rows,
                lambda row: row["level_error"] and row["threshold_source_type"] in {"llm_reasoned_fallback", "hardcoded_fallback"},
            ),
        },
    }


def _audit_row(instance_id: str, fields: dict[str, dict[str, Any]], trace: dict[str, Any]) -> dict[str, Any]:
    gold = {field: value.get("gold") for field, value in fields.items()}
    pred = {field: value.get("prediction") for field, value in fields.items()}
    threshold = trace.get("threshold_result") if isinstance(trace.get("threshold_result"), dict) else {}
    decision = trace.get("decision_features") if isinstance(trace.get("decision_features"), dict) else {}
    numeric = trace.get("numeric_features") if isinstance(trace.get("numeric_features"), dict) else {}
    context = trace.get("threshold_research_context") if isinstance(trace.get("threshold_research_context"), dict) else {}
    gold_level = _numeric_level(gold)
    pred_level = _numeric_level(pred)
    gold_down = _downgraded_from_level(gold_level)
    pred_down = _downgraded_from_level(pred_level)
    binary_error_type = _binary_error_type(gold_down, pred_down)
    numeric_level_error = None
    if gold_level is not None and pred_level is not None:
        numeric_level_error = pred_level - gold_level
    return {
        "instance_id": instance_id,
        "review_id": trace.get("review_id"),
        "outcome": context.get("outcome_concept") or trace.get("setting_context", {}).get("outcome"),
        "condition": context.get("condition_context"),
        "data_type": str(numeric.get("data_type") or "unknown"),
        "effect_measure": str(numeric.get("effect_measure") or "unknown"),
        "gold_level": gold_level,
        "pred_level": pred_level,
        "gold_level_label": _level_label(gold.get("levels"), gold_level),
        "pred_level_label": _level_label(pred.get("levels"), pred_level),
        "gold_down": gold_down,
        "pred_down": pred_down,
        "binary_error_type": binary_error_type,
        "level_error": gold_level != pred_level,
        "numeric_level_error": numeric_level_error,
        "threshold_evidence_grade": str(threshold.get("threshold_evidence_grade") or "unknown"),
        "threshold_source_type": str(threshold.get("threshold_source_type") or "unknown"),
        "derivation_type": str(threshold.get("derivation_type") or "unknown"),
        "threshold_applicability": str(threshold.get("threshold_applicability") or "unknown"),
        "source_confidence": str(threshold.get("source_confidence") or "unknown"),
        "threshold_found": bool(threshold.get("threshold_found")),
        "threshold_valid": threshold.get("threshold_valid"),
        "decision_reason_group": str(decision.get("decision_reason_group") or "unknown"),
        "threshold_basis": str(decision.get("threshold_basis") or "unknown"),
        "crosses_no_effect": bool(decision.get("crosses_no_effect")),
        "crosses_both_important_benefit_and_harm": bool(decision.get("crosses_both_important_benefit_and_harm")),
        "ois_reason": str((decision.get("ois_assessment") or {}).get("reason") or "unknown"),
        "ois_severity": str((decision.get("ois_assessment") or {}).get("severity") or "unknown"),
        "threshold_validation_notes": _string_list(threshold.get("threshold_validation_notes")),
        "rejected_material_reasons": [
            str(item.get("rejection_reason"))
            for item in _dict_list(threshold.get("rejected_materials"))
            if item.get("rejection_reason")
        ],
        "accepted_candidate_types": [
            str(item.get("candidate_type"))
            for item in _dict_list(threshold.get("accepted_candidates"))
            if item.get("candidate_type")
        ],
    }


def _slice_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluable_binary = [row for row in rows if row["gold_down"] in {"yes", "no"} and row["pred_down"] in {"yes", "no"}]
    tp = sum(1 for row in evaluable_binary if row["gold_down"] == "yes" and row["pred_down"] == "yes")
    fp = sum(1 for row in evaluable_binary if row["gold_down"] == "no" and row["pred_down"] == "yes")
    fn = sum(1 for row in evaluable_binary if row["gold_down"] == "yes" and row["pred_down"] == "no")
    tn = sum(1 for row in evaluable_binary if row["gold_down"] == "no" and row["pred_down"] == "no")
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    evaluable_levels = [row for row in rows if row["gold_level"] is not None and row["pred_level"] is not None]
    level_exact = sum(1 for row in evaluable_levels if row["gold_level"] == row["pred_level"])
    level_mae = (
        sum(abs(row["pred_level"] - row["gold_level"]) for row in evaluable_levels) / len(evaluable_levels)
        if evaluable_levels
        else 0.0
    )
    return {
        "count": len(rows),
        "binary_evaluable_count": len(evaluable_binary),
        "level_evaluable_count": len(evaluable_levels),
        "downgrade_confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "downgrade_precision": precision,
        "downgrade_recall": recall,
        "downgrade_f1": f1,
        "level_exact_count": level_exact,
        "level_exact_rate": level_exact / len(evaluable_levels) if evaluable_levels else 0.0,
        "level_mae": level_mae,
        "prediction_unclear_count": sum(1 for row in rows if row["pred_level"] is None),
        "gold_unclear_count": sum(1 for row in rows if row["gold_level"] is None),
    }


def _group_metrics(rows: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(key_fn(row) or "unknown")].append(row)
    return {key: _slice_metrics(value) for key, value in sorted(grouped.items())}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# GRADE Imprecision Audit",
        "",
        f"- Run: `{report['run_dir']}`",
        f"- Instances: `{report['instance_count']}`",
        "",
        "## Snapshot",
        "",
    ]
    for key, value in report["metrics_snapshot"].items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Overall", "", _metrics_table({"overall": report["overall"]})])
    lines.extend(["", "## By Threshold Evidence Grade", "", _metrics_table(report["by_threshold_evidence_grade"])])
    lines.extend(["", "## By Decision Reason", "", _metrics_table(report["by_decision_reason_group"], limit=20)])
    lines.extend(["", "## By OIS Reason", "", _metrics_table(report["by_ois_reason"])])
    lines.extend(["", "## Error Distributions", ""])
    lines.append("### Level Error By Grade")
    lines.append("")
    lines.append(_nested_counter_table(report["level_error_by_grade"]))
    lines.append("")
    lines.append("### Binary Error By Grade")
    lines.append("")
    lines.append(_nested_counter_table(report["binary_error_by_grade"]))
    lines.extend(["", "### Top Decision Reasons For Level Errors", "", _counter_table(report["decision_reason_for_errors"])])
    lines.extend(["", "### Top OIS Reasons For Level Errors", "", _counter_table(report["ois_reason_for_errors"])])
    lines.extend(["", "### Rejected Material Reasons", "", _counter_table(report["rejected_material_reasons"])])
    lines.extend(["", "## Examples", ""])
    for name, examples in report["examples"].items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append(_examples_table(examples))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _metrics_table(groups: dict[str, dict[str, Any]], *, limit: int | None = None) -> str:
    items = sorted(groups.items(), key=lambda item: item[1]["count"], reverse=True)
    if limit is not None:
        items = items[:limit]
    lines = [
        "| group | n | binary n | F1 | precision | recall | FP | FN | level n | level exact | MAE | pred unclear |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, metrics in items:
        confusion = metrics["downgrade_confusion"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(key),
                    str(metrics["count"]),
                    str(metrics["binary_evaluable_count"]),
                    _fmt(metrics["downgrade_f1"]),
                    _fmt(metrics["downgrade_precision"]),
                    _fmt(metrics["downgrade_recall"]),
                    str(confusion["fp"]),
                    str(confusion["fn"]),
                    str(metrics["level_evaluable_count"]),
                    _fmt(metrics["level_exact_rate"]),
                    _fmt(metrics["level_mae"]),
                    str(metrics["prediction_unclear_count"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _nested_counter_table(value: dict[str, dict[str, int]]) -> str:
    rows = []
    for outer, inner in value.items():
        for key, count in inner.items():
            rows.append((outer, key, count))
    rows.sort(key=lambda item: item[2], reverse=True)
    lines = ["| group | error | count |", "|---|---|---:|"]
    for outer, key, count in rows[:30]:
        lines.append(f"| {outer} | {key} | {count} |")
    return "\n".join(lines)


def _counter_table(value: dict[str, int]) -> str:
    lines = ["| value | count |", "|---|---:|"]
    for key, count in sorted(value.items(), key=lambda item: item[1], reverse=True)[:30]:
        lines.append(f"| {key} | {count} |")
    return "\n".join(lines)


def _examples_table(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return "_None_"
    lines = [
        "| instance | outcome | gold | pred | grade | reason | OIS |",
        "|---|---|---:|---:|---|---|---|",
    ]
    for row in examples:
        lines.append(
            f"| `{row['instance_id']}` | {row['outcome']} | {row['gold_level_label']} | {row['pred_level_label']} | "
            f"{row['threshold_evidence_grade']} | {row['decision_reason_group']} | {row['ois_reason']} |"
        )
    return "\n".join(lines)


def _examples(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool], limit: int = 12) -> list[dict[str, Any]]:
    keys = [
        "instance_id",
        "outcome",
        "condition",
        "gold_level_label",
        "pred_level_label",
        "threshold_evidence_grade",
        "threshold_source_type",
        "decision_reason_group",
        "ois_reason",
    ]
    return [{key: row.get(key) for key in keys} for row in rows if predicate(row)][:limit]


def _instances_from_comparisons(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        instance_id = str(row.get("instance_id") or "")
        field = str(row.get("field") or "")
        if instance_id and field:
            grouped[instance_id][field] = row
    return grouped


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _numeric_level(judgement: dict[str, Any]) -> int | None:
    if not judgement or not bool(judgement.get("level_evaluable")):
        return None
    value = judgement.get("levels")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _downgraded_from_level(level: int | None) -> str:
    if level is None:
        return "unclear"
    return "yes" if level > 0 else "no"


def _binary_error_type(gold: str, pred: str) -> str:
    if gold not in {"yes", "no"} or pred not in {"yes", "no"}:
        return "unclear"
    if gold == "yes" and pred == "yes":
        return "tp"
    if gold == "no" and pred == "yes":
        return "fp"
    if gold == "yes" and pred == "no":
        return "fn"
    return "tn"


def _level_label(raw: Any, level: int | None) -> str:
    return str(level) if level is not None else str(raw or "unclear")


def _counter_dict(values: Any) -> dict[str, int]:
    return dict(Counter(str(value or "unknown") for value in values))


def _nested_counter(
    rows: list[dict[str, Any]],
    *,
    outer: Callable[[dict[str, Any]], str],
    inner: Callable[[dict[str, Any]], str],
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, dict[str, int]]:
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if predicate(row):
            counters[str(outer(row) or "unknown")][str(inner(row) or "unknown")] += 1
    return {key: dict(value) for key, value in sorted(counters.items())}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


if __name__ == "__main__":
    main()
