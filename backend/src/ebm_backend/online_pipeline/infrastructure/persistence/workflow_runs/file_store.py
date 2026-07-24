"""Atomic JSON persistence for workflow runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from ebm_backend.online_pipeline.application.ports.workflow_persistence import (
    WorkflowRunCorruptError,
    WorkflowRunNotFoundError,
)
from ebm_backend.online_pipeline.domain.workflow import (
    OnlineEBMWorkflowResult,
    WorkflowStageRecord,
)
from ebm_backend.online_pipeline.infrastructure.persistence.atomic_io import (
    atomic_write_json,
    read_json,
)


SCHEMA_VERSION = 1
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class FileWorkflowRunStore:
    root: Path

    def create_run(
        self,
        *,
        run_id: str,
        review_id: str,
        question_text: str,
        request: dict[str, Any],
    ) -> None:
        now = _utc_now()
        atomic_write_json(
            self._manifest_path(run_id),
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "review_id": review_id,
                "question_text": question_text,
                "status": "running",
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
                "request": request,
                "stages": [],
            },
        )
        atomic_write_json(self._run_dir(run_id) / "input.json", request)

    def save_stage(
        self,
        *,
        run_id: str,
        sequence: int,
        stage: WorkflowStageRecord,
    ) -> None:
        manifest = self._read_manifest(run_id)
        filename = f"{sequence:03d}_{_safe_stage_name(stage.stage_name)}.json"
        atomic_write_json(self._run_dir(run_id) / "stages" / filename, stage)
        stage_refs = [
            item
            for item in manifest.get("stages", [])
            if item.get("stage_name") != stage.stage_name
        ]
        stage_refs.append(
            {
                "sequence": sequence,
                "stage_name": stage.stage_name,
                "status": stage.status,
                "file": f"stages/{filename}",
            }
        )
        stage_refs.sort(key=lambda item: (int(item["sequence"]), item["stage_name"]))
        manifest["stages"] = stage_refs
        manifest["updated_at"] = _utc_now()
        atomic_write_json(self._manifest_path(run_id), manifest)

    def finalize_run(
        self,
        *,
        run_id: str,
        result: OnlineEBMWorkflowResult,
    ) -> None:
        manifest = self._read_manifest(run_id)
        atomic_write_json(self._run_dir(run_id) / "result.json", result)
        now = _utc_now()
        manifest.update(
            {
                "status": result.status,
                "updated_at": now,
                "completed_at": now,
                "persistence_status": result.persistence_status,
            }
        )
        try:
            atomic_write_json(self._manifest_path(run_id), manifest)
        except OSError:
            # result.json is the authoritative completed artifact. A stale
            # manifest must not turn a successfully stored result into a miss.
            pass

    def load_run(self, *, run_id: str) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        result_path = run_dir / "result.json"
        if result_path.exists():
            value = self._read_object(result_path, run_id=run_id)
            if value.get("run_id") != run_id:
                raise WorkflowRunCorruptError(
                    f"Persisted workflow run '{run_id}' has a mismatched run_id"
                )
            return value

        manifest = self._read_manifest(run_id)
        stages = []
        for item in manifest.get("stages", []):
            stage_path = run_dir / str(item["file"])
            stages.append(self._read_object(stage_path, run_id=run_id))
        return _partial_result(manifest=manifest, stages=stages)

    def _read_manifest(self, run_id: str) -> dict[str, Any]:
        path = self._manifest_path(run_id)
        if not path.exists():
            raise WorkflowRunNotFoundError(f"Workflow run '{run_id}' was not found")
        manifest = self._read_object(path, run_id=run_id)
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise WorkflowRunCorruptError(
                f"Workflow run '{run_id}' uses an unsupported schema version"
            )
        if manifest.get("run_id") != run_id:
            raise WorkflowRunCorruptError(
                f"Workflow run '{run_id}' has a mismatched manifest run_id"
            )
        return manifest

    def _read_object(self, path: Path, *, run_id: str) -> dict[str, Any]:
        try:
            value = read_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkflowRunCorruptError(
                f"Workflow run '{run_id}' contains an unreadable JSON artifact"
            ) from exc
        if not isinstance(value, dict):
            raise WorkflowRunCorruptError(
                f"Workflow run '{run_id}' contains a non-object JSON artifact"
            )
        return value

    def _manifest_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "manifest.json"

    def _run_dir(self, run_id: str) -> Path:
        if not _SAFE_RUN_ID.fullmatch(run_id):
            raise ValueError("run_id contains unsupported characters")
        return self.root / run_id


def _partial_result(
    *,
    manifest: dict[str, Any],
    stages: list[dict[str, Any]],
) -> dict[str, Any]:
    successful = {
        stage["stage_name"]: stage.get("output")
        for stage in stages
        if stage.get("status") == "succeeded"
    }
    grade_stage = next(
        (stage for stage in stages if stage.get("stage_name") == "grade"),
        None,
    )
    grade_status = "not_run"
    if grade_stage is not None:
        grade_status = str(grade_stage.get("status") or "not_run")
    return {
        "review_id": manifest.get("review_id", ""),
        "question_text": manifest.get("question_text", ""),
        "status": manifest.get("status", "running"),
        "run_id": manifest.get("run_id", ""),
        "persistence_status": "partial",
        "persistence_error_code": None,
        "stages": stages,
        "question_pico": successful.get("q2pico"),
        "search_retrieval": successful.get("search_retrieval"),
        "study_screening": successful.get("study_screening"),
        "study_pio": successful.get("study_pio") or [],
        "risk_of_bias": successful.get("risk_of_bias") or [],
        "meta_analysis": successful.get("meta_analysis"),
        "grade": successful.get("grade"),
        "grade_status": grade_status,
    }


def _safe_stage_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return normalized or "stage"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
