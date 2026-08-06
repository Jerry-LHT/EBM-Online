"""Immutable evidence and completed-artifact stores for Systematic Review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Mapping
from uuid import uuid4

from pydantic import TypeAdapter

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactFile,
    CompletedArtifactRef,
    TaskName,
)
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    ReviewPath,
    SystematicReviewDraft,
    SystematicReviewEvidencePackageRef,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.filesystem import (
    atomic_write_json,
    digest_tag,
    read_json_object,
    safe_component,
    safe_relative,
)


_DRAFT = TypeAdapter(SystematicReviewDraft)
COMMON_FILES = frozenset(
    {
        "review-context/protocol.json",
        "review-context/search.json",
        "review-context/selection.json",
        "review-context/artifact-index.json",
        "review-context/reporting-index.json",
    }
)
EVIDENCE_REVIEW_FILES = frozenset(
    {
        "study-data/study-data-collection.json",
        "study-data/risk-of-bias.json",
        "analysis-data/synthesis.json",
        "certainty/evidence-profiles.jsonl",
        "certainty/summary-of-findings.json",
    }
)
EMPTY_REVIEW_FILES = frozenset({"review-context/empty-review.json"})
OPTIONAL_FILES = frozenset(
    {
        "study-data/study-characteristics.jsonl",
        "study-data/study-arms.csv",
        "study-data/study-results.csv",
        "analysis-data/data-rows.csv",
        "analysis-data/subgroup-estimates.csv",
        "analysis-data/overall-estimates-and-settings.csv",
    }
)


def _allowed_files(review_path: ReviewPath) -> tuple[frozenset[str], frozenset[str]]:
    if review_path is ReviewPath.EMPTY_REVIEW:
        return COMMON_FILES | EMPTY_REVIEW_FILES, frozenset()
    return COMMON_FILES | EVIDENCE_REVIEW_FILES, OPTIONAL_FILES


@dataclass(frozen=True, slots=True)
class SystematicReviewEvidenceSnapshot:
    package: SystematicReviewEvidencePackageRef
    directory: Path


@dataclass(frozen=True, slots=True)
class SystematicReviewArtifactSnapshot:
    artifact: CompletedArtifactRef
    public_directory: Path


@dataclass(slots=True)
class FileSystematicReviewEvidencePackageStore:
    root: Path

    def persist(
        self,
        *,
        package_id: str,
        review_id: str,
        protocol_version: str,
        review_path: ReviewPath,
        files: Mapping[str, bytes],
    ) -> SystematicReviewEvidenceSnapshot:
        required, optional = _allowed_files(review_path)
        if not (required <= set(files) and set(files) <= required | optional):
            raise ValueError("Systematic Review evidence package file set is invalid")
        base = self.root.expanduser().resolve()
        destination = base / "packages" / safe_component(package_id)
        if destination.exists():
            existing = self.resolve(package_id)
            expected = {
                name: (digest_tag(content), len(content))
                for name, content in files.items()
            }
            observed = {
                item.name: (item.sha256, item.size_bytes)
                for item in existing.package.files
            }
            if (
                existing.package.review_id != review_id
                or existing.package.protocol_version != protocol_version
                or existing.package.review_path is not review_path
                or observed != expected
            ):
                raise ValueError("Systematic Review package id names different content")
            return existing
        temporary = base / "packages" / f".{uuid4().hex}.tmp"
        temporary.mkdir(parents=True)
        descriptors: list[ArtifactFile] = []
        try:
            for name, content in sorted(files.items()):
                path = safe_relative(temporary, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                descriptors.append(ArtifactFile(name, digest_tag(content), len(content)))
            atomic_write_json(
                temporary / "manifest.json",
                {
                    "schema_version": "systematic-review-evidence-package.v2",
                    "package_id": package_id,
                    "review_id": review_id,
                    "protocol_version": protocol_version,
                    "review_path": review_path.value,
                    "files": [
                        {
                            "name": item.name,
                            "sha256": item.sha256,
                            "size_bytes": item.size_bytes,
                        }
                        for item in descriptors
                    ],
                },
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return self.resolve(package_id)

    def resolve(self, package_id: str) -> SystematicReviewEvidenceSnapshot:
        base = self.root.expanduser().resolve()
        directory = (base / "packages" / safe_component(package_id)).resolve()
        if not directory.is_relative_to(base) or not directory.is_dir():
            raise ValueError("Systematic Review evidence package does not exist")
        manifest_path = directory / "manifest.json"
        manifest = read_json_object(manifest_path)
        if manifest.get("schema_version") != "systematic-review-evidence-package.v2":
            raise ValueError("Systematic Review evidence package schema is invalid")
        if manifest.get("package_id") != package_id:
            raise ValueError("Systematic Review evidence package id does not match")
        review_path = ReviewPath(str(manifest["review_path"]))
        files: list[ArtifactFile] = []
        names: set[str] = set()
        for item in manifest.get("files", []):
            if not isinstance(item, dict):
                raise ValueError("Systematic Review evidence manifest is invalid")
            name = str(item.get("name", ""))
            content = safe_relative(directory, name).read_bytes()
            if digest_tag(content) != item.get("sha256") or len(content) != item.get(
                "size_bytes"
            ):
                raise ValueError("Systematic Review evidence integrity check failed")
            names.add(name)
            files.append(ArtifactFile(name, str(item["sha256"]), len(content)))
        if len(names) != len(files):
            raise ValueError("Systematic Review evidence files must be unique")
        required, optional = _allowed_files(review_path)
        if not (required <= names and names <= required | optional):
            raise ValueError("Systematic Review evidence files are invalid")
        actual = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        if actual != names:
            raise ValueError("Systematic Review package contains undeclared files")
        package = SystematicReviewEvidencePackageRef(
            package_id=package_id,
            schema_version="systematic-review-evidence-package.v2",
            review_id=str(manifest["review_id"]),
            protocol_version=str(manifest["protocol_version"]),
            review_path=review_path,
            content_digest=digest_tag(manifest_path.read_bytes()),
            files=tuple(files),
        )
        return SystematicReviewEvidenceSnapshot(package, directory)


@dataclass(slots=True)
class FileSystematicReviewArtifactStore:
    root: Path

    def persist(
        self,
        *,
        binding: Mapping[str, str],
        draft: SystematicReviewDraft,
        evidence: SystematicReviewEvidenceSnapshot,
        warnings: tuple[str, ...],
    ) -> CompletedArtifactRef:
        expected_binding = {
            "review_id": evidence.package.review_id,
            "protocol_version": evidence.package.protocol_version,
            "evidence_package_id": evidence.package.package_id,
            "evidence_package_digest": evidence.package.content_digest,
        }
        if any(binding.get(key) != value for key, value in expected_binding.items()):
            raise ValueError("Review artifact binding does not match evidence package")
        if draft.review_path is not evidence.package.review_path:
            raise ValueError("Review draft path does not match evidence package")
        index = json.loads(
            (evidence.directory / "review-context/artifact-index.json").read_text(
                encoding="utf-8"
            )
        )
        known_ids = {str(item["artifact_id"]) for item in index["artifacts"]}
        referenced = {
            artifact_id
            for section in draft.sections
            for artifact_id in section.source_artifact_ids
        }
        if not referenced <= known_ids:
            raise ValueError("Review section references an unknown upstream artifact")
        evidence_files = {item.name for item in evidence.package.files}
        unknown_display_files = {
            item.source_file for item in draft.displays if item.source_file not in evidence_files
        }
        if unknown_display_files:
            raise ValueError("Review display references an unknown evidence file")
        review_bytes = _DRAFT.dump_json(draft) + b"\n"
        artifact_id = (
            f"{binding['review_id']}:systematic_review:"
            f"{binding['protocol_version']}:{uuid4().hex}"
        )
        base = self.root.expanduser().resolve()
        temporary = base / "completed" / f".{uuid4().hex}.tmp"
        destination = base / "completed" / safe_component(artifact_id)
        public = temporary / "public"
        data_root = public / "review-data"
        data_root.mkdir(parents=True)
        (public / "systematic-review.json").write_bytes(review_bytes)
        copied: list[ArtifactFile] = []
        for item in evidence.package.files:
            source = safe_relative(evidence.directory, item.name)
            target = safe_relative(data_root, item.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append(
                ArtifactFile(
                    name=f"review-data/{item.name}",
                    sha256=item.sha256,
                    size_bytes=item.size_bytes,
                )
            )
        data_manifest = {
            "schema_version": "review-data-package.v4",
            "review_id": binding["review_id"],
            "protocol_version": binding["protocol_version"],
            "source_package_id": evidence.package.package_id,
            "source_package_digest": evidence.package.content_digest,
            "files": [item.name.removeprefix("review-data/") for item in copied],
        }
        atomic_write_json(data_root / "manifest.json", data_manifest)
        descriptors = [
            ArtifactFile(
                "systematic-review.json",
                digest_tag(review_bytes),
                len(review_bytes),
            ),
            ArtifactFile(
                "review-data/manifest.json",
                digest_tag((data_root / "manifest.json").read_bytes()),
                (data_root / "manifest.json").stat().st_size,
            ),
            *copied,
        ]
        counts = {
            "review_sections": len(draft.sections),
            "reporting_method_decisions": len(draft.method_decisions),
            "review_displays": len(draft.displays),
            "review_data_files": len(copied),
        }
        manifest = {
            "schema_version": "systematic-review-artifact.v5",
            "artifact_id": artifact_id,
            "task": TaskName.SYSTEMATIC_REVIEW_REPORTING.value,
            "binding": dict(binding),
            "files": [
                {
                    "name": item.name,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in descriptors
            ],
            "counts": counts,
            "warnings": list(warnings),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write_json(temporary / "manifest.json", manifest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(destination)
        return CompletedArtifactRef(
            artifact_id=artifact_id,
            schema_version="systematic-review-artifact.v5",
            review_id=binding["review_id"],
            protocol_version=binding["protocol_version"],
            task=TaskName.SYSTEMATIC_REVIEW_REPORTING,
            content_digest=digest_tag((destination / "manifest.json").read_bytes()),
            files=tuple(descriptors),
            counts=counts,
            warnings=warnings,
        )

    def resolve(self, artifact_id: str) -> SystematicReviewArtifactSnapshot:
        base = self.root.expanduser().resolve()
        directory = (base / "completed" / safe_component(artifact_id)).resolve()
        if not directory.is_relative_to(base) or not directory.is_dir():
            raise ValueError("Systematic Review artifact does not exist")
        manifest = read_json_object(directory / "manifest.json")
        if manifest.get("schema_version") != "systematic-review-artifact.v5":
            raise ValueError("Systematic Review artifact schema is invalid")
        if manifest.get("artifact_id") != artifact_id:
            raise ValueError("Systematic Review artifact id does not match")
        if manifest.get("task") != TaskName.SYSTEMATIC_REVIEW_REPORTING.value:
            raise ValueError("Systematic Review artifact task does not match")
        binding = manifest["binding"]
        files: list[ArtifactFile] = []
        names: set[str] = set()
        for item in manifest["files"]:
            name = str(item["name"])
            content = safe_relative(directory / "public", name).read_bytes()
            if digest_tag(content) != item["sha256"] or len(content) != item["size_bytes"]:
                raise ValueError("Systematic Review artifact integrity check failed")
            names.add(name)
            files.append(ArtifactFile(name, str(item["sha256"]), len(content)))
        if len(names) != len(files):
            raise ValueError("Systematic Review artifact files must be unique")
        actual = {
            path.relative_to(directory / "public").as_posix()
            for path in (directory / "public").rglob("*")
            if path.is_file()
        }
        if actual != names:
            raise ValueError("Systematic Review artifact contains undeclared files")
        draft = _DRAFT.validate_json(
            (directory / "public/systematic-review.json").read_bytes()
        )
        data_manifest = read_json_object(directory / "public/review-data/manifest.json")
        if (
            data_manifest.get("schema_version") != "review-data-package.v4"
            or data_manifest.get("review_id") != binding["review_id"]
            or data_manifest.get("protocol_version") != binding["protocol_version"]
            or data_manifest.get("source_package_id")
            != binding["evidence_package_id"]
            or data_manifest.get("source_package_digest")
            != binding["evidence_package_digest"]
        ):
            raise ValueError("Review Data Package binding does not match")
        declared_data = {str(item) for item in data_manifest.get("files", [])}
        actual_data = {
            name.removeprefix("review-data/")
            for name in names
            if name.startswith("review-data/")
            and name != "review-data/manifest.json"
        }
        if declared_data != actual_data:
            raise ValueError("Review Data Package file declaration does not match")
        artifact = CompletedArtifactRef(
            artifact_id=artifact_id,
            schema_version="systematic-review-artifact.v5",
            review_id=str(binding["review_id"]),
            protocol_version=str(binding["protocol_version"]),
            task=TaskName.SYSTEMATIC_REVIEW_REPORTING,
            content_digest=digest_tag((directory / "manifest.json").read_bytes()),
            files=tuple(files),
            counts={str(k): int(v) for k, v in manifest["counts"].items()},
            warnings=tuple(str(item) for item in manifest.get("warnings", [])),
        )
        return SystematicReviewArtifactSnapshot(artifact, directory / "public")
