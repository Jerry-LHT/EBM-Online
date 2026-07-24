"""Run the Q2PICO smoke benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ebm_backend.online_pipeline.domain.serialization import to_jsonable

from benchmark.online_pipeline.q2pico.evaluation.io import load_dataset
from benchmark.online_pipeline.q2pico.evaluation.judge import judge_predictions
from benchmark.online_pipeline.q2pico.evaluation.metrics import evaluate_match_rows
from benchmark.online_pipeline.shared.jsonl import read_jsonl, write_jsonl
from benchmark.online_pipeline.q2pico.evaluation.method_adapter import load_q2pico_method
from benchmark.online_pipeline.shared.report_utils import write_json, write_summary_markdown
from benchmark.online_pipeline.shared.run_utils import default_run_id


MODULE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = MODULE_DIR / "datasets" / "smoke"


def run_benchmark(
    *,
    dataset: str | Path = DEFAULT_DATASET,
    method: str = "gold",
    run_id: str | None = None,
    runs_root: str | Path | None = None,
    judge_mode: str = "llm",
    llm_config: str | Path = "llm.local.json",
    limit: int | None = None,
    resume: bool = False,
    workers: int = 1,
) -> dict[str, Any]:
    resolved_run_id = run_id or default_run_id()
    run_dir = Path(runs_root or MODULE_DIR / "runs") / resolved_run_id
    instances, gold_by_id = load_dataset(dataset)
    if limit is not None:
        instances = instances[:limit]
        gold_by_id = {str(instance["instance_id"]): gold_by_id[str(instance["instance_id"])] for instance in instances}
    method_obj = None if method in {"gold", "q2pico.gold"} else load_q2pico_method(method)
    completed_before_resume = _completed_instance_ids(run_dir / "judge_matches.jsonl") if resume else set()

    predictions: list[dict[str, Any]] = []
    for instance in instances:
        instance_id = str(instance["instance_id"])
        if method_obj is None:
            prediction = _gold_prediction(instance_id=instance_id, gold=gold_by_id[instance_id])
        else:
            result = method_obj.run(question_text=str(instance["question_text"]))
            prediction = {"instance_id": instance_id, **to_jsonable(result)}
        predictions.append(prediction)

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
    completed_after_run = _completed_instance_ids(run_dir / "judge_matches.jsonl")
    failure_count = _failure_count(run_dir / "judge_failures.jsonl")
    run_manifest = {
        "module_name": "q2pico",
        "run_id": resolved_run_id,
        "method": method,
        "judge_mode": judge_mode,
        "limit": limit,
        "resume": resume,
        "workers": workers,
        "requested_count": len(instances),
        "completed_count": len(completed_after_run),
        "skipped_by_resume_count": len(
            completed_before_resume & {str(instance["instance_id"]) for instance in instances}
        ),
        "failed_count": failure_count or max(0, len(instances) - len(completed_after_run)),
    }
    write_json(run_dir / "run_manifest.json", run_manifest)

    summary = {
        "module_name": "q2pico",
        "run_id": resolved_run_id,
        "method": method,
        "judge_mode": judge_mode,
        "limit": limit,
        "resume": resume,
        "workers": workers,
        "instances": len(instances),
        "micro_precision": metrics["micro_precision"],
        "micro_recall": metrics["micro_recall"],
        "micro_f1": metrics["micro_f1"],
        "macro_f1": metrics["macro_f1"],
        "pico_complete_question_rate": metrics["pico_complete_question_rate"],
    }
    write_json(run_dir / "summary.json", summary)
    write_summary_markdown(run_dir / "summary.md", title="q2pico smoke benchmark", summary=summary)
    return {"run_id": resolved_run_id, "run_dir": str(run_dir), "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--method", default="gold")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--judge-mode", choices=("llm", "normalized"), default="llm")
    parser.add_argument("--llm-config", default="llm.local.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    result = run_benchmark(
        dataset=args.dataset,
        method=args.method,
        run_id=args.run_id,
        judge_mode=args.judge_mode,
        llm_config=args.llm_config,
        limit=args.limit,
        resume=args.resume,
        workers=args.workers,
    )
    print(result["run_dir"])


def _completed_instance_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    rows = read_jsonl(path)
    by_instance: dict[str, set[str]] = {}
    for row in rows:
        by_instance.setdefault(str(row.get("instance_id") or ""), set()).add(str(row.get("slot") or ""))
    return {instance_id for instance_id, slots in by_instance.items() if {"P", "I", "C", "O"}.issubset(slots)}


def _failure_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(read_jsonl(path))


def _gold_prediction(*, instance_id: str, gold: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "P": list(gold.get("P") or []),
        "I": list(gold.get("I") or []),
        "C": list(gold.get("C") or []),
        "O": list(gold.get("O") or []),
    }


if __name__ == "__main__":
    main()
