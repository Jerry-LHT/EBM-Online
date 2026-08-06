"""Filesystem persistence for immutable Study Characteristics Packages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from ebm_backend.online_pipeline_v2.application.ports.repositories import (
    CharacteristicsReviewSnapshot,
)
from ebm_backend.online_pipeline_v2.domain.common import ArtifactIssue
from ebm_backend.online_pipeline_v2.domain.selection import Report
from ebm_backend.online_pipeline_v2.domain.study_characteristics import (
    CharacteristicsReportEvidenceObservation,
    DiscoveredReportLink,
    StudyCharacteristicsMethodologyAuthority,
    StudyCharacteristicsPackageRef,
    StudyCharacteristicsRecord,
)
from ..filesystem import (
    atomic_write_text,
    jsonable,
    opaque_component,
    safe_component,
    sha256_file,
    validated_member,
    write_jsonl,
)


_COLLECTION_PATHS = {
    "studies": "study-characteristics.jsonl",
    "discovered_reports": "discovered-reports.jsonl",
    "discovered_report_links": "discovered-report-links.jsonl",
    "report_evidence": "report-evidence.jsonl",
    "issues": "issues.jsonl",
}


@dataclass(slots=True)
class FileStudyCharacteristicsPackageStore:
    root: Path

    def persist(
        self,
        *,
        review_id: str,
        protocol_version: str,
        studies: Sequence[StudyCharacteristicsRecord],
        discovered_reports: Sequence[Report],
        discovered_report_links: Sequence[DiscoveredReportLink],
        report_evidence: Sequence[CharacteristicsReportEvidenceObservation],
        issues: Sequence[ArtifactIssue],
        review_runs: Sequence[CharacteristicsReviewSnapshot],
        methodology_authorities: Sequence[StudyCharacteristicsMethodologyAuthority],
    ) -> StudyCharacteristicsPackageRef:
        package_id = (
            f"{review_id}:study_characteristics:{protocol_version}:{uuid4().hex}"
        )
        package_root = (
            self.root.expanduser().resolve()
            / safe_component(review_id)
            / safe_component(protocol_version)
            / safe_component(package_id)
        )
        package_root.mkdir(parents=True, exist_ok=False)

        values = {
            "studies": studies,
            "discovered_reports": discovered_reports,
            "discovered_report_links": discovered_report_links,
            "report_evidence": report_evidence,
            "issues": issues,
        }
        collection_manifest: dict[str, dict[str, object]] = {}
        for name, filename in _COLLECTION_PATHS.items():
            path = package_root / filename
            write_jsonl(path, values[name])
            collection_manifest[name] = {
                "path": filename,
                "sha256": sha256_file(path),
                "record_count": len(values[name]),
            }

        reviews_root = package_root / "reviews"
        reviews_root.mkdir()
        reviewer_manifest: list[dict[str, object]] = []
        for snapshot in sorted(
            review_runs,
            key=lambda item: item.role,
        ):
            role_root = (
                reviews_root
                / safe_component(snapshot.role)
            )
            role_root.mkdir(parents=True)
            final_path = role_root / "final.json"
            atomic_write_text(
                final_path,
                json.dumps(
                    jsonable(snapshot.output),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            files = [
                {
                    "path": str(final_path.relative_to(package_root)),
                    "sha256": sha256_file(final_path),
                }
            ]
            for relative, content in sorted(snapshot.artifacts.items()):
                relative_path = Path(relative)
                if (
                    relative_path.is_absolute()
                    or ".." in relative_path.parts
                    or not relative_path.parts
                ):
                    raise ValueError("review artifact path is invalid")
                path = role_root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                files.append(
                    {
                        "path": str(path.relative_to(package_root)),
                        "sha256": sha256_file(path),
                    }
                )
            reviewer_manifest.append(
                {
                    "role": snapshot.role,
                    "files": files,
                }
            )

        manifest = {
            "schema_version": "study-characteristics-package.v6",
            "package_id": package_id,
            "review_id": review_id,
            "protocol_version": protocol_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "collections": collection_manifest,
            "reviewer_outputs": reviewer_manifest,
            "methodology_authorities": [
                jsonable(item)
                for item in sorted(
                    methodology_authorities,
                    key=lambda item: (item.agent_role, item.title),
                )
            ],
        }
        manifest_path = package_root / "manifest.json"
        atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        return StudyCharacteristicsPackageRef(
            package_id=package_id,
            review_id=review_id,
            protocol_version=protocol_version,
            schema_version="study-characteristics-package.v6",
            content_digest=f"sha256:{sha256_file(manifest_path)}",
        )

    def validate(
        self,
        package_ref: StudyCharacteristicsPackageRef,
    ) -> dict[str, Any]:
        manifest_path = self.resolve_manifest(package_ref)
        if not manifest_path.is_file():
            raise ValueError("Study Characteristics Package manifest does not exist")
        if sha256_file(manifest_path) != package_ref.content_digest.removeprefix(
            "sha256:"
        ):
            raise ValueError(
                "Study Characteristics Package manifest digest does not match"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field in (
            "package_id",
            "review_id",
            "protocol_version",
            "schema_version",
        ):
            if manifest.get(field) != getattr(package_ref, field):
                raise ValueError(
                    f"Study Characteristics Package {field} does not match"
                )
        collections = manifest.get("collections")
        if not isinstance(collections, dict) or set(collections) != set(
            _COLLECTION_PATHS
        ):
            raise ValueError(
                "Study Characteristics Package collections do not match schema"
            )
        authorities = manifest.get("methodology_authorities")
        if not isinstance(authorities, list):
            raise ValueError(
                "Study Characteristics Package methodology authorities are missing"
            )
        for authority in authorities:
            if not isinstance(authority, dict):
                raise ValueError(
                    "Study Characteristics Package methodology authority is invalid"
                )
        try:
            TypeAdapter(tuple[StudyCharacteristicsMethodologyAuthority]).validate_python(
                authorities
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise ValueError(
                "Study Characteristics Package methodology authorities are invalid"
            ) from exc
        root = manifest_path.parent
        for item in collections.values():
            path = validated_member(
                root,
                item,
                label="Study Characteristics Package",
            )
            count = sum(
                bool(line.strip())
                for line in path.read_text(encoding="utf-8").splitlines()
            )
            if count != item["record_count"]:
                raise ValueError(
                    "Study Characteristics Package collection count mismatch"
                )
        reviewers = manifest.get("reviewer_outputs")
        if not isinstance(reviewers, list):
            raise ValueError(
                "Study Characteristics Package reviewer outputs are missing"
            )
        for reviewer in reviewers:
            files = reviewer.get("files") if isinstance(reviewer, dict) else None
            if not isinstance(files, list) or not files:
                raise ValueError(
                    "Study Characteristics Package reviewer files are invalid"
                )
            for item in files:
                validated_member(
                    root,
                    item,
                    label="Study Characteristics Package",
                )
        return manifest

    def resolve_manifest(
        self,
        package_ref: StudyCharacteristicsPackageRef,
    ) -> Path:
        root = self.root.expanduser().resolve()
        path = (
            root
            / safe_component(package_ref.review_id)
            / safe_component(package_ref.protocol_version)
            / safe_component(package_ref.package_id)
            / "manifest.json"
        ).resolve()
        if not path.is_relative_to(root):
            raise ValueError(
                "Study Characteristics Package reference escapes package root"
            )
        return path
