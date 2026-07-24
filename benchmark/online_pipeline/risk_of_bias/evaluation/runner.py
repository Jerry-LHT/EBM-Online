"""Run the Risk of Bias benchmark."""

from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ebm_backend.online_pipeline.domain.risk_of_bias import RiskOfBiasAssessment, RoB1DomainJudgement
from ebm_backend.online_pipeline.domain.serialization import to_jsonable

from benchmark.online_pipeline.risk_of_bias.evaluation.io import cleaned_article_from_payload, load_dataset
from benchmark.online_pipeline.risk_of_bias.evaluation.metrics import DOMAIN_IDS, LABELS, evaluate_comparisons
from benchmark.online_pipeline.shared.jsonl import append_jsonl, read_jsonl, write_jsonl
from benchmark.online_pipeline.shared.report_utils import write_json, write_summary_markdown
from benchmark.online_pipeline.shared.run_utils import default_run_id
from benchmark.online_pipeline.risk_of_bias.evaluation.method_adapter import (
    load_risk_of_bias_benchmark_method,
)


MODULE_NAME = "risk_of_bias"
MODULE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = MODULE_DIR / "datasets" / "cochrane_rob1" / "splits" / "smoke"
METRICS_INDEX_FIELDS = [
    "run_id",
    "method",
    "dataset",
    "split",
    "sample_size",
    "accuracy",
    "macro_f1",
    "high_risk_recall",
    "domain_macro_f1",
    "domain_coverage_rate",
]


def run_benchmark(
    *,
    dataset: str | Path = DEFAULT_DATASET,
    method: str = "gold",
    run_id: str | None = None,
    runs_root: str | Path | None = None,
    limit: int | None = None,
    llm_config: str | Path = "llm.local.json",
    resume: bool = False,
    workers: int = 1,
) -> dict[str, Any]:
    resolved_run_id = run_id or default_run_id()
    run_dir = Path(runs_root or MODULE_DIR / "runs") / resolved_run_id
    instances, gold_by_id, articles_by_id = load_dataset(dataset)
    if limit is not None:
        instances = instances[:limit]
        gold_by_id = {str(instance["instance_id"]): gold_by_id[str(instance["instance_id"])] for instance in instances}

    completed_before_resume = _completed_instance_ids(run_dir / "predictions.jsonl") if resume else set()
    requested_ids = {str(instance["instance_id"]) for instance in instances}
    predictions = _existing_predictions(run_dir / "predictions.jsonl", requested_ids) if resume else []
    if not resume:
        (run_dir / "predictions.jsonl").unlink(missing_ok=True)
        (run_dir / "prediction_failures.jsonl").unlink(missing_ok=True)
    completed_ids = {str(row["instance_id"]) for row in predictions}

    method_obj = (
        None
        if method in {"gold", "risk_of_bias.gold"}
        else load_risk_of_bias_benchmark_method(method)
    )
    if method_obj is not None and hasattr(method_obj, "configure_for_benchmark"):
        method_obj.configure_for_benchmark(llm_config=llm_config, workers=workers, run_dir=run_dir, resume=resume)

    pending_instances = [instance for instance in instances if str(instance["instance_id"]) not in completed_ids]
    if workers > 1 and len(pending_instances) > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _predict_one,
                    instance=instance,
                    gold_by_id=gold_by_id,
                    articles_by_id=articles_by_id,
                    method_obj=method_obj,
                ): instance
                for instance in pending_instances
            }
            for future in as_completed(futures):
                instance = futures[future]
                _record_prediction_result(
                    future=future,
                    instance_id=str(instance["instance_id"]),
                    method=method,
                    predictions=predictions,
                    completed_ids=completed_ids,
                    run_dir=run_dir,
                )
    else:
        for instance in pending_instances:
            future = _ImmediateFuture(
                lambda instance=instance: _predict_one(
                    instance=instance,
                    gold_by_id=gold_by_id,
                    articles_by_id=articles_by_id,
                    method_obj=method_obj,
                )
            )
            _record_prediction_result(
                future=future,
                instance_id=str(instance["instance_id"]),
                method=method,
                predictions=predictions,
                completed_ids=completed_ids,
                run_dir=run_dir,
            )

    comparisons = build_comparisons(predictions=predictions, gold_by_id=gold_by_id)
    metrics = evaluate_comparisons(comparisons)
    write_jsonl(run_dir / "comparisons.jsonl", comparisons, sort_keys=False)
    write_json(run_dir / "metrics.json", metrics)

    summary = {
        "module_name": MODULE_NAME,
        "run_id": resolved_run_id,
        "method": method,
        "limit": limit,
        "instances": len(instances),
        "accuracy": metrics["accuracy"],
        "macro_f1": metrics["macro_f1"],
        "high_risk_recall": metrics["high_risk_recall"],
        "domain_macro_f1": metrics["domain_macro_f1"],
        "domain_coverage_rate": metrics["domain_coverage_rate"],
    }
    write_json(run_dir / "summary.json", summary)
    write_summary_markdown(run_dir / "summary.md", title="risk_of_bias benchmark", summary=summary)
    failure_count = _active_failure_count(run_dir / "prediction_failures.jsonl", requested_ids=requested_ids, completed_ids=completed_ids)
    _rewrite_active_failures(run_dir / "prediction_failures.jsonl", requested_ids=requested_ids, completed_ids=completed_ids)
    write_json(
        run_dir / "run_manifest.json",
        {
            "module_name": MODULE_NAME,
            "run_id": resolved_run_id,
            "method": method,
            "dataset": str(dataset),
            "limit": limit,
            "resume": resume,
            "workers": workers,
            "requested_count": len(instances),
            "completed_count": len(completed_ids & requested_ids),
            "skipped_by_resume_count": len(completed_before_resume & requested_ids),
            "failed_count": failure_count,
        },
    )
    index_row = _metrics_index_row(dataset=Path(dataset), run_id=resolved_run_id, method=method, limit=limit, metrics=metrics)
    _append_metrics_index(index_row, runs_dir=run_dir.parent)
    write_json(run_dir / "metrics_index_row.json", index_row)
    return {"run_id": resolved_run_id, "run_dir": str(run_dir), "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--method", default="gold")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--llm-config", default="llm.local.json")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = run_benchmark(
        dataset=args.dataset,
        method=args.method,
        run_id=args.run_id,
        limit=args.limit,
        llm_config=args.llm_config,
        workers=args.workers,
        resume=args.resume,
    )
    print(result["run_dir"])


def _gold_prediction(*, instance: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": str(instance["instance_id"]),
        "study_id": str(gold["study_id"]),
        "risk_of_bias": list(gold.get("risk_of_bias") or []),
    }


def _predict_one(
    *,
    instance: dict[str, Any],
    gold_by_id: dict[str, dict[str, Any]],
    articles_by_id: dict[str, dict[str, Any]],
    method_obj: Any,
) -> dict[str, Any]:
    instance_id = str(instance["instance_id"])
    if method_obj is None:
        return _gold_prediction(instance=instance, gold=gold_by_id[instance_id])
    return _method_prediction(instance=instance, articles_by_id=articles_by_id, method_obj=method_obj)


def _record_prediction_result(
    *,
    future: Any,
    instance_id: str,
    method: str,
    predictions: list[dict[str, Any]],
    completed_ids: set[str],
    run_dir: Path,
) -> None:
    try:
        prediction = future.result()
        append_jsonl(run_dir / "predictions.jsonl", [prediction], sort_keys=False)
        predictions.append(prediction)
        completed_ids.add(instance_id)
    except Exception as exc:
        append_jsonl(
            run_dir / "prediction_failures.jsonl",
            [{"instance_id": instance_id, "error": str(exc), "method": method}],
            sort_keys=False,
        )


class _ImmediateFuture:
    def __init__(self, callback):
        self._callback = callback

    def result(self):
        return self._callback()


def _method_prediction(*, instance: dict[str, Any], articles_by_id: dict[str, dict[str, Any]], method_obj: Any) -> dict[str, Any]:
    instance_id = str(instance["instance_id"])
    missing_articles = [article_id for article_id in instance.get("article_ids", []) if article_id not in articles_by_id]
    if missing_articles:
        raise ValueError(f"Missing article fixture(s) for {instance_id}: {missing_articles}")
    articles = [cleaned_article_from_payload(articles_by_id[article_id]) for article_id in instance.get("article_ids", [])]
    result = method_obj.run(included_studies=[str(study_id) for study_id in instance.get("included_studies", [])], articles=articles)
    return _prediction_from_method_result(instance_id=instance_id, result=result)


def _prediction_from_method_result(*, instance_id: str, result: list[RiskOfBiasAssessment]) -> dict[str, Any]:
    if len(result) != 1:
        raise ValueError("Risk of Bias benchmark instances must produce exactly one assessment")
    assessment = result[0]
    return {
        "instance_id": instance_id,
        "study_id": assessment.study_id,
        "risk_of_bias": [
            {
                "domain_id": judgement.domain,
                "domain": judgement.domain,
                "judgement": normalize_prediction_judgement(judgement.judgement),
                "support_text": judgement.rationale,
            }
            for judgement in assessment.domains
        ],
        "assessment": to_jsonable(assessment),
    }


def build_comparisons(*, predictions: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    predictions_by_id = {str(row["instance_id"]): row for row in predictions}
    rows = []
    for instance_id, gold in sorted(gold_by_id.items()):
        prediction = predictions_by_id.get(instance_id, {})
        pred_by_domain = {_domain_id(row): row for row in (prediction.get("risk_of_bias") or []) if isinstance(row, dict)}
        for gold_row in gold.get("risk_of_bias") or []:
            domain_id = str(gold_row.get("domain_id") or "")
            pred_row = pred_by_domain.get(domain_id)
            pred_judgement = normalize_prediction_judgement(pred_row.get("judgement")) if pred_row else None
            valid_prediction = pred_judgement in LABELS
            gold_judgement = str(gold_row.get("judgement") or "")
            rows.append(
                {
                    "instance_id": instance_id,
                    "study_id": str(gold.get("study_id") or prediction.get("study_id") or ""),
                    "domain_id": domain_id,
                    "gold_judgement": gold_judgement,
                    "predicted_judgement": pred_judgement,
                    "covered": pred_row is not None,
                    "valid_prediction": valid_prediction,
                    "match": bool(valid_prediction and pred_judgement == gold_judgement),
                }
            )
    return rows


def normalize_prediction_judgement(value: Any) -> str | None:
    text = str(value or "").lower().strip()
    if text in LABELS:
        return text
    if "low" in text:
        return "low_risk"
    if "unclear" in text:
        return "unclear_risk"
    if "high" in text:
        return "high_risk"
    return None


def _domain_id(row: dict[str, Any]) -> str:
    value = str(row.get("domain_id") or row.get("domain") or "")
    return value if value in DOMAIN_IDS else value.lower().strip()


def _completed_instance_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {str(row.get("instance_id") or "") for row in read_jsonl(path)}


def _existing_predictions(path: Path, requested_ids: set[str]) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [row for row in read_jsonl(path) if str(row.get("instance_id") or "") in requested_ids]


def _active_failure_count(path: Path, *, requested_ids: set[str], completed_ids: set[str]) -> int:
    if not path.exists():
        return 0
    return sum(
        1
        for row in read_jsonl(path)
        if str(row.get("instance_id") or "") in requested_ids and str(row.get("instance_id") or "") not in completed_ids
    )


def _rewrite_active_failures(path: Path, *, requested_ids: set[str], completed_ids: set[str]) -> None:
    if not path.exists():
        return
    rows = [
        row
        for row in read_jsonl(path)
        if str(row.get("instance_id") or "") in requested_ids and str(row.get("instance_id") or "") not in completed_ids
    ]
    if rows:
        write_jsonl(path, rows, sort_keys=False)
    else:
        path.unlink(missing_ok=True)


def _metrics_index_row(*, dataset: Path, run_id: str, method: str, limit: int | None, metrics: dict[str, Any]) -> dict[str, Any]:
    dataset_root = _dataset_root_from_split(dataset)
    return {
        "run_id": run_id,
        "method": method,
        "dataset": str(dataset_root),
        "split": dataset.name if dataset.parent.name == "splits" else "all",
        "sample_size": limit or metrics.get("instance_count", ""),
        "accuracy": metrics.get("accuracy", ""),
        "macro_f1": metrics.get("macro_f1", ""),
        "high_risk_recall": metrics.get("high_risk_recall", ""),
        "domain_macro_f1": metrics.get("domain_macro_f1", ""),
        "domain_coverage_rate": metrics.get("domain_coverage_rate", ""),
    }


def _append_metrics_index(row: dict[str, Any], *, runs_dir: Path) -> None:
    path = runs_dir / "metrics_index.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _read_metrics_index_rows(path)
    rows = [existing for existing in rows if existing.get("run_id") != row.get("run_id")]
    rows.append({field: row.get(field, "") for field in METRICS_INDEX_FIELDS})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=METRICS_INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _read_metrics_index_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _dataset_root_from_split(dataset: Path) -> Path:
    if dataset.parent.name == "splits":
        return dataset.parent.parent
    return dataset


if __name__ == "__main__":
    main()
