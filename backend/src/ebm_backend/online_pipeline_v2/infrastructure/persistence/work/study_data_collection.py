"""Work store for one-shot authoritative Study Data Collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
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
from ebm_backend.online_pipeline_v2.infrastructure.persistence.filesystem import (
    atomic_write_json,
    digest_tag,
    opaque_component,
    read_json_object,
    safe_filename,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.study_data_collection import (
    DataCalculator,
    parse_study_data_collection_document,
    validate_completed_projections,
)


class WorkBindingConflict(ValueError):
    pass


class WorkExecutionConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StudyDataCollectionWorkSession:
    work_id: str
    root: Path
    binding: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class StudyDataCollectionSnapshot:
    artifact: CompletedArtifactRef
    document_path: Path
    ledger_path: Path
    public_directory: Path
    document: dict[str, Any]


@dataclass(slots=True)
class FileStudyDataCollectionStore:
    root: Path
    calculate: DataCalculator

    def begin(
        self,
        *,
        binding: Mapping[str, Any],
    ) -> StudyDataCollectionWorkSession:
        root = self.root.expanduser().resolve()
        work_root = root / "work"
        work_root.mkdir(parents=True, exist_ok=True)
        resolved_id = f"study-data-{uuid4().hex}"
        directory = work_root / opaque_component(resolved_id)
        binding_path = directory / "binding.json"
        if directory.exists():
            if not binding_path.is_file():
                raise WorkExecutionConflict("work_id has incomplete initialization")
            if read_json_object(binding_path) != dict(binding):
                raise WorkBindingConflict("work_id belongs to different inputs")
        else:
            directory.mkdir()
            atomic_write_json(binding_path, dict(binding))
        lock_path = directory / "active.lock"
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise WorkExecutionConflict("work_id already has an active execution") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"{os.getpid()}\n")
        return StudyDataCollectionWorkSession(
            work_id=resolved_id,
            root=directory,
            binding=dict(binding),
        )

    def complete(
        self,
        session: StudyDataCollectionWorkSession,
        *,
        authoritative: bytes,
        public_files: Mapping[str, bytes],
        projection_summary: Mapping[str, Any],
        counts: Mapping[str, int],
        warnings: tuple[str, ...],
    ) -> StudyDataCollectionSnapshot:
        document = parse_study_data_collection_document(
            authoritative,
            expected_binding=session.binding,
            require_completed=True,
            calculate=self.calculate,
        )
        validate_completed_projections(
            document,
            authoritative=authoritative,
            public_files={
                name: content
                for name, content in public_files.items()
                if name != f"{session.binding['review_id']}-study-data-collection.json"
            },
        )
        review_id = str(session.binding["review_id"])
        required = {
            f"{review_id}-study-data-collection.json",
            f"{review_id}-study-characteristics.jsonl",
            f"{review_id}-study-arms.csv",
            f"{review_id}-study-results.csv",
        }
        if set(public_files) != required:
            raise ValueError("Study Data Collection public file set is invalid")
        root = self.root.expanduser().resolve()
        completed = root / "completed"
        completed.mkdir(parents=True, exist_ok=True)
        artifact_id = (
            f"{review_id}:study-data-collection:"
            f"{uuid4().hex}"
        )
        final_root = completed / opaque_component(artifact_id)
        temporary = completed / f".{uuid4().hex}.tmp"
        public = temporary / "public"
        public.mkdir(parents=True)
        files: list[ArtifactFile] = []
        try:
            for name, content in sorted(public_files.items()):
                destination = public / safe_filename(name)
                destination.write_bytes(content)
                files.append(
                    ArtifactFile(
                        name=name,
                        sha256=digest_tag(content),
                        size_bytes=len(content),
                    )
                )
            manifest = {
                "schema_version": "study-data-collection-artifact.v3",
                "artifact_id": artifact_id,
                "review_id": review_id,
                "protocol_version": session.binding["protocol_version"],
                "task": TaskName.STUDY_DATA_COLLECTION.value,
                "binding": dict(session.binding),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "public_files": [
                    {
                        "name": item.name,
                        "sha256": item.sha256,
                        "size_bytes": item.size_bytes,
                    }
                    for item in files
                ],
                "projection_summary": dict(projection_summary),
                "counts": dict(counts),
                "warnings": list(warnings),
            }
            atomic_write_json(temporary / "manifest.json", manifest)
            manifest_bytes = (temporary / "manifest.json").read_bytes()
            temporary.replace(final_root)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        artifact = CompletedArtifactRef(
            artifact_id=artifact_id,
            schema_version="study-data-collection-artifact.v3",
            review_id=review_id,
            protocol_version=str(session.binding["protocol_version"]),
            task=TaskName.STUDY_DATA_COLLECTION,
            content_digest=digest_tag(manifest_bytes),
            files=tuple(files),
            counts=dict(counts),
            warnings=warnings,
        )
        return StudyDataCollectionSnapshot(
            artifact=artifact,
            document_path=final_root / "public" / f"{review_id}-study-data-collection.json",
            ledger_path=final_root / "public" / f"{review_id}-study-data-collection.json",
            public_directory=final_root / "public",
            document=document,
        )

    def resolve(
        self,
        artifact: CompletedArtifactRef | str,
    ) -> StudyDataCollectionSnapshot:
        artifact_id = artifact.artifact_id if isinstance(artifact, CompletedArtifactRef) else artifact
        directory = self.root.expanduser().resolve() / "completed" / opaque_component(artifact_id)
        manifest = read_json_object(directory / "manifest.json")
        if manifest.get("artifact_id") != artifact_id:
            raise ValueError("Study Data Collection artifact id does not match")
        if manifest.get("schema_version") != "study-data-collection-artifact.v3":
            raise ValueError("Study Data Collection artifact schema is invalid")
        public = directory / "public"
        review_id = str(manifest["review_id"])
        document_path = public / f"{review_id}-study-data-collection.json"
        listed_files = manifest.get("public_files")
        if not isinstance(listed_files, list):
            raise ValueError("Study Data Collection public files are invalid")
        public_contents: dict[str, bytes] = {}
        for item in listed_files:
            if not isinstance(item, dict):
                raise ValueError("Study Data Collection public file entry is invalid")
            name = safe_filename(str(item.get("name", "")))
            content = (public / name).read_bytes()
            if len(content) != item.get("size_bytes"):
                raise ValueError("Study Data Collection public file size does not match")
            if digest_tag(content) != item.get("sha256"):
                raise ValueError("Study Data Collection public file digest does not match")
            public_contents[name] = content
        document = parse_study_data_collection_document(
            public_contents[document_path.name],
            expected_binding=manifest["binding"],
            require_completed=True,
            calculate=self.calculate,
        )
        validate_completed_projections(
            document,
            authoritative=public_contents[document_path.name],
            public_files={
                name: content
                for name, content in public_contents.items()
                if name != document_path.name
            },
        )
        files = tuple(
            ArtifactFile(
                name=item["name"],
                sha256=item["sha256"],
                size_bytes=item["size_bytes"],
            )
            for item in listed_files
        )
        resolved = CompletedArtifactRef(
            artifact_id=artifact_id,
            schema_version=manifest["schema_version"],
            review_id=review_id,
            protocol_version=str(manifest["protocol_version"]),
            task=TaskName.STUDY_DATA_COLLECTION,
            content_digest=digest_tag((directory / "manifest.json").read_bytes()),
            files=files,
            counts=dict(manifest["counts"]),
            warnings=tuple(manifest["warnings"]),
        )
        if isinstance(artifact, CompletedArtifactRef) and resolved.content_digest != artifact.content_digest:
            raise ValueError("Study Data Collection artifact digest does not match")
        return StudyDataCollectionSnapshot(
            artifact=resolved,
            document_path=document_path,
            ledger_path=document_path,
            public_directory=public,
            document=document,
        )

    def release(self, session: StudyDataCollectionWorkSession) -> None:
        (session.root / "active.lock").unlink(missing_ok=True)
