"""Read one persisted Online EBM workflow run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ebm_backend.online_pipeline.application.ports.workflow_persistence import (
    WorkflowRunStorePort,
)


@dataclass(frozen=True)
class GetWorkflowRun:
    run_store: WorkflowRunStorePort

    def execute(self, *, run_id: str) -> dict[str, Any]:
        normalized = run_id.strip()
        if not normalized:
            raise ValueError("run_id must not be empty")
        return self.run_store.load_run(run_id=normalized)
