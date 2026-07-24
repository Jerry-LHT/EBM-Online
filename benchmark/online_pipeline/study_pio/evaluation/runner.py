"""Run the Study PIO benchmark."""

from __future__ import annotations

import argparse
import concurrent.futures
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleSource,
    ArticleTable,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics

from benchmark.online_pipeline.shared.jsonl import append_jsonl, read_jsonl, write_jsonl
from benchmark.online_pipeline.shared.report_utils import write_json, write_summary_markdown
from benchmark.online_pipeline.shared.run_utils import default_run_id
from benchmark.online_pipeline.study_pio.evaluation.method_adapter import (
    load_study_pio_benchmark_method,
)
from benchmark.online_pipeline.study_pio.evaluation.io import load_dataset
from benchmark.online_pipeline.study_pio.evaluation.judge import FIELDS, judge_predictions
from benchmark.online_pipeline.study_pio.evaluation.metrics import evaluate_match_rows


MODULE_NAME = "study_pio"
MODULE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = MODULE_DIR / "datasets" / "cochrane_study_pio" / "splits" / "smoke"


def run_benchmark(
    *,
    dataset: str | Path = DEFAULT_DATASET,
    method: str = "gold",
    run_id: str | None = None,
    runs_root: str | Path | None = None,
    limit: int | None = None,
    judge_mode: str = "llm",
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

    completed_before_resume = _completed_instance_ids(run_dir / "judge_matches.jsonl") if resume else set()
    prediction_failures_path = run_dir / "prediction_failures.jsonl"
    predictions = _predictions(
        instances=instances,
        gold_by_id=gold_by_id,
        articles_by_id=articles_by_id,
        method=method,
        llm_config=llm_config,
        run_dir=run_dir,
        resume=resume,
        workers=workers,
    )
    match_rows = judge_predictions(
        instances=instances,
        predictions=predictions,
        gold_by_id=gold_by_id,
        judge_mode=judge_mode,
        llm_config=llm_config,
        output_path=run_dir / "judge_matches.jsonl",
        failure_output_path=run_dir / "judge_failures.jsonl",
        resume=resume,
        workers=workers,
    )
    metrics = evaluate_match_rows(match_rows)
    write_jsonl(run_dir / "predictions.jsonl", predictions)
    write_json(run_dir / "metrics.json", metrics)

    requested_instance_ids = {str(instance["instance_id"]) for instance in instances}
    completed_after_run = _completed_instance_ids(run_dir / "judge_matches.jsonl")
    completed_fields_after_run = _completed_fields_by_instance(run_dir / "judge_matches.jsonl")
    judge_failure_count = _active_judge_failure_count(
        run_dir / "judge_failures.jsonl",
        requested_ids=requested_instance_ids,
        completed_fields=completed_fields_after_run,
    )
    prediction_failure_count = _active_prediction_failure_count(
        prediction_failures_path,
        requested_ids=requested_instance_ids,
        completed_ids={str(row.get("instance_id") or "") for row in predictions},
    )
    run_manifest = {
        "module_name": MODULE_NAME,
        "run_id": resolved_run_id,
        "method": method,
        "judge_mode": judge_mode,
        "limit": limit,
        "resume": resume,
        "workers": workers,
        "requested_count": len(instances),
        "completed_count": len(completed_after_run & requested_instance_ids),
        "skipped_by_resume_count": len(completed_before_resume & requested_instance_ids),
        "failed_count": judge_failure_count
        or prediction_failure_count
        or max(0, len(instances) - len(completed_after_run & requested_instance_ids)),
        "prediction_failed_count": prediction_failure_count,
        "judge_failed_count": judge_failure_count,
    }
    write_json(run_dir / "run_manifest.json", run_manifest)

    summary = {
        "module_name": MODULE_NAME,
        "run_id": resolved_run_id,
        "method": method,
        "judge_mode": judge_mode,
        "limit": limit,
        "resume": resume,
        "workers": workers,
        "instances": len(instances),
        "population_f1": metrics["population_f1"],
        "intervention_comparator_f1": metrics["intervention_comparator_f1"],
        "outcomes_f1": metrics["outcomes_f1"],
        "micro_precision": metrics["micro_precision"],
        "micro_recall": metrics["micro_recall"],
        "micro_f1": metrics["micro_f1"],
        "macro_precision": metrics["macro_precision"],
        "macro_recall": metrics["macro_recall"],
        "macro_f1": metrics["macro_f1"],
        "critical_fields_complete_rate": metrics["critical_fields_complete_rate"],
    }
    write_json(run_dir / "summary.json", summary)
    write_summary_markdown(run_dir / "summary.md", title="study_pio smoke benchmark", summary=summary)
    return {"run_id": resolved_run_id, "run_dir": str(run_dir), "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--method", default="gold")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--judge-mode", choices=("llm", "normalized"), default="llm")
    parser.add_argument("--llm-config", default="llm.local.json")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    result = run_benchmark(
        dataset=args.dataset,
        method=args.method,
        run_id=args.run_id,
        limit=args.limit,
        judge_mode=args.judge_mode,
        llm_config=args.llm_config,
        resume=args.resume,
        workers=args.workers,
    )
    print(result["run_dir"])


def _predictions(
    *,
    instances: list[dict[str, Any]],
    gold_by_id: dict[str, dict[str, Any]],
    articles_by_id: dict[str, dict[str, Any]],
    method: str,
    llm_config: str | Path,
    run_dir: Path,
    resume: bool,
    workers: int,
) -> list[dict[str, Any]]:
    if method in {"gold", "study_pio.gold"}:
        return _gold_predictions(instances=instances, gold_by_id=gold_by_id, articles_by_id=articles_by_id)
    method_obj = load_study_pio_benchmark_method(method)
    if hasattr(method_obj, "configure_for_benchmark"):
        method_obj.configure_for_benchmark(llm_config=llm_config, workers=workers, run_dir=run_dir, resume=resume)
    return _method_predictions(
        instances=instances,
        articles_by_id=articles_by_id,
        method_obj=method_obj,
        run_dir=run_dir,
        resume=resume,
        workers=workers,
        method=method,
    )


def _gold_predictions(
    *,
    instances: list[dict[str, Any]],
    gold_by_id: dict[str, dict[str, Any]],
    articles_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    predictions = []
    for instance in instances:
        instance_id = str(instance["instance_id"])
        missing_articles = [article_id for article_id in instance.get("article_ids", []) if article_id not in articles_by_id]
        if missing_articles:
            raise ValueError(f"Missing article fixture(s) for {instance_id}: {missing_articles}")
        gold = gold_by_id[instance_id]
        predictions.append(
            {
                "instance_id": instance_id,
                "study_id": gold["study_id"],
                "population": gold["population"],
                "intervention_comparator": gold["intervention_comparator"],
                "outcomes": gold["outcomes"],
            }
        )
    return predictions


def _method_predictions(
    *,
    instances: list[dict[str, Any]],
    articles_by_id: dict[str, dict[str, Any]],
    method_obj: Any,
    run_dir: Path,
    resume: bool,
    workers: int,
    method: str,
) -> list[dict[str, Any]]:
    predictions_path = run_dir / "predictions.jsonl"
    failures_path = run_dir / "prediction_failures.jsonl"
    requested_ids = {str(instance["instance_id"]) for instance in instances}
    predictions = _existing_predictions(predictions_path, requested_ids) if resume else []
    completed_ids = {str(row["instance_id"]) for row in predictions}
    if resume:
        write_jsonl(predictions_path, predictions, sort_keys=False)
        _rewrite_active_failures(failures_path, requested_ids=requested_ids, completed_ids=completed_ids)
    else:
        predictions_path.unlink(missing_ok=True)
        failures_path.unlink(missing_ok=True)

    pending_instances = [instance for instance in instances if str(instance["instance_id"]) not in completed_ids]

    def predict_one(instance: dict[str, Any]) -> dict[str, Any]:
        instance_id = str(instance["instance_id"])
        missing_articles = [article_id for article_id in instance.get("article_ids", []) if article_id not in articles_by_id]
        if missing_articles:
            raise ValueError(f"Missing article fixture(s) for {instance_id}: {missing_articles}")
        articles = [_cleaned_article_from_payload(articles_by_id[article_id]) for article_id in instance.get("article_ids", [])]
        result = method_obj.run(
            question_pico=_question_pico_from_instance(instance),
            included_studies=[str(study_id) for study_id in instance.get("included_studies", [])],
            articles=articles,
        )
        return _prediction_from_method_result(instance_id=instance_id, result=result)

    if workers > 1 and len(pending_instances) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_instance = {executor.submit(predict_one, instance): instance for instance in pending_instances}
            for future in concurrent.futures.as_completed(future_to_instance):
                instance = future_to_instance[future]
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
            try:
                prediction = predict_one(instance)
            except Exception as exc:
                append_jsonl(
                    failures_path,
                    [{"instance_id": str(instance["instance_id"]), "error_type": type(exc).__name__, "message": str(exc), "method": method}],
                    sort_keys=False,
                )
                continue
            append_jsonl(predictions_path, [prediction], sort_keys=False)
            predictions.append(prediction)
            completed_ids.add(str(instance["instance_id"]))
    return predictions


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
    except Exception as exc:
        append_jsonl(
            run_dir / "prediction_failures.jsonl",
            [{"instance_id": instance_id, "error_type": type(exc).__name__, "message": str(exc), "method": method}],
            sort_keys=False,
        )
        return
    append_jsonl(run_dir / "predictions.jsonl", [prediction], sort_keys=False)
    predictions.append(prediction)
    completed_ids.add(instance_id)


def _existing_predictions(path: Path, requested_ids: set[str]) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    seen: set[str] = set()
    for row in read_jsonl(path):
        instance_id = str(row.get("instance_id") or "")
        if instance_id in requested_ids and instance_id not in seen:
            rows.append(row)
            seen.add(instance_id)
    return rows


def _active_prediction_failure_count(path: Path, *, requested_ids: set[str], completed_ids: set[str]) -> int:
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
    write_jsonl(path, rows, sort_keys=False)


def _active_judge_failure_count(
    path: Path,
    *,
    requested_ids: set[str],
    completed_fields: dict[str, set[str]],
) -> int:
    if not path.exists():
        return 0
    active_rows = []
    seen: set[tuple[str, str]] = set()
    for row in read_jsonl(path):
        instance_id = str(row.get("instance_id") or "")
        if instance_id not in requested_ids:
            continue
        field = str(row.get("field") or "")
        instance_fields = completed_fields.get(instance_id, set())
        if field in FIELDS:
            key = (instance_id, field)
            if field not in instance_fields and key not in seen:
                active_rows.append(row)
                seen.add(key)
        elif not set(FIELDS).issubset(instance_fields):
            key = (instance_id, "")
            if key not in seen:
                active_rows.append(row)
                seen.add(key)
    write_jsonl(path, active_rows, sort_keys=False)
    return len(active_rows)


def _question_pico_from_instance(instance: dict[str, Any]) -> QuestionPICO:
    pico = instance.get("question_pico") or {}
    return QuestionPICO(
        P=[str(item) for item in (pico.get("P") or [])],
        I=[str(item) for item in (pico.get("I") or [])],
        C=[str(item) for item in (pico.get("C") or [])],
        O=[str(item) for item in (pico.get("O") or [])],
    )


def _cleaned_article_from_payload(payload: dict[str, Any]) -> CleanedArticle:
    metadata = payload.get("metadata") or {}
    source = payload.get("source") or {}
    return CleanedArticle(
        study_id=str(payload.get("study_id") or ""),
        metadata=ArticleMetadata(
            title=str(metadata.get("title") or ""),
            pmid=metadata.get("pmid"),
            pmc_id=metadata.get("pmc_id"),
            source_type=metadata.get("source_type"),
            publication_year=metadata.get("publication_year"),
            mesh_terms=[str(item) for item in (metadata.get("mesh_terms") or [])],
            doi=metadata.get("doi"),
        ),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id=str(section.get("section_id") or ""),
                    title=str(section.get("title") or ""),
                    text=str(section.get("text") or ""),
                )
                for section in ((payload.get("xml_content") or {}).get("sections") or [])
            ]
        ),
        tables=[
            ArticleTable(
                table_id=str(table.get("table_id") or ""),
                caption=str(table.get("caption") or ""),
                rows=table.get("rows") if isinstance(table.get("rows"), list) else [],
            )
            for table in (payload.get("tables") or [])
        ],
        source=ArticleSource(
            database=str(source.get("database") or ""),
            retrieval_rank=source.get("retrieval_rank"),
            retrieval_score=source.get("retrieval_score"),
            raw_source_url=source.get("raw_source_url"),
            raw_record_id=source.get("raw_record_id"),
        )
        if source
        else None,
    )


def _prediction_from_method_result(*, instance_id: str, result: list[StudyPIOCharacteristics]) -> dict[str, Any]:
    if not result:
        return {
            "instance_id": instance_id,
            "study_id": "",
            "population": "",
            "intervention_comparator": "",
            "outcomes": "",
        }
    item = result[0]
    interventions = [entry.description for entry in item.interventions if entry.description]
    comparators = [entry.description for entry in item.comparators if entry.description]
    outcomes = [entry.measurement for entry in item.outcomes if entry.measurement]
    return {
        "instance_id": instance_id,
        "study_id": item.study_id,
        "population": item.population.description,
        "intervention_comparator": " Comparator: ".join(
            part for part in ["; ".join(interventions), "; ".join(comparators)] if part
        ),
        "outcomes": "; ".join(outcomes),
    }


def _completed_instance_ids(path: Path) -> set[str]:
    fields_by_instance = _completed_fields_by_instance(path)
    return {instance_id for instance_id, fields in fields_by_instance.items() if set(FIELDS).issubset(fields)}


def _completed_fields_by_instance(path: Path) -> dict[str, set[str]]:
    if not path.exists():
        return {}
    fields_by_instance: dict[str, set[str]] = {}
    for row in read_jsonl(path):
        instance_id = str(row.get("instance_id") or "")
        field = str(row.get("field") or "")
        if instance_id and field in FIELDS:
            fields_by_instance.setdefault(instance_id, set()).add(field)
    return fields_by_instance


if __name__ == "__main__":
    main()
