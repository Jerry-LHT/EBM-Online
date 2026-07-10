"""Run Meta Analysis Subtask 4 benchmark."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from benchmark.online_pipeline.meta_analysis.evaluation_common.io import load_dataset
from benchmark.online_pipeline.meta_analysis.evaluation_common.method_adapters import predict_subtask4
from benchmark.online_pipeline.meta_analysis.subtask4_subgroup_analysis.evaluation.metrics import build_comparisons, evaluate_predictions
from benchmark.online_pipeline.shared.jsonl import write_jsonl
from benchmark.online_pipeline.shared.report_utils import write_json, write_summary_markdown
from benchmark.online_pipeline.shared.run_utils import default_run_id


TASK_DIR = Path(__file__).resolve().parents[1]
MODULE_DIR = TASK_DIR.parent
DEFAULT_DATASET = TASK_DIR / "datasets" / "cochrane_meta_v2" / "splits" / "smoke"
FIELDS = ["run_id", "method", "dataset", "split", "sample_size", "subgroup_estimate_join_rate", "subgroup_estimate_numeric_close_rate", "subgroup_difference_test_join_rate", "subgroup_difference_test_numeric_close_rate"]


def run_benchmark(*, dataset: str | Path = DEFAULT_DATASET, method: str = "gold", run_id: str | None = None, runs_root: str | Path | None = None, limit: int | None = None) -> dict[str, Any]:
    resolved_run_id = run_id or default_run_id()
    run_dir = Path(runs_root or TASK_DIR / "runs") / resolved_run_id
    instances, gold_by_id = load_dataset(dataset)
    if limit is not None:
        instances = instances[:limit]
        gold_by_id = {str(instance["instance_id"]): gold_by_id[str(instance["instance_id"])] for instance in instances}
    predictions = predict_subtask4(instances=instances, gold_by_id=gold_by_id, method=method)
    comparisons = build_comparisons(predictions, gold_by_id)
    metrics = evaluate_predictions(predictions, gold_by_id)
    _write_run(run_dir=run_dir, predictions=predictions, comparisons=comparisons, metrics=metrics, method=method, dataset=Path(dataset), run_id=resolved_run_id, fields=FIELDS)
    return {"run_id": resolved_run_id, "run_dir": str(run_dir), "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--method", default="gold")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    result = run_benchmark(dataset=args.dataset, method=args.method, run_id=args.run_id, limit=args.limit)
    print(result["run_dir"])


def _write_run(*, run_dir: Path, predictions: list[dict[str, Any]], comparisons: list[dict[str, Any]], metrics: dict[str, Any], method: str, dataset: Path, run_id: str, fields: list[str]) -> None:
    write_jsonl(run_dir / "predictions.jsonl", predictions, sort_keys=False)
    write_jsonl(run_dir / "comparisons.jsonl", comparisons, sort_keys=False)
    write_json(run_dir / "metrics.json", metrics)
    write_json(run_dir / "summary.json", metrics)
    write_summary_markdown(run_dir / "summary.md", title="meta_analysis subtask4 benchmark", summary=metrics)
    dataset_name = dataset.parent.parent.name if dataset.parent.name == "splits" else dataset.name
    split = dataset.name if dataset.parent.name == "splits" else "all"
    write_json(
        run_dir / "run_manifest.json",
        {
            "module_name": "meta_analysis",
            "subtask": "subtask4_subgroup_analysis",
            "run_id": run_id,
            "method": method,
            "dataset": str(dataset),
            "dataset_name": dataset_name,
            "split": split,
            "requested_count": metrics.get("instance_count", ""),
            "completed_count": len(predictions),
            "failed_count": max(0, int(metrics.get("instance_count", 0) or 0) - len(predictions)),
        },
    )
    row = {"run_id": run_id, "method": method, "dataset": dataset_name, "split": split, "sample_size": metrics.get("instance_count", ""), "subgroup_estimate_join_rate": metrics.get("subgroup_estimate_join_rate", ""), "subgroup_estimate_numeric_close_rate": metrics.get("subgroup_estimate_numeric_close_rate", ""), "subgroup_difference_test_join_rate": metrics.get("subgroup_difference_test_join_rate", ""), "subgroup_difference_test_numeric_close_rate": metrics.get("subgroup_difference_test_numeric_close_rate", "")}
    _append_metrics_index(run_dir.parent / "metrics_index.csv", row, fields)


def _append_metrics_index(path: Path, row: dict[str, Any], fields: list[str]) -> None:
    rows = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    key = (row["run_id"], row["dataset"], row["split"])
    rows = [existing for existing in rows if (existing.get("run_id"), existing.get("dataset"), existing.get("split")) != key]
    rows.append({field: row.get(field, "") for field in fields})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
