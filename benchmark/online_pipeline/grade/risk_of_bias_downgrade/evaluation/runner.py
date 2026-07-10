"""Run the GRADE benchmark."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from benchmark.online_pipeline.grade.risk_of_bias_downgrade.evaluation.io import load_dataset
from benchmark.online_pipeline.grade.risk_of_bias_downgrade.evaluation.metrics import build_comparisons, evaluate_predictions
from benchmark.online_pipeline.shared.jsonl import write_jsonl
from benchmark.online_pipeline.shared.method_loader import load_method
from benchmark.online_pipeline.shared.report_utils import write_json, write_summary_markdown
from benchmark.online_pipeline.shared.run_utils import default_run_id


MODULE_NAME = "grade"
DOMAIN_DIR = Path(__file__).resolve().parents[1]
MODULE_DIR = DOMAIN_DIR.parent
DEFAULT_DATASET = DOMAIN_DIR / "datasets" / "grade_v4" / "splits" / "smoke"
FIELDS = [
    "run_id",
    "method",
    "dataset",
    "split",
    "sample_size",
    "judgement_join_rate",
    "downgraded_exact_rate",
    "severity_exact_rate",
    "levels_exact_rate",
    "evaluable_exact_rate",
    "all_fields_exact_rate",
]


def run_benchmark(
    *,
    dataset: str | Path = DEFAULT_DATASET,
    method: str = "gold",
    run_id: str | None = None,
    runs_root: str | Path | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    resolved_run_id = run_id or default_run_id()
    dataset_path = Path(dataset)
    run_dir = Path(runs_root or DOMAIN_DIR / "runs") / resolved_run_id
    instances, gold_by_id = load_dataset(dataset_path)
    if offset or limit is not None:
        start = max(0, int(offset or 0))
        stop = None if limit is None else start + max(0, int(limit))
        instances = instances[start:stop]
        gold_by_id = {str(instance["instance_id"]): gold_by_id[str(instance["instance_id"])] for instance in instances}
    method_obj = None if method in {"gold", "grade.gold", "oracle"} else load_method(method, default_module=MODULE_NAME)
    predictions = [
        _predict(
            instance=instance,
            gold=gold_by_id[str(instance["instance_id"])],
            method=method,
            method_obj=method_obj,
        )
        for instance in instances
    ]
    comparisons = build_comparisons(predictions, gold_by_id)
    metrics = evaluate_predictions(predictions, gold_by_id)
    _write_run(
        run_dir=run_dir,
        predictions=predictions,
        comparisons=comparisons,
        metrics=metrics,
        method=method,
        dataset=dataset_path,
        run_id=resolved_run_id,
    )
    return {"run_id": resolved_run_id, "run_dir": str(run_dir), "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--method", default="gold")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runs-root", default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    result = run_benchmark(
        dataset=args.dataset,
        method=args.method,
        run_id=args.run_id,
        runs_root=args.runs_root,
        offset=args.offset,
        limit=args.limit,
    )
    print(result["run_dir"])


def _predict(*, instance: dict[str, Any], gold: dict[str, Any], method: str, method_obj: Any | None = None) -> dict[str, Any]:
    if method in {"gold", "grade.gold", "oracle"}:
        return {
            "instance_id": instance["instance_id"],
            "sof_row_id": instance["sof_row_id"],
            "review_id": instance["review_id"],
            "domain": instance["domain"],
            "judgement": gold.get("judgement") or {},
        }
    method_obj = method_obj or load_method(method, default_module=MODULE_NAME)
    if not hasattr(method_obj, "run_instance"):
        raise TypeError("GRADE domain benchmark methods must implement run_instance(instance=...).")
    output = method_obj.run_instance(instance=instance)
    return {
        "instance_id": instance["instance_id"],
        "sof_row_id": instance.get("sof_row_id"),
        "review_id": instance.get("review_id"),
        "domain": instance.get("domain"),
        "prediction": to_jsonable(output),
    }


def _write_run(
    *,
    run_dir: Path,
    predictions: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    metrics: dict[str, Any],
    method: str,
    dataset: Path,
    run_id: str,
) -> None:
    write_jsonl(run_dir / "predictions.jsonl", predictions, sort_keys=False)
    write_jsonl(run_dir / "comparisons.jsonl", comparisons, sort_keys=False)
    write_json(run_dir / "metrics.json", metrics)
    summary = {"run_id": run_id, "method": method, "dataset": str(dataset), **metrics}
    write_json(run_dir / "summary.json", summary)
    write_summary_markdown(run_dir / "summary.md", title="grade benchmark", summary=summary)
    dataset_name = dataset.parent.parent.name if dataset.parent.name == "splits" else dataset.name
    split = dataset.name if dataset.parent.name == "splits" else "all"
    write_json(
        run_dir / "run_manifest.json",
        {
            "module_name": "grade",
            "domain": "risk_of_bias",
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
    row = {
        "run_id": run_id,
        "method": method,
        "dataset": dataset_name,
        "split": split,
        "sample_size": metrics.get("instance_count", ""),
        "judgement_join_rate": metrics.get("judgement_join_rate", ""),
        "downgraded_exact_rate": metrics.get("downgraded_exact_rate", ""),
        "severity_exact_rate": metrics.get("severity_exact_rate", ""),
        "levels_exact_rate": metrics.get("levels_exact_rate", ""),
        "evaluable_exact_rate": metrics.get("evaluable_exact_rate", ""),
        "all_fields_exact_rate": metrics.get("all_fields_exact_rate", ""),
    }
    _append_metrics_index(run_dir.parent / "metrics_index.csv", row)


def _append_metrics_index(path: Path, row: dict[str, Any]) -> None:
    rows = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    key = (row["run_id"], row["dataset"], row["split"])
    rows = [existing for existing in rows if (existing.get("run_id"), existing.get("dataset"), existing.get("split")) != key]
    rows.append({field: row.get(field, "") for field in FIELDS})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
