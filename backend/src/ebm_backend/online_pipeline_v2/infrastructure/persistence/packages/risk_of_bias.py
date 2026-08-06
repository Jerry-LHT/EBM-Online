"""Filesystem persistence for immutable Risk of Bias v4 packages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from ebm_backend.online_pipeline_v2.domain.common import ArtifactIssue
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasDocumentV4,
    RiskOfBiasPackageRef,
    RiskOfBiasReviewProcess,
)
from ..filesystem import (
    atomic_write_text,
    jsonable,
    safe_component,
    sha256_file,
    validated_member,
    write_jsonl,
)


_DOCUMENT = "risk-of-bias-document.json"
_COLLECTION_PATHS = {
    "method_uses": "method-uses.jsonl",
    "targets": "targets.jsonl",
    "assessments": "assessments.jsonl",
    "evidence_observations": "evidence-observations.jsonl",
    "unassessed_results": "unassessed-results.jsonl",
    "issues": "issues.jsonl",
}
_FORBIDDEN_KEYS = {
    "full_text",
    "fulltext",
    "raw_full_text",
    "document_content",
    "downloaded_document",
}


@dataclass(slots=True)
class FileRiskOfBiasPackageStore:
    root: Path

    def persist(
        self,
        *,
        review_id: str,
        protocol_version: str,
        document: RiskOfBiasDocumentV4,
        issues: Sequence[ArtifactIssue],
        review_process: RiskOfBiasReviewProcess,
    ) -> RiskOfBiasPackageRef:
        package_id = f"{review_id}:risk_of_bias:{protocol_version}:{uuid4().hex}"
        package_root = (
            self.root.expanduser().resolve()
            / safe_component(review_id)
            / safe_component(protocol_version)
            / safe_component(package_id)
        )
        package_root.mkdir(parents=True, exist_ok=False)

        document_value = _ensure_safe_json(document.model_dump(mode="json"))
        _write_json(package_root / _DOCUMENT, document_value)
        values: Mapping[str, Sequence[object]] = {
            "method_uses": document.method_uses,
            "targets": document.targets,
            "assessments": document.assessments,
            "evidence_observations": document.evidence_observations,
            "unassessed_results": document.coverage.unassessed_results,
            "issues": issues,
        }
        collection_manifest: dict[str, dict[str, object]] = {}
        for name, filename in _COLLECTION_PATHS.items():
            path = package_root / filename
            write_jsonl(
                path,
                values[name],
                transform=lambda value: _ensure_safe_json(jsonable(value)),
            )
            collection_manifest[name] = {
                "path": filename,
                "sha256": sha256_file(path),
                "record_count": len(values[name]),
            }

        manifest = {
            "schema_version": "risk-of-bias-package.v4",
            "package_id": package_id,
            "review_id": review_id,
            "protocol_version": protocol_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "review_process": _ensure_safe_json(jsonable(review_process)),
            "authoritative_document": {
                "path": _DOCUMENT,
                "sha256": sha256_file(package_root / _DOCUMENT),
            },
            "collections": collection_manifest,
        }
        manifest_path = package_root / "manifest.json"
        _write_json(manifest_path, manifest)
        return RiskOfBiasPackageRef(
            package_id=package_id,
            review_id=review_id,
            protocol_version=protocol_version,
            schema_version="risk-of-bias-package.v4",
            content_digest=f"sha256:{sha256_file(manifest_path)}",
        )

    def validate(self, package_ref: RiskOfBiasPackageRef) -> dict[str, Any]:
        manifest_path = self.resolve_manifest(package_ref)
        if not manifest_path.is_file():
            raise ValueError("Risk of Bias Package manifest does not exist")
        if sha256_file(manifest_path) != package_ref.content_digest.removeprefix(
            "sha256:"
        ):
            raise ValueError("Risk of Bias Package manifest digest does not match")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field in ("package_id", "review_id", "protocol_version", "schema_version"):
            if manifest.get(field) != getattr(package_ref, field):
                raise ValueError(f"Risk of Bias Package {field} does not match")
        collections = manifest.get("collections")
        if not isinstance(collections, dict) or set(collections) != set(
            _COLLECTION_PATHS
        ):
            raise ValueError("Risk of Bias Package collections do not match schema")
        root = manifest_path.parent
        document_path = validated_member(
            root,
            manifest.get("authoritative_document"),
            label="Risk of Bias Package",
        )
        RiskOfBiasDocumentV4.model_validate_json(document_path.read_bytes())
        for item in collections.values():
            path = validated_member(root, item, label="Risk of Bias Package")
            count = sum(
                bool(line.strip())
                for line in path.read_text(encoding="utf-8").splitlines()
            )
            if count != item["record_count"]:
                raise ValueError("Risk of Bias Package collection count mismatch")
        return manifest

    def resolve_manifest(self, package_ref: RiskOfBiasPackageRef) -> Path:
        root = self.root.expanduser().resolve()
        path = (
            root
            / safe_component(package_ref.review_id)
            / safe_component(package_ref.protocol_version)
            / safe_component(package_ref.package_id)
            / "manifest.json"
        ).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Risk of Bias Package reference escapes package root")
        return path


def _write_json(path: Path, value: object) -> None:
    atomic_write_text(
        path,
        json.dumps(_ensure_safe_json(value), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
    )


def _ensure_safe_json(value: object, *, key: str | None = None) -> object:
    if key is not None and key.casefold() in _FORBIDDEN_KEYS:
        raise ValueError(f"Risk of Bias package contains prohibited field: {key}")
    if isinstance(value, dict):
        return {
            str(name): _ensure_safe_json(item, key=str(name))
            for name, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_ensure_safe_json(item) for item in value]
    return value
