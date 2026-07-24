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
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.evidence import build_threshold_research_context
from benchmark.online_pipeline.grade.imprecision.evaluation.io import load_dataset
from benchmark.online_pipeline.grade.imprecision.evaluation.metrics import build_comparisons, evaluate_predictions
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
    "threshold_found_rate",
    "threshold_applicable_rate",
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
    progress: bool = False,
    threshold_context_variant: str = "baseline",
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
    instances = [_apply_threshold_context_variant(instance, threshold_context_variant) for instance in instances]
    gold_by_id = {str(instance["instance_id"]): gold_by_id[str(instance["instance_id"])] for instance in instances}
    method_obj = (
        None
        if method in {"gold", "grade.gold", "oracle"}
        else load_grade_domain_benchmark_method("imprecision", method)
    )
    existing_predictions = _load_existing_predictions(run_dir / "predictions.jsonl") if resume else []
    predictions = _predict_all(
        instances=instances,
        gold_by_id=gold_by_id,
        method=method,
        method_obj=method_obj,
        workers=workers,
        run_dir=run_dir,
        existing_predictions=existing_predictions,
        progress=progress,
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
        threshold_context_variant=threshold_context_variant,
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
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--threshold-context-variant", choices=["baseline", "sof_row_safe"], default="baseline")
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
        progress=args.progress,
        threshold_context_variant=args.threshold_context_variant,
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
    method_obj = method_obj or load_grade_domain_benchmark_method("imprecision", method)
    output = _run_method_on_instance(method_obj=method_obj, instance=instance)
    return {
        "instance_id": instance["instance_id"],
        "sof_row_id": instance.get("sof_row_id"),
        "review_id": instance.get("review_id"),
        "domain": instance.get("domain"),
        "prediction": to_jsonable(output),
    }


def _run_method_on_instance(*, method_obj: Any, instance: dict[str, Any]) -> dict[str, Any]:
    domain = str(instance.get("domain") or "")
    domain_method = _domain_method(method_obj, domain)
    if domain_method is None or not hasattr(domain_method, "run"):
        raise TypeError(f"GRADE benchmark method does not expose a run(...) method for domain {domain!r}.")
    judgement = domain_method.run(
        domain_evidence=_dict_value(instance.get("domain_evidence")),
        evidence_body=_evidence_body_for_instance(instance),
    )
    return {
        "instance_id": instance.get("instance_id"),
        "sof_row_id": instance.get("sof_row_id"),
        "review_id": instance.get("review_id"),
        "domain": domain,
        "judgement": judgement,
    }


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
) -> list[dict[str, Any]]:
    completed_by_id = _predictions_by_id(existing_predictions or [])
    pending = [instance for instance in instances if str(instance.get("instance_id") or "") not in completed_by_id]
    if progress and completed_by_id:
        print(f"[resume] loaded {len(completed_by_id)} existing predictions; pending {len(pending)}/{len(instances)}", flush=True)
    predictions_path = run_dir / "predictions.jsonl" if run_dir is not None else None
    if not completed_by_id and predictions_path is not None:
        predictions_path.parent.mkdir(parents=True, exist_ok=True)
        predictions_path.write_text("", encoding="utf-8")
    if _supports_threshold_reuse(method=method, method_obj=method_obj):
        new_predictions = _predict_all_with_threshold_reuse(
            instances=pending,
            gold_by_id=gold_by_id,
            method=method,
            method_obj=method_obj,
            workers=workers,
            predictions_path=predictions_path,
            progress=progress,
            completed_count=len(completed_by_id),
            total_count=len(instances),
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
            )
            new_predictions.append(prediction)
            _append_prediction(predictions_path, prediction)
            if progress:
                print(f"[predict] {len(completed_by_id) + index}/{len(instances)} {instance['instance_id']}", flush=True)
        completed_by_id.update(_predictions_by_id(new_predictions))
        return [completed_by_id[str(instance["instance_id"])] for instance in instances if str(instance["instance_id"]) in completed_by_id]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _predict,
                instance=instance,
                gold=gold_by_id[str(instance["instance_id"])],
                method=method,
                method_obj=method_obj,
            ): instance
            for instance in pending
        }
        new_predictions = []
        for completed, future in enumerate(as_completed(futures), start=1):
            instance = futures[future]
            prediction = future.result()
            new_predictions.append(prediction)
            _append_prediction(predictions_path, prediction)
            if progress:
                print(f"[predict] {len(completed_by_id) + completed}/{len(instances)} {instance['instance_id']}", flush=True)
        completed_by_id.update(_predictions_by_id(new_predictions))
        return [completed_by_id[str(instance["instance_id"])] for instance in instances if str(instance["instance_id"]) in completed_by_id]


def _supports_threshold_reuse(*, method: str, method_obj: Any | None) -> bool:
    imprecision_method = _domain_method(method_obj, "imprecision") if method_obj is not None else None
    return (
        method.endswith("method_llm_web")
        and imprecision_method is not None
        and hasattr(imprecision_method, "research_threshold")
        and hasattr(imprecision_method, "run_with_threshold")
    )


def _predict_all_with_threshold_reuse(
    *,
    instances: list[dict[str, Any]],
    gold_by_id: dict[str, dict[str, Any]],
    method: str,
    method_obj: Any,
    workers: int,
    predictions_path: Path | None = None,
    progress: bool = False,
    completed_count: int = 0,
    total_count: int | None = None,
) -> list[dict[str, Any]]:
    if not instances:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    for instance in instances:
        groups.setdefault(_threshold_query_key(instance), []).append(instance)

    imprecision_method = _domain_method(method_obj, "imprecision")
    if imprecision_method is None:
        raise TypeError("GRADE method does not expose an imprecision domain method.")
    key_order = list(groups)

    def research_for_key(key: str) -> tuple[str, dict[str, Any], str]:
        representative = groups[key][0]
        threshold = imprecision_method.research_threshold(
            domain_evidence=_dict_value(representative.get("domain_evidence")),
            evidence_body=_evidence_body_for_instance(representative),
        )
        return key, threshold, str(representative.get("instance_id") or "")

    total = total_count if total_count is not None else len(instances)
    predictions: list[dict[str, Any]] = []
    completed_instances = 0

    def emit_group(key: str, threshold: dict[str, Any], source_id: str) -> None:
        nonlocal completed_instances
        group_predictions = []
        for instance in groups[key]:
            output = _predict_with_reused_threshold(
                instance=instance,
                gold=gold_by_id[str(instance["instance_id"])],
                method=method,
                method_obj=method_obj,
                threshold=threshold,
                threshold_query_key=key,
                threshold_source_instance_id=source_id,
            )
            predictions.append(output)
            group_predictions.append(output)
            completed_instances += 1
        if group_predictions:
            _append_predictions(predictions_path, group_predictions)
        if progress:
            print(
                f"[threshold] {len(predictions)}/{len(instances)} pending, total {completed_count + completed_instances}/{total}; key={key[:120]}",
                flush=True,
            )

    if workers <= 1:
        for key in key_order:
            researched_key, threshold, source_id = research_for_key(key)
            emit_group(researched_key, threshold, source_id)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(research_for_key, key): key for key in key_order}
            for future in as_completed(futures):
                researched_key, threshold, source_id = future.result()
                emit_group(researched_key, threshold, source_id)
    return predictions


def _predict_with_reused_threshold(
    *,
    instance: dict[str, Any],
    gold: dict[str, Any],
    method: str,
    method_obj: Any,
    threshold: dict[str, Any],
    threshold_query_key: str,
    threshold_source_instance_id: str,
) -> dict[str, Any]:
    if method in {"gold", "grade.gold", "oracle"}:
        return _predict(instance=instance, gold=gold, method=method, method_obj=method_obj)
    imprecision_method = _domain_method(method_obj, "imprecision")
    if imprecision_method is None:
        raise TypeError("GRADE method does not expose an imprecision domain method.")
    judgement = imprecision_method.run_with_threshold(
        domain_evidence=_dict_value(instance.get("domain_evidence")),
        evidence_body=_evidence_body_for_instance(instance),
        threshold=threshold,
    )
    debug = judgement.setdefault("debug", {})
    if isinstance(debug, dict):
        debug["threshold_query_key"] = threshold_query_key
        debug["threshold_reused"] = str(instance.get("instance_id") or "") != threshold_source_instance_id
        debug["threshold_source_instance_id"] = threshold_source_instance_id
    return {
        "instance_id": instance["instance_id"],
        "sof_row_id": instance.get("sof_row_id"),
        "review_id": instance.get("review_id"),
        "domain": instance.get("domain"),
        "prediction": to_jsonable(
            {
                "instance_id": instance.get("instance_id"),
                "sof_row_id": instance.get("sof_row_id"),
                "review_id": instance.get("review_id"),
                "domain": instance.get("domain"),
                "judgement": judgement,
            }
        ),
    }


def _domain_method(method_obj: Any | None, domain: str) -> Any | None:
    if method_obj is None:
        return None
    domain_methods = getattr(method_obj, "domain_methods", None)
    if isinstance(domain_methods, dict):
        return domain_methods.get(domain)
    if getattr(method_obj, "domain", None) == domain:
        return method_obj
    return None


def _load_existing_predictions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_jsonl(path)


def _predictions_by_id(predictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for prediction in predictions:
        instance_id = str(prediction.get("instance_id") or "")
        if instance_id:
            rows[instance_id] = prediction
    return rows


def _append_prediction(path: Path | None, prediction: dict[str, Any]) -> None:
    _append_predictions(path, [prediction])


def _append_predictions(path: Path | None, predictions: list[dict[str, Any]]) -> None:
    if path is None or not predictions:
        return
    append_jsonl(path, predictions, sort_keys=False)


def _apply_threshold_context_variant(instance: dict[str, Any], variant: str) -> dict[str, Any]:
    if variant == "baseline":
        return instance
    if variant != "sof_row_safe":
        raise ValueError(f"Unsupported threshold context variant: {variant}")
    evidence_body = _evidence_body_for_instance(instance)
    overrides = _sof_row_safe_threshold_overrides(evidence_body)
    if not overrides:
        return instance
    existing = _dict_value(instance.get("domain_evidence"))
    return {**instance, "domain_evidence": {**existing, "threshold_research_overrides": overrides}}


def _sof_row_safe_threshold_overrides(evidence_body: dict[str, Any]) -> dict[str, Any]:
    sof_context = _dict_value(evidence_body.get("sof_context"))
    overrides = {
        "condition_context": _clean_context_value(sof_context.get("population_text")),
        "outcome_concept": _clean_context_value(sof_context.get("outcome_name")),
        "timepoint_window": _clean_context_value(sof_context.get("timepoint_text")),
        "clinical_setting_context": _clean_context_value(sof_context.get("setting_text")),
        "intervention_context": _clean_context_value(sof_context.get("intervention_text")),
        "comparator_context": _clean_context_value(sof_context.get("comparison_text")),
        "threshold_context_variant": "sof_row_safe",
    }
    return {key: value for key, value in overrides.items() if value}


def _clean_context_value(value: Any) -> str | None:
    text = " ".join(str(value or "").split()).strip(" \t\r\n:;,-")
    text = text.replace("‐", "-")
    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = text.replace("c-IVF", "c-IVF")
    text = text.replace("c‐IVF", "c-IVF")
    text = text.replace("ICSI", "ICSI")
    text = text.removesuffix(" were included in this review.").strip()
    text = text.removesuffix(" was included in this review.").strip()
    return text or None


def _threshold_query_key(instance: dict[str, Any]) -> str:
    context = build_threshold_research_context(
        domain_evidence=_dict_value(instance.get("domain_evidence")),
        evidence_body=_evidence_body_for_instance(instance),
    )
    return str(context.get("threshold_research_key") or "")


def _key_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _evidence_body_for_instance(instance: dict[str, Any]) -> dict[str, Any]:
    evidence_body = _dict_value(instance.get("evidence_body"))
    if isinstance(instance.get("question_pico"), dict) and "question_pico" not in evidence_body:
        return {**evidence_body, "question_pico": instance.get("question_pico")}
    return evidence_body


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
    threshold_context_variant: str = "baseline",
) -> None:
    write_jsonl(run_dir / "predictions.jsonl", predictions, sort_keys=False)
    write_jsonl(run_dir / "comparisons.jsonl", comparisons, sort_keys=False)
    write_jsonl(run_dir / "threshold_traces.jsonl", _threshold_traces(predictions), sort_keys=False)
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
            "domain": "imprecision",
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
            "threshold_context_variant": threshold_context_variant,
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
        "threshold_found_rate": metrics.get("threshold_found_rate", ""),
        "threshold_applicable_rate": metrics.get("threshold_applicable_rate", ""),
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


def _threshold_traces(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for prediction in predictions:
        payload = prediction.get("prediction")
        if not isinstance(payload, dict):
            continue
        judgement = payload.get("judgement") if isinstance(payload.get("judgement"), dict) else {}
        debug = judgement.get("debug") if isinstance(judgement.get("debug"), dict) else None
        if debug is None:
            debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else None
        if not isinstance(debug, dict):
            continue
        traces.append(
            {
                "instance_id": prediction.get("instance_id"),
                "sof_row_id": prediction.get("sof_row_id"),
                "review_id": prediction.get("review_id"),
                "domain": prediction.get("domain"),
                "setting_context": debug.get("setting_context") or {},
                "numeric_features": debug.get("numeric_features") or {},
                "threshold_result": debug.get("threshold_result") or {},
                "decision_features": debug.get("decision_features") or {},
                "threshold_research_context": (debug.get("threshold_result") or {}).get("threshold_research_context") or {},
                "threshold_audit_context": (debug.get("threshold_result") or {}).get("threshold_audit_context") or {},
                "threshold_research_key": (debug.get("threshold_result") or {}).get("threshold_research_key"),
                "threshold_query_key": debug.get("threshold_query_key"),
                "threshold_reused": debug.get("threshold_reused"),
                "threshold_source_instance_id": debug.get("threshold_source_instance_id"),
            }
        )
    return traces


if __name__ == "__main__":
    main()
