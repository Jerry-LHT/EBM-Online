from __future__ import annotations

import json
from pathlib import Path

import pytest

from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.workflow import (
    OnlineEBMWorkflowResult,
    WorkflowStageRecord,
)
from ebm_backend.online_pipeline.infrastructure.persistence.workflow_runs.file_store import (
    FileWorkflowRunStore,
    WorkflowRunCorruptError,
    WorkflowRunNotFoundError,
)


def test_file_store_returns_partial_stage_snapshot_before_finalization(
    tmp_path: Path,
) -> None:
    store = FileWorkflowRunStore(tmp_path / "runs")
    store.create_run(
        run_id="run-1",
        review_id="review-1",
        question_text="question",
        request={"expand_outcomes": True},
    )
    store.save_stage(
        run_id="run-1",
        sequence=10,
        stage=WorkflowStageRecord(
            stage_name="q2pico",
            status="succeeded",
            output={"P": ["adults"], "I": [], "C": [], "O": []},
        ),
    )

    snapshot = store.load_run(run_id="run-1")

    assert snapshot["run_id"] == "run-1"
    assert snapshot["status"] == "running"
    assert snapshot["persistence_status"] == "partial"
    assert snapshot["question_pico"]["P"] == ["adults"]
    assert snapshot["stages"][0]["stage_name"] == "q2pico"


def test_file_store_returns_exact_final_workflow_result(tmp_path: Path) -> None:
    store = FileWorkflowRunStore(tmp_path / "runs")
    store.create_run(
        run_id="run-2",
        review_id="review-2",
        question_text="question",
        request={},
    )
    result = OnlineEBMWorkflowResult(
        review_id="review-2",
        question_text="question",
        status="succeeded",
        run_id="run-2",
        persistence_status="succeeded",
        question_pico=QuestionPICO(P=["adults"]),
        grade_status="succeeded",
    )

    store.finalize_run(run_id="run-2", result=result)

    loaded = store.load_run(run_id="run-2")
    assert loaded["run_id"] == "run-2"
    assert loaded["status"] == "succeeded"
    assert loaded["question_pico"]["P"] == ["adults"]


def test_file_store_distinguishes_missing_corrupt_and_invalid_runs(
    tmp_path: Path,
) -> None:
    store = FileWorkflowRunStore(tmp_path / "runs")
    with pytest.raises(WorkflowRunNotFoundError):
        store.load_run(run_id="missing")
    with pytest.raises(ValueError, match="unsupported characters"):
        store.load_run(run_id="../escape")

    run_dir = tmp_path / "runs" / "broken"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(WorkflowRunCorruptError):
        store.load_run(run_id="broken")


def test_file_store_replaces_same_stage_checkpoint_atomically(tmp_path: Path) -> None:
    store = FileWorkflowRunStore(tmp_path / "runs")
    store.create_run(
        run_id="run-3",
        review_id="review-3",
        question_text="question",
        request={},
    )
    for status in ("failed", "succeeded"):
        store.save_stage(
            run_id="run-3",
            sequence=10,
            stage=WorkflowStageRecord(stage_name="q2pico", status=status),
        )

    manifest = json.loads(
        (tmp_path / "runs" / "run-3" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(manifest["stages"]) == 1
    assert store.load_run(run_id="run-3")["stages"][0]["status"] == "succeeded"
