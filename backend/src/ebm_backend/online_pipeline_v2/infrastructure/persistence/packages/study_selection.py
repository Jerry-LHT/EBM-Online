"""Filesystem persistence for immutable Study Selection Packages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from ebm_backend.online_pipeline_v2.application.ports.repositories import (
    SelectionAgentSnapshot,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    SelectionCollections,
    SelectionPackageRef,
)
from ..filesystem import (
    atomic_write_text,
    jsonable,
    safe_component,
    sha256_file,
    validated_member,
    write_jsonl,
)


_COLLECTION_PATHS = {
    "record_screening": "record-screening.jsonl",
    "reports": "reports.jsonl",
    "report_discoveries": "report-discoveries.jsonl",
    "record_report_links": "record-report-links.jsonl",
    "report_evidence": "report-evidence.jsonl",
    "studies": "studies.jsonl",
    "study_report_links": "study-report-links.jsonl",
    "study_decisions": "study-decisions.jsonl",
    "conflicts": "conflicts.jsonl",
}


@dataclass(slots=True)
class FileSelectionPackageStore:
    root: Path

    def persist(
        self,
        *,
        review_id: str,
        protocol_version: str,
        collections: SelectionCollections,
        agent_runs: Sequence[SelectionAgentSnapshot],
    ) -> SelectionPackageRef:
        package_id = f"{review_id}:study_selection:{protocol_version}:{uuid4().hex}"
        package_root = (
            self.root.expanduser().resolve()
            / safe_component(review_id)
            / safe_component(protocol_version)
            / safe_component(package_id)
        )
        package_root.mkdir(parents=True, exist_ok=False)

        collection_manifest: dict[str, dict[str, object]] = {}
        for name, filename in _COLLECTION_PATHS.items():
            values = getattr(collections, name)
            path = package_root / filename
            write_jsonl(path, values)
            collection_manifest[name] = {
                "path": filename,
                "sha256": sha256_file(path),
                "record_count": len(values),
            }

        agents_root = package_root / "agent-outputs"
        agents_root.mkdir()
        agent_manifest: dict[str, dict[str, object]] = {}
        for snapshot in sorted(agent_runs, key=lambda item: item.role):
            role = safe_component(snapshot.role)
            role_root = agents_root / role
            role_root.mkdir()
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
            files: list[dict[str, str]] = [
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
            agent_manifest[role] = {"files": files}

        manifest = {
            "schema_version": "selection-package.v4",
            "package_id": package_id,
            "review_id": review_id,
            "protocol_version": protocol_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "collections": collection_manifest,
            "agent_outputs": agent_manifest,
        }
        manifest_path = package_root / "manifest.json"
        atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        return SelectionPackageRef(
            package_id=package_id,
            review_id=review_id,
            protocol_version=protocol_version,
            schema_version="selection-package.v4",
            content_digest=f"sha256:{sha256_file(manifest_path)}",
        )

    def validate(self, package_ref: SelectionPackageRef) -> dict[str, Any]:
        manifest_path = self.resolve_manifest(package_ref)
        if not manifest_path.is_file():
            raise ValueError("Selection Package manifest does not exist")
        if sha256_file(manifest_path) != package_ref.content_digest.removeprefix(
            "sha256:"
        ):
            raise ValueError("Selection Package manifest digest does not match")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != "selection-package.v4":
            raise ValueError("Unsupported Selection Package schema")
        for field in ("package_id", "review_id", "protocol_version", "schema_version"):
            if manifest.get(field) != getattr(package_ref, field):
                raise ValueError(f"Selection Package {field} does not match")
        root = manifest_path.parent
        collections = manifest.get("collections")
        if not isinstance(collections, dict):
            raise ValueError("Selection Package collections are missing")
        if set(collections) != set(_COLLECTION_PATHS):
            raise ValueError("Selection Package collections do not match schema")
        for item in collections.values():
            path = validated_member(root, item, label="Selection Package")
            count = sum(
                bool(line.strip())
                for line in path.read_text(encoding="utf-8").splitlines()
            )
            if count != item["record_count"]:
                raise ValueError("Selection Package collection count mismatch")
        agents = manifest.get("agent_outputs")
        if not isinstance(agents, dict):
            raise ValueError("Selection Package Agent outputs are missing")
        for agent in agents.values():
            files = agent.get("files") if isinstance(agent, dict) else None
            if not isinstance(files, list) or not files:
                raise ValueError("Selection Package Agent files are invalid")
            for item in files:
                validated_member(root, item, label="Selection Package")
        return manifest

    def resolve_manifest(self, package_ref: SelectionPackageRef) -> Path:
        root = self.root.expanduser().resolve()
        path = (
            root
            / safe_component(package_ref.review_id)
            / safe_component(package_ref.protocol_version)
            / safe_component(package_ref.package_id)
            / "manifest.json"
        ).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Selection Package reference escapes package root")
        return path
