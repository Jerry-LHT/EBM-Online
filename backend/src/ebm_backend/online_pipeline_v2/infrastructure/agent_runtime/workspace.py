"""Per-run isolated workspace materialization and cleanup."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from .contracts import (
    AgentProvider,
    AgentOutputArtifact,
    AgentRunRequest,
    WorkspaceRetention,
)
from .errors import AgentWorkspaceError
from .skill_loader import StagedSkills, stage_skills
from .structured_output import validate_output_schema

_MAX_OUTPUT_ARTIFACT_BYTES = 128 * 1024 * 1024
_MAX_OUTPUT_ARTIFACT_TOTAL_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PreparedWorkspace:
    root: Path
    input_path: Path
    schema_path: Path
    output_path: Path
    artifact_paths: dict[str, Path]
    staged_skills: StagedSkills


@dataclass(slots=True)
class WorkspaceManager:
    base_directory: Path | None = None
    retention: WorkspaceRetention = WorkspaceRetention.NEVER

    def prepare(
        self,
        request: AgentRunRequest,
        *,
        provider: AgentProvider,
    ) -> PreparedWorkspace:
        base = (
            self.base_directory.expanduser().resolve()
            if self.base_directory is not None
            else None
        )
        if base is not None:
            base.mkdir(parents=True, exist_ok=True)
        root = Path(
            tempfile.mkdtemp(
                prefix=f"ebm-agent-{request.run_id}-",
                dir=base,
            )
        ).resolve()
        try:
            input_path = root / "inputs" / "task-input.json"
            schema_path = root / "contracts" / "output.schema.json"
            artifact_contract_path = root / "contracts" / "output-artifacts.json"
            output_path = root / "outputs" / "final.json"
            for path in (
                input_path,
                schema_path,
                artifact_contract_path,
                output_path,
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
            schema = validate_output_schema(request.output_schema)
            input_path.write_text(
                json.dumps(
                    dict(request.input_data),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            artifact_paths: dict[str, Path] = {}
            artifact_root = root / "inputs" / "artifacts"
            for name, source in request.input_artifacts.items():
                target = artifact_root / name
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                artifact_paths[name] = target
            schema_path.write_text(
                json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            artifact_contract_path.write_text(
                json.dumps(
                    dict(request.output_artifacts),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            staged = stage_skills(
                request.skill_paths,
                workspace=root,
                provider=provider,
            )
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return PreparedWorkspace(
            root=root,
            input_path=input_path,
            schema_path=schema_path,
            output_path=output_path,
            artifact_paths=artifact_paths,
            staged_skills=staged,
        )

    def collect_output_artifacts(
        self,
        workspace: PreparedWorkspace,
        request: AgentRunRequest,
    ) -> dict[str, AgentOutputArtifact]:
        collected: dict[str, AgentOutputArtifact] = {}
        total_bytes = 0
        for name, relative in request.output_artifacts.items():
            candidate = workspace.root / relative
            current = workspace.root
            for part in Path(relative).parts:
                current = current / part
                if current.is_symlink():
                    raise AgentWorkspaceError(
                        current,
                        "declared output artifact path must not use symlinks",
                    )
            path = candidate.resolve()
            if not path.is_relative_to(workspace.root):
                raise AgentWorkspaceError(
                    path,
                    "declared output artifact escapes the workspace",
                )
            if not path.exists():
                continue
            if not path.is_file():
                raise AgentWorkspaceError(
                    path,
                    "declared output artifact must be a regular file",
                )
            content = path.read_bytes()
            if len(content) > _MAX_OUTPUT_ARTIFACT_BYTES:
                raise AgentWorkspaceError(
                    path,
                    "declared output artifact exceeds the per-file limit",
                )
            total_bytes += len(content)
            if total_bytes > _MAX_OUTPUT_ARTIFACT_TOTAL_BYTES:
                raise AgentWorkspaceError(
                    path,
                    "declared output artifacts exceed the total size limit",
                )
            collected[name] = AgentOutputArtifact(
                name=name,
                relative_path=relative,
                content=content,
                sha256=f"sha256:{hashlib.sha256(content).hexdigest()}",
            )
        return collected

    def release(
        self,
        workspace: PreparedWorkspace,
        *,
        succeeded: bool,
    ) -> Path | None:
        retain = (
            self.retention is WorkspaceRetention.ALWAYS
            or (
                self.retention is WorkspaceRetention.ON_FAILURE
                and not succeeded
            )
        )
        if retain:
            return workspace.root
        try:
            shutil.rmtree(workspace.root)
        except OSError as exc:
            raise AgentWorkspaceError(
                workspace.root,
                f"cleanup failed: {exc}",
            ) from exc
        return None
