"""Filesystem stores for immutable GRADE inputs and completed outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any, Mapping
from uuid import uuid4

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactFile,
    CompletedArtifactRef,
    TaskName,
)
from ebm_backend.online_pipeline_v2.domain.grade import GradeEvidencePackageRef
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.grade import (
    serialize_grade_artifact,
    validate_grade_artifact,
)
from ebm_backend.online_pipeline_v2.domain.grade import (
    GradeSummaryOfFindingsArtifact,
)
from ..filesystem import (
    atomic_write_json as _atomic_json,
    digest_tag as _digest,
    read_json_object as _read_json,
    safe_component as _safe_component,
    safe_relative as _safe_relative,
)


REQUIRED_EVIDENCE_FILES = frozenset(
    {
        "protocol.json",
        "search.json",
        "selection.json",
        "study-characteristics.jsonl",
        "risk-of-bias.json",
        "synthesis.json",
    }
)
OPTIONAL_EVIDENCE_FILES = frozenset(
    {
        "meta-analysis/data-rows.csv",
        "meta-analysis/subgroup-estimates.csv",
        "meta-analysis/overall-estimates-and-settings.csv",
    }
)


@dataclass(frozen=True, slots=True)
class GradeEvidenceSnapshot:
    package: GradeEvidencePackageRef
    directory: Path


@dataclass(frozen=True, slots=True)
class GradeArtifactSnapshot:
    artifact: CompletedArtifactRef
    public_directory: Path


@dataclass(slots=True)
class FileGradeEvidencePackageStore:
    root: Path

    def persist(
        self,
        *,
        package_id: str,
        review_id: str,
        protocol_version: str,
        files: Mapping[str, bytes],
    ) -> GradeEvidenceSnapshot:
        if not (
            REQUIRED_EVIDENCE_FILES <= set(files)
            and set(files) <= REQUIRED_EVIDENCE_FILES | OPTIONAL_EVIDENCE_FILES
        ):
            raise ValueError("GRADE evidence package file set is incomplete or unknown")
        base = self.root.expanduser().resolve()
        destination = base / "packages" / _safe_component(package_id)
        if destination.exists():
            existing = self.resolve(package_id)
            expected = {
                name: (_digest(content), len(content))
                for name, content in files.items()
            }
            observed = {
                item.name: (item.sha256, item.size_bytes)
                for item in existing.package.files
            }
            if (
                existing.package.review_id != review_id
                or existing.package.protocol_version != protocol_version
                or observed != expected
            ):
                raise ValueError(
                    "GRADE evidence package id already names different content"
                )
            return existing
        temporary = base / "packages" / f".{uuid4().hex}.tmp"
        temporary.mkdir(parents=True)
        descriptors: list[ArtifactFile] = []
        try:
            for name, content in sorted(files.items()):
                path = _safe_relative(temporary, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                descriptors.append(
                    ArtifactFile(
                        name=name, sha256=_digest(content), size_bytes=len(content)
                    )
                )
            manifest = {
                "schema_version": "grade-evidence-package.v2",
                "package_id": package_id,
                "review_id": review_id,
                "protocol_version": protocol_version,
                "files": [
                    {
                        "name": item.name,
                        "sha256": item.sha256,
                        "size_bytes": item.size_bytes,
                    }
                    for item in descriptors
                ],
            }
            _atomic_json(temporary / "manifest.json", manifest)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return self.resolve(package_id)

    def resolve(self, package_id: str) -> GradeEvidenceSnapshot:
        base = self.root.expanduser().resolve()
        directory = (base / "packages" / _safe_component(package_id)).resolve()
        if not directory.is_relative_to(base) or not directory.is_dir():
            raise ValueError("GRADE evidence package does not exist")
        manifest_path = directory / "manifest.json"
        manifest = _read_json(manifest_path)
        if manifest.get("schema_version") != "grade-evidence-package.v2":
            raise ValueError("GRADE evidence package schema is invalid")
        if manifest.get("package_id") != package_id:
            raise ValueError("GRADE evidence package id does not match")
        files: list[ArtifactFile] = []
        names: set[str] = set()
        for item in manifest.get("files", []):
            if not isinstance(item, dict):
                raise ValueError("GRADE evidence file manifest is invalid")
            name = str(item.get("name", ""))
            path = _safe_relative(directory, name)
            content = path.read_bytes()
            if _digest(content) != item.get("sha256") or len(content) != item.get(
                "size_bytes"
            ):
                raise ValueError("GRADE evidence package integrity check failed")
            names.add(name)
            files.append(
                ArtifactFile(
                    name=name, sha256=str(item["sha256"]), size_bytes=len(content)
                )
            )
        if not (
            REQUIRED_EVIDENCE_FILES <= names
            and names <= REQUIRED_EVIDENCE_FILES | OPTIONAL_EVIDENCE_FILES
        ):
            raise ValueError("GRADE evidence package file set is invalid")
        actual_names = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        if not (
            REQUIRED_EVIDENCE_FILES <= actual_names
            and actual_names <= REQUIRED_EVIDENCE_FILES | OPTIONAL_EVIDENCE_FILES
        ):
            raise ValueError("GRADE evidence package contains undeclared files")
        package = GradeEvidencePackageRef(
            package_id=package_id,
            schema_version="grade-evidence-package.v2",
            review_id=str(manifest["review_id"]),
            protocol_version=str(manifest["protocol_version"]),
            content_digest=_digest(manifest_path.read_bytes()),
            files=tuple(files),
        )
        return GradeEvidenceSnapshot(package, directory)


@dataclass(slots=True)
class FileGradeArtifactStore:
    root: Path

    def persist(
        self,
        *,
        binding: Mapping[str, Any],
        artifact: GradeSummaryOfFindingsArtifact,
        warnings: tuple[str, ...],
    ) -> CompletedArtifactRef:
        profiles, sof = serialize_grade_artifact(artifact)
        counts = validate_grade_artifact(profiles, sof)
        artifact_id = (
            f"{binding['review_id']}:grade_summary_of_findings:"
            f"{binding['protocol_version']}:{uuid4().hex}"
        )
        base = self.root.expanduser().resolve()
        temporary = base / "completed" / f".{uuid4().hex}.tmp"
        destination = base / "completed" / _safe_component(artifact_id)
        temporary.mkdir(parents=True)
        public = temporary / "public"
        public.mkdir()
        contents = {
            "evidence-profiles.jsonl": profiles,
            "summary-of-findings.json": sof,
        }
        descriptors: list[ArtifactFile] = []
        for name, content in contents.items():
            (public / name).write_bytes(content)
            descriptors.append(
                ArtifactFile(
                    name=name, sha256=_digest(content), size_bytes=len(content)
                )
            )
        manifest = {
            "schema_version": "grade-sof-artifact.v4",
            "artifact_id": artifact_id,
            "task": TaskName.GRADE_SUMMARY_OF_FINDINGS.value,
            "binding": dict(binding),
            "files": [
                {
                    "name": item.name,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in descriptors
            ],
            "counts": dict(counts),
            "warnings": list(warnings),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_json(temporary / "manifest.json", manifest)
        temporary.replace(destination)
        return CompletedArtifactRef(
            artifact_id=artifact_id,
            schema_version="grade-sof-artifact.v4",
            review_id=str(binding["review_id"]),
            protocol_version=str(binding["protocol_version"]),
            task=TaskName.GRADE_SUMMARY_OF_FINDINGS,
            content_digest=_digest((destination / "manifest.json").read_bytes()),
            files=tuple(descriptors),
            counts=counts,
            warnings=warnings,
        )

    def resolve(self, artifact_id: str) -> GradeArtifactSnapshot:
        base = self.root.expanduser().resolve()
        directory = (base / "completed" / _safe_component(artifact_id)).resolve()
        if not directory.is_relative_to(base) or not directory.is_dir():
            raise ValueError("completed GRADE artifact does not exist")
        manifest_path = directory / "manifest.json"
        manifest = _read_json(manifest_path)
        binding = manifest.get("binding")
        if (
            manifest.get("schema_version") != "grade-sof-artifact.v4"
            or manifest.get("artifact_id") != artifact_id
            or manifest.get("task") != TaskName.GRADE_SUMMARY_OF_FINDINGS.value
            or not isinstance(binding, dict)
        ):
            raise ValueError("GRADE artifact manifest is invalid")
        public = directory / "public"
        files: list[ArtifactFile] = []
        contents: dict[str, bytes] = {}
        for item in manifest.get("files", []):
            if not isinstance(item, dict):
                raise ValueError("GRADE artifact file manifest is invalid")
            name = str(item.get("name", ""))
            if name not in {"evidence-profiles.jsonl", "summary-of-findings.json"}:
                raise ValueError("GRADE artifact contains an unknown public file")
            content = (public / name).read_bytes()
            if _digest(content) != item.get("sha256") or len(content) != item.get(
                "size_bytes"
            ):
                raise ValueError("GRADE artifact integrity check failed")
            contents[name] = content
            files.append(
                ArtifactFile(
                    name=name, sha256=str(item["sha256"]), size_bytes=len(content)
                )
            )
        if set(contents) != {"evidence-profiles.jsonl", "summary-of-findings.json"}:
            raise ValueError("GRADE artifact is missing a required file")
        actual_names = {path.name for path in public.iterdir() if path.is_file()}
        if actual_names != set(contents):
            raise ValueError("GRADE artifact contains undeclared public files")
        counts = validate_grade_artifact(
            contents["evidence-profiles.jsonl"],
            contents["summary-of-findings.json"],
        )
        if counts != manifest.get("counts"):
            raise ValueError("GRADE artifact counts do not match content")
        artifact = CompletedArtifactRef(
            artifact_id=artifact_id,
            schema_version="grade-sof-artifact.v4",
            review_id=str(binding["review_id"]),
            protocol_version=str(binding["protocol_version"]),
            task=TaskName.GRADE_SUMMARY_OF_FINDINGS,
            content_digest=_digest(manifest_path.read_bytes()),
            files=tuple(files),
            counts=counts,
            warnings=tuple(manifest.get("warnings", [])),
        )
        return GradeArtifactSnapshot(artifact, public)
