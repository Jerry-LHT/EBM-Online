"""Shared smoke runner logic for online pipeline module benchmarks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.meta_analysis import MetaAnalysisResultPackage
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.risk_of_bias import RiskOfBiasAssessment
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.domain.serialization import from_jsonable
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics
from benchmark.online_pipeline.search_retrieval.evaluation.method_adapter import (
    load_search_retrieval_benchmark_use_case,
)
from benchmark.online_pipeline.shared.jsonl import read_jsonl, write_jsonl
from benchmark.online_pipeline.shared.report_utils import write_json, write_summary_markdown


def default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_structural_module_benchmark(
    *,
    module_name: str,
    dataset: str | Path,
    method: str,
    run_id: str | None,
    module_dir: str | Path,
) -> dict[str, Any]:
    dataset_dir = Path(dataset)
    module_root = Path(module_dir)
    resolved_run_id = run_id or default_run_id()
    run_dir = module_root / "runs" / resolved_run_id

    instances = read_jsonl(dataset_dir / "instances.jsonl")
    gold_rows = _read_optional_jsonl(dataset_dir / "gold.jsonl")
    gold_ids = {row.get("instance_id") for row in gold_rows}
    if module_name != "search_retrieval":
        raise ValueError(f"No structural benchmark method adapter for module '{module_name}'")
    method_obj = load_search_retrieval_benchmark_use_case(method)

    predictions: list[dict[str, Any]] = []
    for instance in instances:
        instance_id = str(instance["instance_id"])
        output = _run_module_method(module_name, method_obj, instance)
        predictions.append(
            {
                "instance_id": instance_id,
                "module_name": module_name,
                "prediction": to_jsonable(output),
            }
        )

    metrics = _structural_metrics(instances=instances, predictions=predictions, gold_ids=gold_ids)
    write_jsonl(run_dir / "predictions.jsonl", predictions)
    write_json(run_dir / "metrics.json", metrics)
    summary = {
        "module_name": module_name,
        "run_id": resolved_run_id,
        "method": method,
        "instances": len(instances),
        **metrics,
    }
    write_json(run_dir / "summary.json", summary)
    write_summary_markdown(run_dir / "summary.md", title=f"{module_name} smoke benchmark", summary=summary)
    return {"run_id": resolved_run_id, "run_dir": str(run_dir), "metrics": metrics}


def add_common_runner_args(parser: argparse.ArgumentParser, *, default_dataset: Path, default_method: str) -> None:
    parser.add_argument("--dataset", default=str(default_dataset))
    parser.add_argument("--method", default=default_method)
    parser.add_argument("--run-id", default=None)


def _read_optional_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_jsonl(path)


def _structural_metrics(
    *,
    instances: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    gold_ids: set[Any],
) -> dict[str, Any]:
    instance_ids = [row.get("instance_id") for row in instances]
    prediction_ids = [row.get("instance_id") for row in predictions]
    prediction_id_set = set(prediction_ids)
    required_ids_present = all(instance_id in prediction_id_set for instance_id in instance_ids)
    schema_valid = all(
        isinstance(row.get("instance_id"), str) and isinstance(row.get("prediction"), (dict, list))
        for row in predictions
    )
    join_keys_valid = not gold_ids or gold_ids.issubset(prediction_id_set)
    return {
        "schema_valid": schema_valid,
        "required_ids_present": required_ids_present,
        "join_keys_valid": join_keys_valid,
        "prediction_count": len(predictions),
        "gold_count": len(gold_ids),
    }


def _run_module_method(module_name: str, method_obj, instance: dict[str, Any]):
    if module_name == "search_retrieval":
        max_results = int(
            instance.get("max_results_per_source")
            or instance.get("max_results")
            or 20
        )
        return method_obj.execute(
            question_pico=_required_dataclass(instance, "question_pico", QuestionPICO),
            config=ModuleRunConfig(
                max_candidates_per_source=int(
                    instance.get("max_candidates_per_source")
                    or max(100, max_results)
                ),
                max_results_per_source=max_results,
            ),
        )
    if module_name == "study_screening":
        return method_obj.run(
            question_text=_required_text(instance, "question_text"),
            question_pico=_required_dataclass(instance, "question_pico", QuestionPICO),
            constraints=ModuleRunConfig().constraints,
            articles=_required_dataclass_list(instance, "articles", CleanedArticle),
        )
    if module_name == "study_pio":
        return method_obj.run(
            question_pico=_required_dataclass(instance, "question_pico", QuestionPICO),
            included_studies=_required_text_list(instance, "included_studies"),
            articles=_required_dataclass_list(instance, "articles", CleanedArticle),
        )
    if module_name == "risk_of_bias":
        return method_obj.run(
            included_studies=_required_text_list(instance, "included_studies"),
            articles=_required_dataclass_list(instance, "articles", CleanedArticle),
        )
    if module_name == "meta_analysis":
        return method_obj.run(
            review_id=_required_text(instance, "review_id"),
            question_text=_required_text(instance, "question_text"),
            question_pico=_required_dataclass(instance, "question_pico", QuestionPICO),
            included_studies=_required_text_list(instance, "included_studies"),
            articles=_required_dataclass_list(instance, "articles", CleanedArticle),
        )
    if module_name == "grade":
        return method_obj.run(
            review_id=_required_text(instance, "review_id"),
            question_text=_required_text(instance, "question_text"),
            question_pico=_required_dataclass(instance, "question_pico", QuestionPICO),
            screening_criteria=_required_dataclass(instance, "screening_criteria", ScreeningCriteria),
            study_characteristics=_required_dataclass_list(instance, "study_characteristics", StudyPIOCharacteristics),
            risk_of_bias=_required_dataclass_list(instance, "risk_of_bias", RiskOfBiasAssessment),
            meta_analysis_result=_required_dataclass(instance, "meta_analysis_result", MetaAnalysisResultPackage),
        )
    raise ValueError(f"No structural runner for module '{module_name}'")


def _required(instance: dict[str, Any], field_name: str) -> Any:
    value = instance.get(field_name)
    if value is None:
        raise ValueError(f"{field_name} is required in benchmark instance")
    return value


def _required_text(instance: dict[str, Any], field_name: str) -> str:
    value = str(_required(instance, field_name)).strip()
    if not value:
        raise ValueError(f"{field_name} is required in benchmark instance")
    return value


def _required_text_list(instance: dict[str, Any], field_name: str) -> list[str]:
    value = _required(instance, field_name)
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list in benchmark instance")
    return [str(item) for item in value]


def _required_dataclass(instance: dict[str, Any], field_name: str, target_type: type):
    return from_jsonable(_required(instance, field_name), target_type, path=field_name)


def _required_dataclass_list(instance: dict[str, Any], field_name: str, item_type: type):
    return from_jsonable(_required(instance, field_name), list[item_type], path=field_name)
