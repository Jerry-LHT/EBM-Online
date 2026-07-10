"""Run Meta Analysis Subtask 2 benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from benchmark.online_pipeline.meta_analysis.evaluation_common.io import load_dataset
from benchmark.online_pipeline.meta_analysis.evaluation_common.method_adapters import predict_subtask2, targetize_subtask2_gold
from benchmark.online_pipeline.meta_analysis.subtask2_study_results.evaluation.metrics import build_comparisons, evaluate_predictions
from benchmark.online_pipeline.shared.jsonl import write_jsonl
from benchmark.online_pipeline.shared.report_utils import write_json, write_summary_markdown
from benchmark.online_pipeline.shared.run_utils import default_run_id


TASK_DIR = Path(__file__).resolve().parents[1]
MODULE_DIR = TASK_DIR.parent
DEFAULT_DATASET = TASK_DIR / "datasets" / "cochrane_meta_v2-key-filter-dev4" / "splits" / "dev4"
FIELDS = [
    "run_id",
    "method",
    "dataset",
    "split",
    "sample_size",
    "evaluable_target_count",
    "duplicate_gold_target_count",
    "candidate_item_complete_recall",
    "candidate_item_any_value_recall",
    "candidate_item_field_coverage",
    "target_completion_rate",
    "target_extracted_rate",
    "target_numeric_close_rate",
    "target_value_only_close_rate",
    "field_close_rate",
    "value_only_field_close_rate",
    "denominator_field_close_rate",
    "candidate_numeric_recall_rate",
    "candidate_value_only_recall_rate",
    "candidate_field_recall_rate",
    "candidate_value_only_field_recall_rate",
    "candidate_denominator_field_recall_rate",
    "candidate_row_recall",
    "candidate_row_precision",
    "candidate_row_f1",
    "candidate_value_only_recall",
    "full_set_recall_rate",
    "downstream_ready_rate",
    "ambiguous_with_gold_candidate_rate",
    "avg_candidate_count",
    "avg_gold_candidate_count",
    "avg_pred_candidate_count",
]
_PARTIAL_WRITE_LOCK = Lock()


def run_benchmark(
    *,
    dataset: str | Path = DEFAULT_DATASET,
    method: str = "gold",
    run_id: str | None = None,
    runs_root: str | Path | None = None,
    limit: int | None = None,
    llm_config: str | Path | None = None,
    progress: bool = False,
    workers: int = 1,
    hint_policy: str = "none",
) -> dict[str, Any]:
    resolved_run_id = run_id or default_run_id()
    run_dir = Path(runs_root or TASK_DIR / "runs") / resolved_run_id
    instances, gold_by_id = load_dataset(dataset)
    if limit is not None:
        instances = instances[:limit]
        gold_by_id = {str(instance["instance_id"]): gold_by_id[str(instance["instance_id"])] for instance in instances}
    gold_by_id = {
        str(instance["instance_id"]): targetize_subtask2_gold(
            instance=instance,
            gold=gold_by_id[str(instance["instance_id"])],
        )
        for instance in instances
    }
    predictions = []
    failures = []
    partial_predictions_path = run_dir / "predictions.partial.jsonl"
    partial_failures_path = run_dir / "failures.partial.jsonl"
    workers = max(1, int(workers or 1))
    if progress:
        run_dir.mkdir(parents=True, exist_ok=True)
        partial_predictions_path.write_text("", encoding="utf-8")
        partial_failures_path.write_text("", encoding="utf-8")
        _progress(f"run start run_id={resolved_run_id} method={method} instances={len(instances)} workers={workers} dataset={dataset}")
    if workers <= 1 or len(instances) <= 1:
        for index, instance in enumerate(instances, start=1):
            prediction = _predict_one(
                index=index,
                total=len(instances),
                instance=instance,
                gold=gold_by_id[str(instance["instance_id"])],
                method=method,
                dataset=dataset,
                llm_config=llm_config,
                progress=progress,
                hint_policy=hint_policy,
                partial_predictions_path=partial_predictions_path,
                partial_failures_path=partial_failures_path,
            )
            predictions.append(prediction)
    else:
        predictions_by_index: list[dict[str, Any] | None] = [None] * len(instances)
        with ThreadPoolExecutor(max_workers=min(workers, len(instances))) as executor:
            futures = {
                executor.submit(
                    _predict_one,
                    index=index,
                    total=len(instances),
                    instance=instance,
                    gold=gold_by_id[str(instance["instance_id"])],
                    method=method,
                    dataset=dataset,
                    llm_config=llm_config,
                    progress=progress,
                    hint_policy=hint_policy,
                    partial_predictions_path=partial_predictions_path,
                    partial_failures_path=partial_failures_path,
                ): index - 1
                for index, instance in enumerate(instances, start=1)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    predictions_by_index[index] = future.result()
                except Exception as exc:
                    failures.append({"instance_index": index + 1, "error_type": type(exc).__name__, "error": str(exc)})
                    raise
        predictions = [prediction for prediction in predictions_by_index if prediction is not None]
    comparisons = build_comparisons(predictions, gold_by_id)
    metrics = evaluate_predictions(predictions, gold_by_id)
    _write_run(run_dir=run_dir, predictions=predictions, comparisons=comparisons, metrics=metrics, method=method, dataset=Path(dataset), run_id=resolved_run_id, fields=FIELDS, hint_policy=hint_policy)
    return {"run_id": resolved_run_id, "run_dir": str(run_dir), "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--method", default="gold")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--llm-config", default=None)
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--hint-policy", default="none", choices=["none", "row_hint", "footnote_only", "analysis_name", "analysis_labels", "analysis_name_subgroup", "full"])
    args = parser.parse_args()
    result = run_benchmark(dataset=args.dataset, method=args.method, run_id=args.run_id, limit=args.limit, llm_config=args.llm_config, progress=args.progress, workers=args.workers, hint_policy=args.hint_policy)
    print(result["run_dir"])


def _predict_one(
    *,
    index: int,
    total: int,
    instance: dict[str, Any],
    gold: dict[str, Any],
    method: str,
    dataset: str | Path,
    llm_config: str | Path | None,
    progress: bool,
    hint_policy: str,
    partial_predictions_path: Path,
    partial_failures_path: Path,
) -> dict[str, Any]:
    instance_id = str(instance["instance_id"])
    started = time.monotonic()
    if progress:
        _progress(f"instance {index}/{total} start instance_id={instance_id}")
    try:
        prediction = predict_subtask2(
            instance=instance,
            gold=gold,
            method=method,
            dataset_dir=dataset,
            llm_config=llm_config,
            hint_policy=hint_policy,
        )
    except Exception as exc:
        failure = {
            "instance_id": instance_id,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        if progress:
            with _PARTIAL_WRITE_LOCK:
                _append_jsonl(partial_failures_path, failure)
            _progress(f"instance {index}/{total} failed instance_id={instance_id} elapsed={failure['elapsed_seconds']}s error={type(exc).__name__}: {exc}")
        raise
    if progress:
        elapsed = round(time.monotonic() - started, 3)
        row_count = len(prediction.get("study_result_rows") or [])
        with _PARTIAL_WRITE_LOCK:
            _append_jsonl(partial_predictions_path, prediction)
        _progress(f"instance {index}/{total} done instance_id={instance_id} rows={row_count} elapsed={elapsed}s")
    return prediction


def _write_run(*, run_dir: Path, predictions: list[dict[str, Any]], comparisons: list[dict[str, Any]], metrics: dict[str, Any], method: str, dataset: Path, run_id: str, fields: list[str], hint_policy: str) -> None:
    write_jsonl(run_dir / "predictions.jsonl", predictions, sort_keys=False)
    write_jsonl(run_dir / "comparisons.jsonl", comparisons, sort_keys=False)
    write_json(run_dir / "metrics.json", metrics)
    write_json(run_dir / "summary.json", metrics)
    write_summary_markdown(run_dir / "summary.md", title="meta_analysis subtask2 benchmark", summary=metrics)
    dataset_name = dataset.parent.parent.name if dataset.parent.name == "splits" else dataset.name
    split = dataset.name if dataset.parent.name == "splits" else "all"
    write_json(
        run_dir / "run_manifest.json",
        {
            "module_name": "meta_analysis",
            "subtask": "subtask2_study_results",
            "run_id": run_id,
            "method": method,
            "hint_policy": hint_policy,
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
        "evaluable_target_count": metrics.get("evaluable_target_count", ""),
        "duplicate_gold_target_count": metrics.get("duplicate_gold_target_count", ""),
        "candidate_item_complete_recall": metrics.get("candidate_item_complete_recall", ""),
        "candidate_item_any_value_recall": metrics.get("candidate_item_any_value_recall", ""),
        "candidate_item_field_coverage": metrics.get("candidate_item_field_coverage", ""),
        "target_completion_rate": metrics.get("target_completion_rate", ""),
        "target_extracted_rate": metrics.get("target_extracted_rate", ""),
        "target_numeric_close_rate": metrics.get("target_numeric_close_rate", ""),
        "target_value_only_close_rate": metrics.get("target_value_only_close_rate", ""),
        "field_close_rate": metrics.get("field_close_rate", ""),
        "value_only_field_close_rate": metrics.get("value_only_field_close_rate", ""),
        "denominator_field_close_rate": metrics.get("denominator_field_close_rate", ""),
        "candidate_numeric_recall_rate": metrics.get("candidate_numeric_recall_rate", ""),
        "candidate_value_only_recall_rate": metrics.get("candidate_value_only_recall_rate", ""),
        "candidate_field_recall_rate": metrics.get("candidate_field_recall_rate", ""),
        "candidate_value_only_field_recall_rate": metrics.get("candidate_value_only_field_recall_rate", ""),
        "candidate_denominator_field_recall_rate": metrics.get("candidate_denominator_field_recall_rate", ""),
        "candidate_row_recall": metrics.get("candidate_row_recall", ""),
        "candidate_row_precision": metrics.get("candidate_row_precision", ""),
        "candidate_row_f1": metrics.get("candidate_row_f1", ""),
        "candidate_value_only_recall": metrics.get("candidate_value_only_recall", ""),
        "full_set_recall_rate": metrics.get("full_set_recall_rate", ""),
        "downstream_ready_rate": metrics.get("downstream_ready_rate", ""),
        "ambiguous_with_gold_candidate_rate": metrics.get("ambiguous_with_gold_candidate_rate", ""),
        "avg_candidate_count": metrics.get("avg_candidate_count", ""),
        "avg_gold_candidate_count": metrics.get("avg_gold_candidate_count", ""),
        "avg_pred_candidate_count": metrics.get("avg_pred_candidate_count", ""),
    }
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


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def _progress(message: str) -> None:
    print(f"[subtask2-runner] {message}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
