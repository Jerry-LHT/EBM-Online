"""Run Subtask 2 instances in isolated subprocesses with a per-instance timeout.

This helper is for expensive LLM methods whose provider calls can occasionally
hang long enough to block a whole threaded benchmark run. It does not change
the benchmark contract or method behavior: each child process invokes the
normal runner on a one-instance temporary split, then the parent merges normal
prediction artifacts and computes the standard metrics.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from benchmark.online_pipeline.meta_analysis.evaluation_common.io import load_dataset
from benchmark.online_pipeline.meta_analysis.subtask2_study_results.evaluation.metrics import (
    build_comparisons,
    evaluate_predictions,
)
from benchmark.online_pipeline.shared.jsonl import write_jsonl
from benchmark.online_pipeline.shared.report_utils import write_json, write_summary_markdown


TASK_DIR = Path(__file__).resolve().parents[1]
RUNNER = TASK_DIR / "evaluation" / "runner.py"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--hint-policy", default="none")
    parser.add_argument("--llm-config", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--workers", type=int, default=1, help="Number of instances to run concurrently.")
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--end-index", type=int, default=None)
    parser.add_argument("--debug-root", default=None)
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run_instances(
        dataset=Path(args.dataset),
        method=args.method,
        run_id=args.run_id,
        limit=args.limit,
        hint_policy=args.hint_policy,
        llm_config=args.llm_config,
        timeout_seconds=args.timeout_seconds,
        workers=args.workers,
        start_index=args.start_index,
        end_index=args.end_index,
        debug_root=Path(args.debug_root) if args.debug_root else None,
        progress=args.progress,
        resume=args.resume,
    )


def run_instances(
    *,
    dataset: Path,
    method: str,
    run_id: str,
    limit: int | None,
    hint_policy: str,
    llm_config: str | None,
    timeout_seconds: int,
    workers: int,
    start_index: int,
    end_index: int | None,
    debug_root: Path | None,
    progress: bool,
    resume: bool,
) -> None:
    run_dir = TASK_DIR / "runs" / run_id
    if run_dir.exists() and not resume:
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp_root = TASK_DIR / "tmp_rerun" / run_id
    if tmp_root.exists() and not resume:
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)

    instances, gold_by_id = load_dataset(dataset)
    if limit is not None:
        instances = instances[:limit]
    selected = instances[start_index - 1 : end_index]
    predictions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    partial_predictions_path = run_dir / "predictions.partial.jsonl"
    partial_failures_path = run_dir / "failures.partial.jsonl"
    if resume:
        predictions = _read_jsonl(partial_predictions_path)
        seen_prediction_ids = {str(row.get("instance_id") or "") for row in predictions}
        failures = _read_jsonl(partial_failures_path)
    else:
        partial_predictions_path.write_text("", encoding="utf-8")
        partial_failures_path.write_text("", encoding="utf-8")
        seen_prediction_ids = set()

    jobs = [
        (offset, instance)
        for offset, instance in enumerate(selected, start=start_index)
        if str(instance["instance_id"]) not in seen_prediction_ids
    ]
    skipped = len(selected) - len(jobs)
    if progress and skipped:
        _progress(f"skip existing count={skipped}")
    instance_workers = min(max(1, workers), len(jobs)) if jobs else 1
    if instance_workers <= 1:
        for offset, instance in jobs:
            outcome = _run_one_instance(
                offset=offset,
                instance=instance,
                gold_by_id=gold_by_id,
                tmp_root=tmp_root,
                source_dataset=dataset,
                method=method,
                run_id=run_id,
                hint_policy=hint_policy,
                llm_config=llm_config,
                timeout_seconds=timeout_seconds,
                debug_root=debug_root,
                progress=progress,
            )
            _record_outcome(
                outcome=outcome,
                predictions=predictions,
                failures=failures,
                seen_prediction_ids=seen_prediction_ids,
                partial_predictions_path=partial_predictions_path,
                partial_failures_path=partial_failures_path,
            )
    else:
        with ThreadPoolExecutor(max_workers=instance_workers) as executor:
            futures = [
                executor.submit(
                    _run_one_instance,
                    offset=offset,
                    instance=instance,
                    gold_by_id=gold_by_id,
                    tmp_root=tmp_root,
                    source_dataset=dataset,
                    method=method,
                    run_id=run_id,
                    hint_policy=hint_policy,
                    llm_config=llm_config,
                    timeout_seconds=timeout_seconds,
                    debug_root=debug_root,
                    progress=progress,
                )
                for offset, instance in jobs
            ]
            for future in as_completed(futures):
                _record_outcome(
                    outcome=future.result(),
                    predictions=predictions,
                    failures=failures,
                    seen_prediction_ids=seen_prediction_ids,
                    partial_predictions_path=partial_predictions_path,
                    partial_failures_path=partial_failures_path,
                )

    completed_ids = {str(prediction["instance_id"]) for prediction in predictions}
    selected_gold = {str(instance["instance_id"]): gold_by_id[str(instance["instance_id"])] for instance in selected if str(instance["instance_id"]) in completed_ids}
    comparisons = build_comparisons(predictions, selected_gold) if predictions else []
    metrics = evaluate_predictions(predictions, selected_gold) if predictions else {"instance_count": 0}
    metrics["requested_instance_count"] = len(selected)
    metrics["completed_instance_count"] = len(predictions)
    metrics["failed_instance_count"] = len(failures)
    metrics["timeout_seconds"] = timeout_seconds
    metrics["instance_worker_count"] = instance_workers

    write_jsonl(run_dir / "predictions.jsonl", predictions, sort_keys=False)
    write_jsonl(run_dir / "failures.jsonl", failures, sort_keys=False)
    write_jsonl(run_dir / "comparisons.jsonl", comparisons, sort_keys=False)
    write_json(run_dir / "metrics.json", metrics)
    write_json(run_dir / "summary.json", metrics)
    write_summary_markdown(run_dir / "summary.md", title="meta_analysis subtask2 benchmark", summary=metrics)
    write_json(
        run_dir / "run_manifest.json",
        {
            "module_name": "meta_analysis",
            "subtask": "subtask2_study_results",
            "run_id": run_id,
            "method": method,
            "hint_policy": hint_policy,
            "dataset": str(dataset),
            "requested_count": len(selected),
            "completed_count": len(predictions),
            "failed_count": len(failures),
            "timeout_seconds": timeout_seconds,
            "instance_worker_count": instance_workers,
        },
    )
    print(run_dir)


def _run_one_instance(
    *,
    offset: int,
    instance: dict[str, Any],
    gold_by_id: dict[str, dict[str, Any]],
    tmp_root: Path,
    source_dataset: Path,
    method: str,
    run_id: str,
    hint_policy: str,
    llm_config: str | None,
    timeout_seconds: int,
    debug_root: Path | None,
    progress: bool,
) -> dict[str, Any]:
    instance_id = str(instance["instance_id"])
    child_split = _write_child_split(
        tmp_root=tmp_root,
        source_dataset=source_dataset,
        index=offset,
        instance=instance,
        gold=gold_by_id[instance_id],
    )
    child_run_id = f"{run_id}__i{offset:03d}"
    child_debug_dir = (debug_root or (TASK_DIR / "debug_runs" / run_id)) / f"i{offset:03d}"
    started = time.monotonic()
    if progress:
        _progress(f"instance {offset} start instance_id={instance_id}")
    result = _run_child(
        child_split=child_split,
        method=method,
        run_id=child_run_id,
        hint_policy=hint_policy,
        llm_config=llm_config,
        timeout_seconds=timeout_seconds,
        debug_dir=child_debug_dir,
    )
    elapsed = round(time.monotonic() - started, 3)
    if result["status"] == "ok":
        if progress:
            _progress(f"instance {offset} done instance_id={instance_id} elapsed={elapsed}s")
        return {"kind": "prediction", "instance_index": offset, "instance_id": instance_id, "elapsed_seconds": elapsed, "prediction": result["prediction"]}
    if progress:
        _progress(f"instance {offset} failed instance_id={instance_id} elapsed={elapsed}s status={result['status']}")
    return {
        "kind": "failure",
        "instance_index": offset,
        "instance_id": instance_id,
        "status": result["status"],
        "error": result.get("error"),
        "elapsed_seconds": elapsed,
    }


def _record_outcome(
    *,
    outcome: dict[str, Any],
    predictions: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    seen_prediction_ids: set[str],
    partial_predictions_path: Path,
    partial_failures_path: Path,
) -> None:
    if outcome.get("kind") == "prediction":
        prediction = outcome["prediction"]
        predictions.append(prediction)
        seen_prediction_ids.add(str(prediction.get("instance_id") or outcome.get("instance_id") or ""))
        _append_jsonl(partial_predictions_path, prediction)
        return
    failure = {key: value for key, value in outcome.items() if key != "kind"}
    failures.append(failure)
    _append_jsonl(partial_failures_path, failure)


def _write_child_split(*, tmp_root: Path, source_dataset: Path, index: int, instance: dict[str, Any], gold: dict[str, Any]) -> Path:
    split = tmp_root / f"i{index:03d}"
    split.mkdir(parents=True, exist_ok=True)
    (split / "instances.jsonl").write_text(json.dumps(instance, ensure_ascii=False) + "\n", encoding="utf-8")
    (split / "gold.jsonl").write_text(json.dumps(gold, ensure_ascii=False) + "\n", encoding="utf-8")
    shared_src = _dataset_root(source_dataset) / "shared"
    if shared_src.exists():
        shared_dst = split / "shared"
        if not shared_dst.exists():
            shared_dst.symlink_to(shared_src.resolve(), target_is_directory=True)
    return split


def _dataset_root(dataset: Path) -> Path:
    if dataset.name in {"smoke", "dev", "test"} and dataset.parent.name == "splits":
        return dataset.parents[1]
    if dataset.parent.name == "splits":
        return dataset.parents[1]
    return dataset


def _run_child(
    *,
    child_split: Path,
    method: str,
    run_id: str,
    hint_policy: str,
    llm_config: str | None,
    timeout_seconds: int,
    debug_dir: Path,
) -> dict[str, Any]:
    env = dict(os.environ)
    env["SUBTASK2_V10_DEBUG_DIR"] = str(debug_dir)
    env["SUBTASK2_V12_DEBUG_DIR"] = str(debug_dir)
    env["SUBTASK2_TARGETED_DEBUG_DIR"] = str(debug_dir)
    cmd = [
        sys.executable,
        str(RUNNER),
        "--dataset",
        str(child_split),
        "--method",
        method,
        "--run-id",
        run_id,
        "--workers",
        "1",
        "--hint-policy",
        hint_policy,
    ]
    if llm_config:
        cmd.extend(["--llm-config", llm_config])
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(Path.cwd()),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {"status": "timeout", "error": f"timeout_after_{timeout_seconds}s: {exc}"}
    if completed.returncode != 0:
        return {
            "status": "failed",
            "error": (completed.stderr or completed.stdout or "").strip()[-2000:],
        }
    child_run_dir = TASK_DIR / "runs" / run_id
    predictions_path = child_run_dir / "predictions.jsonl"
    if not predictions_path.exists():
        return {"status": "missing_prediction", "error": completed.stderr.strip()[-2000:]}
    rows = [json.loads(line) for line in predictions_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 1:
        return {"status": "invalid_prediction_count", "error": f"count={len(rows)}"}
    return {"status": "ok", "prediction": rows[0]}


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _progress(message: str) -> None:
    print(f"[subtask2-timeout-runner] {message}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
