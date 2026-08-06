"""Filesystem persistence for large Search Packages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4
from pydantic import TypeAdapter

from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchArtifact,
    SearchPackageRef,
)
from ..filesystem import (
    atomic_write_text,
    jsonable,
    safe_component,
    sha256_file,
)


@dataclass(slots=True)
class FileSearchPackageStore:
    """Persist domain-validated Agent search artifacts as an immutable package."""

    root: Path

    def persist(
        self,
        *,
        review_id: str,
        protocol_version: str,
        artifact: EvidenceSearchArtifact,
    ) -> SearchPackageRef:
        package_id = (
            f"{review_id}:evidence_search:{protocol_version}:{uuid4().hex}"
        )
        package_root = (
            self.root
            / safe_component(review_id)
            / safe_component(protocol_version)
            / safe_component(package_id)
        )
        package_root.mkdir(parents=True, exist_ok=True)
        runs_path = package_root / "search_runs.jsonl"
        records_path = package_root / "records.jsonl"

        runs_lines = [
            json.dumps(jsonable(run), ensure_ascii=False, sort_keys=True)
            for run in artifact.search_runs
        ]
        records_lines = [
            json.dumps(jsonable(record), ensure_ascii=False, sort_keys=True)
            for record in artifact.records
        ]
        atomic_write_text(
            runs_path,
            "\n".join(runs_lines) + ("\n" if runs_lines else ""),
        )
        atomic_write_text(
            records_path,
            "\n".join(records_lines) + ("\n" if records_lines else ""),
        )

        manifest = {
            "schema_version": "search-package.v2",
            "package_id": package_id,
            "review_id": review_id,
            "protocol_version": protocol_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": jsonable(artifact.summary),
            "collections": {
                "search_runs": {
                    "path": runs_path.name,
                    "sha256": sha256_file(runs_path),
                    "record_count": len(artifact.search_runs),
                },
                "records": {
                    "path": records_path.name,
                    "sha256": sha256_file(records_path),
                    "record_count": len(artifact.records),
                },
            },
        }
        manifest_path = package_root / "manifest.json"
        atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
        )
        digest = sha256_file(manifest_path)
        return SearchPackageRef(
            package_id=package_id,
            review_id=review_id,
            protocol_version=protocol_version,
            schema_version="search-package.v2",
            content_digest=f"sha256:{digest}",
        )

    def validate(self, package_ref: SearchPackageRef) -> dict[str, Any]:
        manifest_path = self.resolve_manifest(package_ref)
        if not manifest_path.is_file():
            raise ValueError(f"Search Package manifest does not exist: {manifest_path}")
        if sha256_file(manifest_path) != package_ref.content_digest.removeprefix(
            "sha256:"
        ):
            raise ValueError("Search Package manifest digest does not match reference")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("schema_version") != "search-package.v2"
            or package_ref.schema_version != "search-package.v2"
        ):
            raise ValueError("Search Package schema version is not supported")
        if manifest.get("package_id") != package_ref.package_id:
            raise ValueError("Search Package identity does not match reference")
        if manifest.get("review_id") != package_ref.review_id:
            raise ValueError("Search Package review identity does not match reference")
        if manifest.get("protocol_version") != package_ref.protocol_version:
            raise ValueError("Search Package Protocol version does not match reference")
        root = manifest_path.parent
        for collection in manifest.get("collections", {}).values():
            path = (root / str(collection["path"])).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Search Package collection escapes package root")
            if sha256_file(path) != collection["sha256"]:
                raise ValueError(f"Search Package collection digest mismatch: {path}")
            line_count = sum(
                1
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            if line_count != collection["record_count"]:
                raise ValueError(f"Search Package collection count mismatch: {path}")
        return manifest

    def resolve_manifest(self, package_ref: SearchPackageRef) -> Path:
        root = self.root.expanduser().resolve()
        manifest_path = (
            root
            / safe_component(package_ref.review_id)
            / safe_component(package_ref.protocol_version)
            / safe_component(package_ref.package_id)
            / "manifest.json"
        ).resolve()
        if not manifest_path.is_relative_to(root):
            raise ValueError("Search Package reference escapes package root")
        return manifest_path

    def package_directory(self, package_ref: SearchPackageRef) -> Path:
        self.validate(package_ref)
        return self.resolve_manifest(package_ref).parent

    def load(self, package_ref: SearchPackageRef) -> EvidenceSearchArtifact:
        manifest = self.validate(package_ref)
        root = self.resolve_manifest(package_ref).parent
        runs = tuple(
            TypeAdapter(tuple).validate_python(
                [json.loads(line) for line in (root / manifest["collections"]["search_runs"]["path"]).read_text(encoding="utf-8").splitlines()]
            )
        )
        records = tuple(
            TypeAdapter(tuple).validate_python(
                [json.loads(line) for line in (root / manifest["collections"]["records"]["path"]).read_text(encoding="utf-8").splitlines()]
            )
        )
        # TypeAdapter over the dataclass contract restores enums and nested provenance.
        return TypeAdapter(EvidenceSearchArtifact).validate_python(
            {"search_runs": runs, "records": records, "summary": manifest["summary"], "package_ref": package_ref}
        )
