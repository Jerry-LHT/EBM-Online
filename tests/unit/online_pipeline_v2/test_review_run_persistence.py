from __future__ import annotations

from dataclasses import replace

import pytest

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactFile,
    CompletedArtifactRef,
    TaskContext,
    TaskName,
    build_artifact,
)
from ebm_backend.online_pipeline_v2.domain.protocol import TopicKind
from ebm_backend.online_pipeline_v2.domain.review_run import (
    CreateReviewRun,
    ReviewRun,
    ReviewRunStatus,
    ReviewStage,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.review_runs import (
    FileReviewRunStore,
)


def _run(protocol, source) -> ReviewRun:
    context = TaskContext("review-1", protocol.version)
    protocol_artifact = build_artifact(
        context=context,
        task=TaskName.Q2PROTOCOL,
        data=protocol,
        provenance=(source,),
    )
    synthesis_artifact = CompletedArtifactRef(
        artifact_id="synthesis-1",
        schema_version="evidence-synthesis-artifact.v3",
        review_id=context.review_id,
        protocol_version=context.protocol_version,
        task=TaskName.EVIDENCE_SYNTHESIS,
        content_digest="sha256:synthesis",
        files=(ArtifactFile("synthesis.json", "sha256:file", 1),),
        counts={"analyses": 1},
    )
    return ReviewRun(
        run_id="run-1",
        request=CreateReviewRun(
            review_id=context.review_id,
            protocol_version=context.protocol_version,
            topic_text=protocol.review_question,
            topic_kind=TopicKind.QUESTION,
            provenance=(source,),
        ),
        status=ReviewRunStatus.INTERRUPTED,
        stage=ReviewStage.GRADE_SUMMARY_OF_FINDINGS,
        created_at="2026-08-03T00:00:00Z",
        updated_at="2026-08-03T00:00:00Z",
        artifacts={
            "q2protocol": protocol_artifact,
            "evidence_synthesis": synthesis_artifact,
        },
    )


def test_load_hydrates_envelopes_and_completed_references(
    tmp_path, protocol, source
) -> None:
    store = FileReviewRunStore(tmp_path)
    original = _run(protocol, source)
    store.create(original)

    loaded = store.load(original.run_id)

    assert type(loaded.artifacts["q2protocol"]) is type(
        original.artifacts["q2protocol"]
    )
    assert loaded.artifacts["q2protocol"] == original.artifacts["q2protocol"]
    assert isinstance(
        loaded.artifacts["evidence_synthesis"], CompletedArtifactRef
    )
    assert (
        loaded.artifacts["evidence_synthesis"]
        == original.artifacts["evidence_synthesis"]
    )

    store.save(loaded)
    assert store.load(original.run_id) == loaded


def test_load_rejects_unknown_artifact_slot(tmp_path, protocol, source) -> None:
    store = FileReviewRunStore(tmp_path)
    run = _run(protocol, source)
    store.create(run)
    state_path = next(tmp_path.glob("*/state.json"))
    state = state_path.read_text(encoding="utf-8")
    state_path.write_text(
        state.replace('"q2protocol":', '"unknown_task":', 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported Review Run artifact slot"):
        store.load(run.run_id)


def test_load_rejects_artifact_task_mismatch(tmp_path, protocol, source) -> None:
    store = FileReviewRunStore(tmp_path)
    run = _run(protocol, source)
    wrong = replace(
        run.artifacts["evidence_synthesis"],
        task=TaskName.GRADE_SUMMARY_OF_FINDINGS,
    )
    store.create(
        replace(
            run,
            run_id="run-2",
            artifacts={**run.artifacts, "evidence_synthesis": wrong},
        )
    )

    with pytest.raises(ValueError, match="contains task grade_summary_of_findings"):
        store.load("run-2")
