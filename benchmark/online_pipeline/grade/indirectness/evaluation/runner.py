"""Run the GRADE benchmark."""

from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from benchmark.online_pipeline.grade.indirectness.evaluation.input_adapter import build_method_instance
from benchmark.online_pipeline.grade.indirectness.evaluation.io import load_dataset
from benchmark.online_pipeline.grade.indirectness.evaluation.metrics import build_comparisons, evaluate_predictions
from benchmark.online_pipeline.shared.jsonl import append_jsonl, read_jsonl, write_jsonl
from benchmark.online_pipeline.grade.method_adapter import load_grade_domain_benchmark_method
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
    "downgrade_f1_on_evaluable",
    "level_macro_f1_on_evaluable",
    "level_ordinal_mae_on_evaluable",
    "prediction_unclear_rate",
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
    limit: int | None = None,
    review_limit: int | None = None,
    max_rows_per_review: int | None = None,
    workers: int = 1,
    resume: bool = False,
    retry_unclear: bool = False,
    progress: bool = False,
    input_policy: str = "analysis_setting",
    batch_size: int = 1,
) -> dict[str, Any]:
    resolved_run_id = run_id or default_run_id()
    dataset_path = Path(dataset)
    run_dir = Path(runs_root or DOMAIN_DIR / "runs") / resolved_run_id
    instances, gold_by_id = load_dataset(dataset_path)
    instances = _filter_instances_by_review(
        instances,
        review_limit=review_limit,
        max_rows_per_review=max_rows_per_review,
    )
    if limit is not None:
        instances = instances[:limit]
    gold_by_id = {str(instance["instance_id"]): gold_by_id[str(instance["instance_id"])] for instance in instances}
    method_obj = None if method in {"gold", "grade.gold", "oracle"} else _load_indirectness_method(method)
    existing_predictions = _load_existing_predictions(run_dir / "predictions.jsonl") if resume else []
    if retry_unclear:
        existing_predictions = _filter_retryable_predictions(existing_predictions)
    predictions = _predict_all(
        instances=instances,
        gold_by_id=gold_by_id,
        method=method,
        method_obj=method_obj,
        workers=workers,
        run_dir=run_dir,
        existing_predictions=existing_predictions,
        progress=progress,
        input_policy=input_policy,
        batch_size=batch_size,
    )
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
        workers=workers,
        resume=resume,
        retry_unclear=retry_unclear,
        input_policy=input_policy,
        batch_size=batch_size,
    )
    return {"run_id": resolved_run_id, "run_dir": str(run_dir), "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--method", default="gold")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runs-root", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--review-limit", type=int, default=None)
    parser.add_argument("--max-rows-per-review", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-unclear", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--input-policy", choices=["analysis_setting", "sof_context"], default="analysis_setting")
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args()
    result = run_benchmark(
        dataset=args.dataset,
        method=args.method,
        run_id=args.run_id,
        runs_root=args.runs_root,
        limit=args.limit,
        review_limit=args.review_limit,
        max_rows_per_review=args.max_rows_per_review,
        workers=args.workers,
        resume=args.resume,
        retry_unclear=args.retry_unclear,
        progress=args.progress,
        input_policy=args.input_policy,
        batch_size=max(1, args.batch_size),
    )
    print(result["run_dir"])


def _predict(
    *,
    instance: dict[str, Any],
    gold: dict[str, Any],
    method: str,
    method_obj: Any | None = None,
    input_policy: str = "analysis_setting",
) -> dict[str, Any]:
    if method in {"gold", "grade.gold", "oracle"}:
        return {
            "instance_id": instance["instance_id"],
            "sof_row_id": instance["sof_row_id"],
            "review_id": instance["review_id"],
            "domain": instance["domain"],
            "judgement": gold.get("judgement") or {},
        }
    method_obj = method_obj or load_grade_domain_benchmark_method("indirectness", method)
    method_instance = build_method_instance(instance, input_policy=input_policy)
    output = _run_method_instance(method_obj=method_obj, method_instance=method_instance)
    return {
        "instance_id": instance["instance_id"],
        "sof_row_id": instance.get("sof_row_id"),
        "review_id": instance.get("review_id"),
        "domain": instance.get("domain"),
        "prediction": to_jsonable(output),
    }


def _run_method_instance(*, method_obj: Any, method_instance: dict[str, Any]) -> dict[str, Any]:
    if hasattr(method_obj, "run_instance"):
        return method_obj.run_instance(instance=method_instance)
    domain_attr = getattr(method_obj, "domain", None)
    if domain_attr == "indirectness" and hasattr(method_obj, "run"):
        judgement = method_obj.run(
            domain_evidence=_dict_value(method_instance.get("domain_evidence")),
            evidence_body=_dict_value(method_instance.get("evidence_body")),
        )
        return {
            "instance_id": method_instance.get("instance_id"),
            "sof_row_id": method_instance.get("sof_row_id"),
            "review_id": method_instance.get("review_id"),
            "domain": method_instance.get("domain"),
            "judgement": judgement,
        }
    domain = str(method_instance.get("domain") or "")
    domain_methods = getattr(method_obj, "domain_methods", None)
    if isinstance(domain_methods, dict) and domain in domain_methods:
        domain_method = domain_methods[domain]
        judgement = domain_method.run(
            domain_evidence=_dict_value(method_instance.get("domain_evidence")),
            evidence_body=_dict_value(method_instance.get("evidence_body")),
        )
        return {
            "instance_id": method_instance.get("instance_id"),
            "sof_row_id": method_instance.get("sof_row_id"),
            "review_id": method_instance.get("review_id"),
            "domain": method_instance.get("domain"),
            "judgement": judgement,
        }
    raise TypeError("GRADE domain benchmark methods must implement run_instance(instance=...) or expose domain_methods.")


def _load_indirectness_method(method: str) -> Any:
    return load_grade_domain_benchmark_method("indirectness", method)


def _predict_all(
    *,
    instances: list[dict[str, Any]],
    gold_by_id: dict[str, dict[str, Any]],
    method: str,
    method_obj: Any | None,
    workers: int,
    run_dir: Path | None = None,
    existing_predictions: list[dict[str, Any]] | None = None,
    progress: bool = False,
    input_policy: str = "analysis_setting",
    batch_size: int = 1,
) -> list[dict[str, Any]]:
    completed_by_id = _predictions_by_id(existing_predictions or [])
    pending = [instance for instance in instances if str(instance.get("instance_id") or "") not in completed_by_id]
    predictions_path = run_dir / "predictions.jsonl" if run_dir is not None else None
    if progress and completed_by_id:
        print(f"[resume] loaded {len(completed_by_id)} existing predictions; pending {len(pending)}/{len(instances)}", flush=True)
    if not completed_by_id and predictions_path is not None:
        predictions_path.parent.mkdir(parents=True, exist_ok=True)
        predictions_path.write_text("", encoding="utf-8")

    if batch_size > 1 and method not in {"gold", "grade.gold", "oracle"} and hasattr(method_obj, "run_batch_instances"):
        new_predictions = []
        batches = _chunks(pending, batch_size)
        if workers <= 1:
            for batch_index, batch in enumerate(batches, start=1):
                batch_predictions = _predict_batch(
                    instances=batch,
                    method_obj=method_obj,
                    input_policy=input_policy,
                )
                for prediction in batch_predictions:
                    new_predictions.append(prediction)
                    _append_prediction(predictions_path, prediction)
                if progress:
                    completed_count = len(completed_by_id) + len(new_predictions)
                    print(
                        f"[predict-batch] {completed_count}/{len(instances)} batch={batch_index} size={len(batch)}",
                        flush=True,
                    )
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        _predict_batch,
                        instances=batch,
                        method_obj=method_obj,
                        input_policy=input_policy,
                    ): (batch_index, batch)
                    for batch_index, batch in enumerate(batches, start=1)
                }
                for completed, future in enumerate(as_completed(futures), start=1):
                    batch_index, batch = futures[future]
                    batch_predictions = future.result()
                    for prediction in batch_predictions:
                        new_predictions.append(prediction)
                        _append_prediction(predictions_path, prediction)
                    if progress:
                        completed_count = len(completed_by_id) + len(new_predictions)
                        print(
                            f"[predict-batch] {completed_count}/{len(instances)} batch={batch_index} size={len(batch)} completed_batches={completed}/{len(batches)}",
                            flush=True,
                        )
        completed_by_id.update(_predictions_by_id(new_predictions))
        return [completed_by_id[str(instance["instance_id"])] for instance in instances if str(instance["instance_id"]) in completed_by_id]

    if workers <= 1 or method in {"gold", "grade.gold", "oracle"}:
        new_predictions = []
        for index, instance in enumerate(pending, start=1):
            prediction = _predict(
                instance=instance,
                gold=gold_by_id[str(instance["instance_id"])],
                method=method,
                method_obj=method_obj,
                input_policy=input_policy,
            )
            new_predictions.append(prediction)
            _append_prediction(predictions_path, prediction)
            if progress:
                print(f"[predict] {len(completed_by_id) + index}/{len(instances)} {instance['instance_id']}", flush=True)
        completed_by_id.update(_predictions_by_id(new_predictions))
        return [completed_by_id[str(instance["instance_id"])] for instance in instances if str(instance["instance_id"]) in completed_by_id]

    new_predictions = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _predict,
                instance=instance,
                gold=gold_by_id[str(instance["instance_id"])],
                method=method,
                method_obj=method_obj,
                input_policy=input_policy,
            ): instance
            for instance in pending
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            instance = futures[future]
            prediction = future.result()
            new_predictions.append(prediction)
            _append_prediction(predictions_path, prediction)
            if progress:
                print(f"[predict] {len(completed_by_id) + completed}/{len(instances)} {instance['instance_id']}", flush=True)
    completed_by_id.update(_predictions_by_id(new_predictions))
    return [completed_by_id[str(instance["instance_id"])] for instance in instances if str(instance["instance_id"]) in completed_by_id]


def _predict_batch(
    *,
    instances: list[dict[str, Any]],
    method_obj: Any,
    input_policy: str,
) -> list[dict[str, Any]]:
    method_instances = [build_method_instance(instance, input_policy=input_policy) for instance in instances]
    outputs = method_obj.run_batch_instances(method_instances=method_instances)
    outputs_by_id = _outputs_by_id(outputs)
    predictions = []
    for instance in instances:
        instance_id = str(instance.get("instance_id") or "")
        output = outputs_by_id.get(instance_id)
        if output is None:
            output = {
                "instance_id": instance.get("instance_id"),
                "sof_row_id": instance.get("sof_row_id"),
                "review_id": instance.get("review_id"),
                "domain": instance.get("domain"),
                "judgement": {
                    "domain": "indirectness",
                    "downgraded": "unclear",
                    "severity": "unclear",
                    "levels": "unclear",
                    "level_evaluable": False,
                    "rationale": "Batch method did not return a prediction for this instance.",
                    "debug": {"method": "method_llm", "batch_mode": True, "fallback_reason": "missing_batch_output"},
                },
            }
        predictions.append(
            {
                "instance_id": instance.get("instance_id"),
                "sof_row_id": instance.get("sof_row_id"),
                "review_id": instance.get("review_id"),
                "domain": instance.get("domain"),
                "prediction": to_jsonable(output),
            }
        )
    return predictions


def _outputs_by_id(outputs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for output in outputs:
        if not isinstance(output, dict):
            continue
        instance_id = str(output.get("instance_id") or "")
        if instance_id:
            rows[instance_id] = output
    return rows


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), max(1, size))]


def _load_existing_predictions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_jsonl(path)


def _filter_retryable_predictions(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [prediction for prediction in predictions if not _is_retryable_prediction(prediction)]


def _is_retryable_prediction(prediction: dict[str, Any]) -> bool:
    judgement_payload = _dict_value(prediction.get("prediction"))
    if isinstance(judgement_payload.get("judgement"), dict):
        judgement = judgement_payload["judgement"]
    else:
        judgement = _dict_value(prediction.get("judgement"))
    if str(judgement.get("downgraded") or "").lower() == "unclear":
        return True
    if str(judgement.get("severity") or "").lower() == "unclear":
        return True
    debug = _dict_value(judgement.get("debug"))
    fallback_reason = str(debug.get("fallback_reason") or "").lower()
    return bool(fallback_reason and ("llm_error" in fallback_reason or "429" in fallback_reason or "timeout" in fallback_reason))


def _predictions_by_id(predictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for prediction in predictions:
        instance_id = str(prediction.get("instance_id") or "")
        if instance_id:
            rows[instance_id] = prediction
    return rows


def _append_prediction(path: Path | None, prediction: dict[str, Any]) -> None:
    if path is None:
        return
    append_jsonl(path, [prediction], sort_keys=False)


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _write_run(
    *,
    run_dir: Path,
    predictions: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    metrics: dict[str, Any],
    method: str,
    dataset: Path,
    run_id: str,
    workers: int,
    resume: bool = False,
    retry_unclear: bool = False,
    input_policy: str = "analysis_setting",
    batch_size: int = 1,
) -> None:
    write_jsonl(run_dir / "predictions.jsonl", predictions, sort_keys=False)
    write_jsonl(run_dir / "comparisons.jsonl", comparisons, sort_keys=False)
    write_jsonl(run_dir / "indirectness_traces.jsonl", _indirectness_traces(predictions), sort_keys=False)
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
            "domain": "indirectness",
            "run_id": run_id,
            "method": method,
            "dataset": str(dataset),
            "dataset_name": dataset_name,
            "split": split,
            "requested_count": metrics.get("instance_count", ""),
            "completed_count": len(predictions),
            "failed_count": max(0, int(metrics.get("instance_count", 0) or 0) - len(predictions)),
            "workers": workers,
            "resume": resume,
            "retry_unclear": retry_unclear,
            "input_policy": input_policy,
            "batch_size": batch_size,
        },
    )
    row = {
        "run_id": run_id,
        "method": method,
        "dataset": dataset_name,
        "split": split,
        "sample_size": metrics.get("instance_count", ""),
        "judgement_join_rate": metrics.get("judgement_join_rate", ""),
        "downgrade_f1_on_evaluable": metrics.get("downgrade_f1_on_evaluable", ""),
        "level_macro_f1_on_evaluable": metrics.get("level_macro_f1_on_evaluable", ""),
        "level_ordinal_mae_on_evaluable": metrics.get("level_ordinal_mae_on_evaluable", ""),
        "prediction_unclear_rate": metrics.get("prediction_unclear_rate", ""),
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


def _filter_instances_by_review(
    instances: list[dict[str, Any]],
    *,
    review_limit: int | None,
    max_rows_per_review: int | None,
) -> list[dict[str, Any]]:
    if review_limit is None and max_rows_per_review is None:
        return instances
    selected_reviews: list[str] = []
    counts_by_review: dict[str, int] = {}
    filtered: list[dict[str, Any]] = []
    for instance in instances:
        review_id = str(instance.get("review_id") or "")
        if review_id not in selected_reviews:
            if review_limit is not None and len(selected_reviews) >= review_limit:
                continue
            selected_reviews.append(review_id)
        if max_rows_per_review is not None and counts_by_review.get(review_id, 0) >= max_rows_per_review:
            continue
        counts_by_review[review_id] = counts_by_review.get(review_id, 0) + 1
        filtered.append(instance)
    return filtered


def _indirectness_traces(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for prediction in predictions:
        payload = prediction.get("prediction")
        if not isinstance(payload, dict):
            continue
        judgement = payload.get("judgement") if isinstance(payload.get("judgement"), dict) else {}
        debug = judgement.get("debug") if isinstance(judgement.get("debug"), dict) else {}
        if not isinstance(debug, dict) or not debug:
            continue
        traces.append(
            {
                "instance_id": prediction.get("instance_id"),
                "sof_row_id": prediction.get("sof_row_id"),
                "review_id": prediction.get("review_id"),
                "domain": prediction.get("domain"),
                "input_policy": debug.get("input_policy"),
                "population_source": debug.get("population_source"),
                "signals": debug.get("signals") or [],
                "decision_features": debug.get("decision_features") or {},
                "llm_used": debug.get("llm_used"),
                "fallback_reason": debug.get("fallback_reason"),
            }
        )
    return traces


if __name__ == "__main__":
    main()
