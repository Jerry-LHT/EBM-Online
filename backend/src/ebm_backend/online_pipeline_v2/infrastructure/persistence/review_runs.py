"""Inspectable filesystem persistence for end-to-end Review Runs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from pydantic import TypeAdapter

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactEnvelope,
    CompletedArtifactRef,
    TaskName,
)
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft
from ebm_backend.online_pipeline_v2.domain.review_run import (
    ReviewRun,
    ReviewRunStatus,
)
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import RiskOfBiasArtifact
from ebm_backend.online_pipeline_v2.domain.search import EvidenceSearchArtifact
from ebm_backend.online_pipeline_v2.domain.selection import StudySelectionArtifact
from ebm_backend.online_pipeline_v2.infrastructure.persistence.filesystem import (
    atomic_write_json,
    jsonable,
    opaque_component,
    read_json_object,
    safe_component,
)


_RUN = TypeAdapter(ReviewRun)
_COMPLETED_ARTIFACT = TypeAdapter(CompletedArtifactRef)
_ENVELOPE_ARTIFACTS = {
    "q2protocol": TypeAdapter(ArtifactEnvelope[ProtocolDraft]),
    "evidence_search": TypeAdapter(ArtifactEnvelope[EvidenceSearchArtifact]),
    "study_selection": TypeAdapter(ArtifactEnvelope[StudySelectionArtifact]),
    "risk_of_bias": TypeAdapter(ArtifactEnvelope[RiskOfBiasArtifact]),
}
_COMPLETED_ARTIFACT_TASKS = {
    "study_data_collection": TaskName.STUDY_DATA_COLLECTION,
    "evidence_synthesis": TaskName.EVIDENCE_SYNTHESIS,
    "grade_summary_of_findings": TaskName.GRADE_SUMMARY_OF_FINDINGS,
    "systematic_review": TaskName.SYSTEMATIC_REVIEW_REPORTING,
}
_ENVELOPE_ARTIFACT_TASKS = {
    "q2protocol": TaskName.Q2PROTOCOL,
    "evidence_search": TaskName.EVIDENCE_SEARCH,
    "study_selection": TaskName.STUDY_SELECTION,
    "risk_of_bias": TaskName.RISK_OF_BIAS,
}


class ReviewRunNotFound(LookupError):
    pass


class FileReviewRunStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def create(self, run: ReviewRun) -> None:
        directory = self._directory(run.run_id)
        if directory.exists():
            raise ValueError("Review Run already exists")
        directory.mkdir(parents=True)
        atomic_write_json(directory / "request.json", jsonable(run.request))
        self.save(run)

    def load(self, run_id: str) -> ReviewRun:
        path = self._directory(run_id) / "state.json"
        if not path.is_file():
            raise ReviewRunNotFound(run_id)
        return _review_run_from_record(read_json_object(path))

    def save(self, run: ReviewRun) -> None:
        directory = self._directory(run.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        previous = None
        state_path = directory / "state.json"
        if state_path.exists():
            previous = _review_run_from_record(read_json_object(state_path))
        atomic_write_json(state_path, jsonable(run))
        previous_count = len(previous.events) if previous is not None else 0
        events = directory / "events"
        events.mkdir(exist_ok=True)
        for event in run.events[previous_count:]:
            atomic_write_json(
                events / f"{event.sequence:06d}.json",
                jsonable(event),
            )

    def mark_interrupted(self) -> None:
        if not self.root.exists():
            return
        for path in self.root.glob("*/state.json"):
            run = _review_run_from_record(read_json_object(path))
            if run.status is ReviewRunStatus.RUNNING:
                self.save(
                    run.event(
                        code="service_interrupted",
                        message="The service stopped while this stage was running.",
                        status=ReviewRunStatus.INTERRUPTED,
                    )
                )

    def _directory(self, run_id: str) -> Path:
        safe_component(run_id)
        return self.root / opaque_component(run_id)


def _review_run_from_record(value: object) -> ReviewRun:
    run = _RUN.validate_python(value)
    artifacts: dict[str, object] = {}
    for key, artifact in run.artifacts.items():
        if key in _ENVELOPE_ARTIFACTS:
            parsed = _ENVELOPE_ARTIFACTS[key].validate_python(artifact)
            expected_task = _ENVELOPE_ARTIFACT_TASKS[key]
        elif key in _COMPLETED_ARTIFACT_TASKS:
            parsed = _COMPLETED_ARTIFACT.validate_python(artifact)
            expected_task = _COMPLETED_ARTIFACT_TASKS[key]
        else:
            raise ValueError(f"unsupported Review Run artifact slot: {key}")
        if parsed.task is not expected_task:
            raise ValueError(
                f"Review Run artifact slot {key} contains task {parsed.task.value}"
            )
        artifacts[key] = parsed
    return replace(run, artifacts=artifacts)
