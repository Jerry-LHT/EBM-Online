"""Typed filesystem store for Results work and immutable completed bundles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
from typing import Any, Mapping
from uuid import uuid4

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactFile,
    CompletedArtifactRef,
    TaskName,
)

from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.study_results import (
    ResultCalculator,
    parse_results_document,
    validate_completed_projections,
)
from ..filesystem import (
    atomic_write_bytes as _atomic_bytes,
    atomic_write_json as _atomic_json,
    digest_tag as _digest_bytes,
    read_json_object as _read_json,
    safe_component as _safe_component,
    safe_filename as _safe_filename,
)


class WorkBindingConflict(ValueError):
    """The supplied work_id belongs to different immutable inputs."""


class WorkExecutionConflict(RuntimeError):
    """The supplied work_id already has an active execution."""


@dataclass(frozen=True, slots=True)
class ResultsWorkSession:
    work_id: str
    root: Path
    binding: Mapping[str, Any]
    checkpoint_path: Path | None


@dataclass(frozen=True, slots=True)
class ResultsArtifactSnapshot:
    artifact: CompletedArtifactRef
    ledger_path: Path
    authoritative_path: Path
    public_directory: Path


@dataclass(slots=True)
class FileStudyResultsStore:
    root: Path
    calculate_result: ResultCalculator

    def begin(
        self,
        *,
        binding: Mapping[str, Any],
        work_id: str | None,
    ) -> ResultsWorkSession:
        root = self.root.expanduser().resolve()
        work_root = root / "work"
        work_root.mkdir(parents=True, exist_ok=True)
        resolved_id = work_id or f"results-{uuid4().hex}"
        directory = work_root / _safe_component(resolved_id)
        binding_path = directory / "binding.json"
        if directory.exists():
            if not binding_path.is_file():
                raise WorkExecutionConflict(
                    "work_id is being initialized or has incomplete state"
                )
            stored = _read_json(binding_path)
            if stored != dict(binding):
                raise WorkBindingConflict(
                    "work_id is bound to different review or upstream artifacts"
                )
        else:
            try:
                directory.mkdir()
            except FileExistsError as exc:
                raise WorkExecutionConflict(
                    "work_id is being initialized by another execution"
                ) from exc
            _atomic_json(binding_path, dict(binding))
        lock_path = directory / "active.lock"
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise WorkExecutionConflict(
                "work_id already has an active execution"
            ) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"{os.getpid()}\n")
        checkpoint = directory / "checkpoint.json"
        return ResultsWorkSession(
            work_id=resolved_id,
            root=directory,
            binding=dict(binding),
            checkpoint_path=checkpoint if checkpoint.is_file() else None,
        )

    def checkpoint(self, session: ResultsWorkSession, content: bytes) -> Path:
        destination = session.root / "checkpoint.json"
        _atomic_bytes(destination, content)
        _atomic_json(
            session.root / "state.json",
            {
                "work_id": session.work_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "checkpoint_sha256": _digest_bytes(content),
            },
        )
        return destination

    def complete(
        self,
        session: ResultsWorkSession,
        *,
        authoritative: bytes,
        public_files: Mapping[str, bytes],
        projection_summary: Mapping[str, Any],
        counts: Mapping[str, int],
        warnings: tuple[str, ...],
        supersedes_artifact_id: str | None = None,
    ) -> ResultsArtifactSnapshot:
        authoritative_name = (
            f"{session.binding['review_id']}-study-results.json"
        )
        required_names = {
            authoritative_name,
            f"{session.binding['review_id']}-study-arms.csv",
            f"{session.binding['review_id']}-study-results.csv",
        }
        if set(public_files) != required_names:
            raise ValueError(
                "Results completion requires authoritative JSON and two CSVs"
            )
        if public_files[authoritative_name] != authoritative:
            raise ValueError(
                "Results authoritative public file differs from frozen input"
            )
        root = self.root.expanduser().resolve()
        completed_root = root / "completed"
        completed_root.mkdir(parents=True, exist_ok=True)
        artifact_id = (
            f"{session.binding['review_id']}:study_results:"
            f"{session.binding['protocol_version']}:{uuid4().hex}"
        )
        final_root = completed_root / _safe_component(artifact_id)
        temporary = completed_root / f".{uuid4().hex}.tmp"
        temporary.mkdir()
        try:
            public = temporary / "public"
            public.mkdir()
            files: list[ArtifactFile] = []
            file_manifest: list[dict[str, Any]] = []
            for name, content in sorted(public_files.items()):
                path = public / _safe_filename(name)
                path.write_bytes(content)
                digest = _digest_bytes(content)
                files.append(
                    ArtifactFile(name=name, sha256=digest, size_bytes=len(content))
                )
                file_manifest.append(
                    {"name": name, "sha256": digest, "size_bytes": len(content)}
                )
            manifest = {
                "schema_version": "study-results-artifact.v3",
                "artifact_id": artifact_id,
                "review_id": session.binding["review_id"],
                "protocol_version": session.binding["protocol_version"],
                "task": TaskName.STUDY_DATA_COLLECTION.value,
                "binding": dict(session.binding),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "authoritative_results_sha256": _digest_bytes(authoritative),
                "public_files": file_manifest,
                "projection_summary": dict(projection_summary),
                "counts": dict(counts),
                "warnings": list(warnings),
                "supersedes_artifact_id": supersedes_artifact_id,
            }
            _atomic_json(temporary / "manifest.json", manifest)
            manifest_bytes = (temporary / "manifest.json").read_bytes()
            temporary.replace(final_root)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        artifact = CompletedArtifactRef(
            artifact_id=artifact_id,
            schema_version="study-results-artifact.v3",
            review_id=str(session.binding["review_id"]),
            protocol_version=str(session.binding["protocol_version"]),
            task=TaskName.STUDY_DATA_COLLECTION,
            content_digest=_digest_bytes(manifest_bytes),
            files=tuple(files),
            counts=dict(counts),
            warnings=warnings,
            supersedes_artifact_id=supersedes_artifact_id,
        )
        return ResultsArtifactSnapshot(
            artifact=artifact,
            ledger_path=(
                final_root
                / "public"
                / f"{session.binding['review_id']}-study-results.json"
            ),
            authoritative_path=(
                final_root
                / "public"
                / f"{session.binding['review_id']}-study-results.json"
            ),
            public_directory=final_root / "public",
        )

    def resolve(self, artifact_id: str) -> ResultsArtifactSnapshot:
        root = self.root.expanduser().resolve()
        directory = (root / "completed" / _safe_component(artifact_id)).resolve()
        if not directory.is_relative_to(root) or not directory.is_dir():
            raise ValueError("completed Results artifact does not exist")
        manifest_path = directory / "manifest.json"
        manifest = _read_json(manifest_path)
        if manifest.get("artifact_id") != artifact_id:
            raise ValueError("Results artifact id does not match manifest")
        if manifest.get("schema_version") != "study-results-artifact.v3":
            raise ValueError("Results artifact schema is invalid")
        if manifest.get("task") != TaskName.STUDY_DATA_COLLECTION.value:
            raise ValueError("Results artifact task is invalid")
        binding = manifest.get("binding")
        if not isinstance(binding, dict):
            raise ValueError("Results artifact binding is invalid")
        if manifest.get("review_id") != binding.get("review_id") or manifest.get(
            "protocol_version"
        ) != binding.get("protocol_version"):
            raise ValueError("Results artifact identity is inconsistent")
        public = directory / "public"
        files: list[ArtifactFile] = []
        expected_names: set[str] = set()
        for item in manifest.get("public_files", []):
            if not isinstance(item, dict):
                raise ValueError("Results public file manifest is invalid")
            name = _safe_filename(str(item.get("name", "")))
            expected_names.add(name)
            path = public / name
            content = path.read_bytes()
            if _digest_bytes(content) != item.get("sha256"):
                raise ValueError("Results public file digest mismatch")
            if len(content) != item.get("size_bytes"):
                raise ValueError("Results public file size mismatch")
            files.append(
                ArtifactFile(
                    name=name,
                    sha256=str(item["sha256"]),
                    size_bytes=int(item["size_bytes"]),
                )
            )
        actual_names = {path.name for path in public.iterdir() if path.is_file()}
        if actual_names != expected_names:
            raise ValueError("Results public directory has undeclared files")
        required_names = {
            f"{binding['review_id']}-study-results.json",
            f"{binding['review_id']}-study-arms.csv",
            f"{binding['review_id']}-study-results.csv",
        }
        if expected_names != required_names:
            raise ValueError(
                "Results artifact must declare authoritative JSON and two CSVs"
            )
        authoritative = public / f"{binding['review_id']}-study-results.json"
        authoritative_content = authoritative.read_bytes()
        if _digest_bytes(authoritative_content) != manifest.get(
            "authoritative_results_sha256"
        ):
            raise ValueError("Results authoritative JSON digest mismatch")
        parsed_document = parse_results_document(
            authoritative_content,
            expected_binding=binding,
            require_completed=True,
            calculate=self.calculate_result,
        )
        summary = validate_completed_projections(
            parsed_document,
            authoritative=authoritative_content,
            public_csvs={
                name: (public / name).read_bytes()
                for name in expected_names
                if name.endswith(".csv")
            },
        )
        if summary != manifest.get("projection_summary"):
            raise ValueError("Results projection summary mismatch")
        artifact = CompletedArtifactRef(
            artifact_id=artifact_id,
            schema_version=str(manifest["schema_version"]),
            review_id=str(manifest["review_id"]),
            protocol_version=str(manifest["protocol_version"]),
            task=TaskName.STUDY_DATA_COLLECTION,
            content_digest=_digest_bytes(manifest_path.read_bytes()),
            files=tuple(files),
            counts=dict(manifest.get("counts", {})),
            warnings=tuple(manifest.get("warnings", [])),
            supersedes_artifact_id=manifest.get("supersedes_artifact_id"),
        )
        return ResultsArtifactSnapshot(
            artifact,
            authoritative,
            authoritative,
            public,
        )

    def release(self, session: ResultsWorkSession) -> None:
        (session.root / "active.lock").unlink(missing_ok=True)
