"""Re-score an existing GRADE RoB LLM run with the current post-processing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from benchmark.online_pipeline.grade.risk_of_bias_downgrade.evaluation.batch_run import analyze_run
from benchmark.online_pipeline.grade.risk_of_bias_downgrade.evaluation.io import load_dataset
from benchmark.online_pipeline.grade.risk_of_bias_downgrade.evaluation.metrics import build_comparisons, evaluate_predictions
from benchmark.online_pipeline.grade.risk_of_bias_downgrade.evaluation.runner import _write_run
from benchmark.online_pipeline.shared.jsonl import read_jsonl
from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_llm import pipeline as method_llm


DOMAIN_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = DOMAIN_DIR / "datasets" / "grade_v3" / "splits" / "dev"
DEFAULT_RUNS_ROOT = DOMAIN_DIR / "runs"


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-score an existing method_llm run without new API calls.")
    parser.add_argument("--source-run-dir", required=True)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    args = parser.parse_args()

    dataset = Path(args.dataset)
    source_run_dir = Path(args.source_run_dir)
    predictions = _rescored_predictions(
        source_run_dir=source_run_dir,
        dataset=dataset,
        offset=args.offset,
        limit=args.limit,
    )
    instances, gold_by_id = load_dataset(dataset)
    if args.offset or args.limit is not None:
        start = max(0, int(args.offset or 0))
        stop = None if args.limit is None else start + max(0, int(args.limit))
        instances = instances[start:stop]
        gold_by_id = {str(instance["instance_id"]): gold_by_id[str(instance["instance_id"])] for instance in instances}
    comparisons = build_comparisons(predictions, gold_by_id)
    metrics = evaluate_predictions(predictions, gold_by_id)
    run_dir = Path(args.runs_root) / args.run_id
    _write_run(
        run_dir=run_dir,
        predictions=predictions,
        comparisons=comparisons,
        metrics=metrics,
        method="method_llm_rescored",
        dataset=dataset,
        run_id=args.run_id,
    )
    summary = analyze_run(run_dir=run_dir, dataset=dataset, offset=args.offset, limit=args.limit)
    print({"run_dir": str(run_dir), "metrics": metrics, "analysis": summary})


def _rescored_predictions(*, source_run_dir: Path, dataset: Path, offset: int = 0, limit: int | None) -> list[dict[str, Any]]:
    instances, _ = load_dataset(dataset)
    if offset or limit is not None:
        start = max(0, int(offset or 0))
        stop = None if limit is None else start + max(0, int(limit))
        instances = instances[start:stop]
    instances_by_id = {str(instance["instance_id"]): instance for instance in instances}
    rows = read_jsonl(source_run_dir / "predictions.jsonl")
    result = []
    for row in rows:
        instance_id = str(row.get("instance_id") or "")
        instance = instances_by_id.get(instance_id)
        if instance is None:
            continue
        judgement = _prediction_judgement(row)
        payload = method_llm._compact_payload(
            domain_evidence=instance.get("domain_evidence") or {},
            evidence_body=instance.get("evidence_body") or {},
        )
        rescored = method_llm._apply_sof_guardrails(judgement, payload)
        result.append(
            {
                "instance_id": row.get("instance_id"),
                "sof_row_id": row.get("sof_row_id"),
                "review_id": row.get("review_id"),
                "domain": row.get("domain"),
                "prediction": {"judgement": rescored},
            }
        )
    return result


def _prediction_judgement(prediction: dict[str, Any]) -> dict[str, Any]:
    if isinstance(prediction.get("judgement"), dict):
        return _without_previous_guardrail(prediction["judgement"])
    payload = prediction.get("prediction")
    if isinstance(payload, dict) and isinstance(payload.get("judgement"), dict):
        return _without_previous_guardrail(payload["judgement"])
    return {}


def _without_previous_guardrail(judgement: dict[str, Any]) -> dict[str, Any]:
    result = dict(judgement)
    rationale = str(result.get("rationale") or "")
    if " Guardrail:" in rationale:
        result["rationale"] = rationale.split(" Guardrail:", 1)[0]
    return result


if __name__ == "__main__":
    main()
