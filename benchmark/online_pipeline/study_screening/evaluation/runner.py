"""Run the study screening smoke benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import ScreeningDecision, StudyScreeningResult
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from benchmark.online_pipeline.shared.jsonl import write_jsonl
from benchmark.online_pipeline.study_screening.evaluation.method_adapter import (
    load_article_screening_method,
)
from benchmark.online_pipeline.shared.report_utils import write_json, write_summary_markdown
from benchmark.online_pipeline.shared.run_utils import default_run_id
from benchmark.online_pipeline.study_screening.evaluation.io import (
    articles_from_instance,
    load_dataset,
    screening_criteria_from_instance,
)
from benchmark.online_pipeline.study_screening.evaluation.metrics import evaluate


MODULE_NAME = "study_screening"
MODULE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = MODULE_DIR / "datasets" / "csmed_ft" / "splits" / "smoke"


def run_benchmark(
    *,
    dataset: str | Path = DEFAULT_DATASET,
    method: str = "gold",
    run_id: str | None = None,
    runs_root: str | Path | None = None,
    limit: int | None = None,
    section_policy: str = "abstract_plus_fulltext",
    max_abstract_chars: int | None = None,
    max_full_text_chars: int | None = 12000,
) -> dict[str, Any]:
    resolved_run_id = run_id or default_run_id()
    run_dir = Path(runs_root or MODULE_DIR / "runs") / resolved_run_id
    instances, gold_by_id = load_dataset(dataset)
    if limit is not None:
        instances = instances[:limit]
        gold_by_id = {str(instance["instance_id"]): gold_by_id[str(instance["instance_id"])] for instance in instances}
    method_obj = (
        None
        if method in {"gold", "study_screening.gold"}
        else load_article_screening_method(method)
    )

    predictions: list[dict[str, Any]] = []
    for instance in instances:
        instance_id = str(instance["instance_id"])
        criteria = screening_criteria_from_instance(instance)
        articles = articles_from_instance(
            instance,
            section_policy=section_policy,
            max_abstract_chars=max_abstract_chars,
            max_full_text_chars=max_full_text_chars,
        )
        result = (
            _gold_result(instance=instance, gold=gold_by_id[instance_id])
            if method_obj is None
            else _run_article_screening_method(
                method_obj=method_obj,
                question_text=str(instance["question_text"]),
                screening_criteria=criteria,
                articles=articles,
            )
        )
        if len(result.decisions) != 1:
            raise ValueError("Study screening smoke instances must produce exactly one decision")
        decision = result.decisions[0]
        predictions.append(
            {
                "instance_id": instance_id,
                "study_id": decision.study_id,
                "decision": decision.decision,
                "rationale": decision.rationale,
                "exclusion_reason": decision.exclusion_reason,
                "screening_result": to_jsonable(result),
            }
        )

    metrics = evaluate(predictions, gold_by_id)
    write_jsonl(run_dir / "predictions.jsonl", predictions)
    write_json(run_dir / "metrics.json", metrics)
    write_json(
        run_dir / "run_manifest.json",
        {
            "module_name": MODULE_NAME,
            "run_id": resolved_run_id,
            "method": method,
            "limit": limit,
            "section_policy": section_policy,
            "max_abstract_chars": max_abstract_chars,
            "max_full_text_chars": max_full_text_chars,
            "requested_count": len(instances),
            "completed_count": len(predictions),
            "failed_count": max(0, len(instances) - len(predictions)),
        },
    )
    summary = {
        "module_name": MODULE_NAME,
        "run_id": resolved_run_id,
        "method": method,
        "limit": limit,
        "section_policy": section_policy,
        "max_abstract_chars": max_abstract_chars,
        "max_full_text_chars": max_full_text_chars,
        "instances": len(instances),
        "include_f1": metrics["include_f1"],
        "false_negative_count": metrics["false_negative_count"],
        "accuracy": metrics["accuracy"],
        "macro_f1": metrics["macro_f1"],
    }
    write_json(run_dir / "summary.json", summary)
    write_summary_markdown(run_dir / "summary.md", title="study_screening smoke benchmark", summary=summary)
    return {"run_id": resolved_run_id, "run_dir": str(run_dir), "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--method", default="gold")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--section-policy", choices=("abstract_only", "abstract_plus_fulltext"), default="abstract_plus_fulltext")
    parser.add_argument("--max-abstract-chars", type=int, default=None)
    parser.add_argument("--max-full-text-chars", type=int, default=12000)
    args = parser.parse_args()
    result = run_benchmark(
        dataset=args.dataset,
        method=args.method,
        run_id=args.run_id,
        limit=args.limit,
        section_policy=args.section_policy,
        max_abstract_chars=args.max_abstract_chars,
        max_full_text_chars=args.max_full_text_chars,
    )
    print(result["run_dir"])


def _question_pico(payload: dict[str, Any]) -> QuestionPICO:
    return QuestionPICO(
        P=list(payload.get("P") or []),
        I=list(payload.get("I") or []),
        C=list(payload.get("C") or []),
        O=list(payload.get("O") or []),
    )


def _run_article_screening_method(
    *,
    method_obj,
    question_text: str,
    screening_criteria,
    articles,
) -> StudyScreeningResult:
    if hasattr(method_obj, "run_article_screening"):
        return method_obj.run_article_screening(
            question_text=question_text,
            screening_criteria=screening_criteria,
            articles=articles,
        )
    raise TypeError(
        "study_screening benchmark evaluates the Article Screening subtask. "
        "Methods must implement run_article_screening(question_text, screening_criteria, articles), "
        "or use --method gold for the benchmark baseline."
    )


def _gold_result(*, instance: dict[str, Any], gold: dict[str, Any]) -> StudyScreeningResult:
    criteria = screening_criteria_from_instance(instance)
    decision = ScreeningDecision(
        study_id=str(gold["study_id"]),
        decision=str(gold["gold_decision"]),
        rationale=str(gold.get("gold_reason") or "Gold screening label."),
        exclusion_reason=str(gold.get("gold_reason") or "") if gold.get("gold_decision") == "exclude" else None,
    )
    included_studies = [decision.study_id] if decision.decision == "include" else []
    return StudyScreeningResult(screening_criteria=criteria, decisions=[decision], included_studies=included_studies)


if __name__ == "__main__":
    main()
