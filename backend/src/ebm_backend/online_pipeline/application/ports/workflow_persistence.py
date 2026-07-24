"""Application ports for durable workflow-run snapshots."""

from __future__ import annotations

from typing import Any, Protocol

from ebm_backend.online_pipeline.domain.workflow import (
    OnlineEBMWorkflowResult,
    WorkflowStageRecord,
)


class WorkflowRunNotFoundError(FileNotFoundError):
    """The requested persisted workflow run does not exist."""


class WorkflowRunCorruptError(ValueError):
    """A persisted workflow run cannot be parsed safely."""


class WorkflowRunStorePort(Protocol):
    """Persist and retrieve one observable workflow execution."""

    def create_run(
        self,
        *,
        run_id: str,
        review_id: str,
        question_text: str,
        request: dict[str, Any],
    ) -> None:
        ...

    def save_stage(
        self,
        *,
        run_id: str,
        sequence: int,
        stage: WorkflowStageRecord,
    ) -> None:
        ...

    def finalize_run(
        self,
        *,
        run_id: str,
        result: OnlineEBMWorkflowResult,
    ) -> None:
        ...

    def load_run(self, *, run_id: str) -> dict[str, Any]:
        ...
