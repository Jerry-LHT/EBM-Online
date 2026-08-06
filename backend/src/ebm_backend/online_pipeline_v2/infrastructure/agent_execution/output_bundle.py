"""Provider-neutral validation for declared task output bundles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, Mapping

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskOutputArtifact,
    TaskOutputError,
    TaskRunResult,
)


class ArtifactEncoding(StrEnum):
    JSON_OBJECT = "json_object"
    JSONL_OBJECTS = "jsonl_objects"
    BYTES = "bytes"


@dataclass(frozen=True, slots=True)
class OutputMemberSpec:
    name: str
    relative_path: str
    manifest_path: str
    encoding: ArtifactEncoding = ArtifactEncoding.JSONL_OBJECTS
    manifest_name: str | None = None

    @property
    def collection_name(self) -> str:
        return self.manifest_name or self.name


@dataclass(frozen=True, slots=True)
class OutputBundleSpec:
    label: str
    schema_version: str
    manifest_name: str
    manifest_relative_path: str
    members: tuple[OutputMemberSpec, ...]
    exact_collections: bool = False

    def requested_artifacts(self) -> dict[str, str]:
        return {
            self.manifest_name: self.manifest_relative_path,
            **{
                member.name: member.relative_path
                for member in self.members
            },
        }


@dataclass(frozen=True, slots=True)
class LoadedOutputBundle:
    manifest: Mapping[str, Any]
    values: Mapping[str, object]

    def json_object(self, name: str) -> dict[str, Any]:
        value = self.values[name]
        if not isinstance(value, dict):
            raise TypeError(f"{name} is not a JSON object")
        return value

    def jsonl_objects(self, name: str) -> tuple[dict[str, Any], ...]:
        value = self.values[name]
        if not isinstance(value, tuple):
            raise TypeError(f"{name} is not a JSONL collection")
        return value


def load_output_bundle(
    result: TaskRunResult,
    spec: OutputBundleSpec,
) -> LoadedOutputBundle:
    artifacts = result.output_artifacts
    required = spec.requested_artifacts()
    missing = sorted(set(required) - set(artifacts))
    if missing:
        raise _bundle_error(
            f"Agent did not create required {spec.label} artifacts: {missing}",
            label=spec.label,
            artifact="output bundle",
            location="/artifacts",
            contract_version=spec.schema_version,
        )
    for name, relative_path in required.items():
        if artifacts[name].relative_path != relative_path:
            raise _bundle_error(
                f"Agent {spec.label} artifact path mismatch for {name}",
                label=spec.label,
                artifact=name,
                location="/relative_path",
                contract_version=spec.schema_version,
            )

    manifest = _json_object(artifacts[spec.manifest_name], "manifest", spec.label)
    if manifest.get("schema_version") != spec.schema_version:
        raise _bundle_error(
            f"unsupported Agent {spec.label} artifact schema",
            label=spec.label,
            artifact=spec.manifest_name,
            location="/schema_version",
            contract_version=spec.schema_version,
        )
    collections = manifest.get("collections")
    if not isinstance(collections, dict):
        raise _bundle_error(
            f"Agent {spec.label} manifest requires collections",
            label=spec.label,
            artifact=spec.manifest_name,
            location="/collections",
            contract_version=spec.schema_version,
        )
    expected_names = {member.collection_name for member in spec.members}
    if spec.exact_collections and set(collections) != expected_names:
        raise _bundle_error(
            f"Agent {spec.label} manifest collections do not match schema",
            label=spec.label,
            artifact=spec.manifest_name,
            location="/collections",
            contract_version=spec.schema_version,
        )

    values: dict[str, object] = {}
    for member in spec.members:
        artifact = artifacts[member.name]
        _validate_collection(
            collections=collections,
            member=member,
            artifact=artifact,
            label=spec.label,
        )
        if member.encoding is ArtifactEncoding.JSON_OBJECT:
            values[member.name] = _json_object(
                artifact,
                member.name,
                spec.label,
            )
        elif member.encoding is ArtifactEncoding.JSONL_OBJECTS:
            values[member.name] = _jsonl_objects(
                artifact,
                member.name,
                spec.label,
            )
        else:
            values[member.name] = artifact.content
    return LoadedOutputBundle(manifest=manifest, values=values)


def _validate_collection(
    *,
    collections: Mapping[str, object],
    member: OutputMemberSpec,
    artifact: TaskOutputArtifact,
    label: str,
) -> None:
    collection_name = member.collection_name
    value = collections.get(collection_name)
    if not isinstance(value, dict):
        raise _bundle_error(
            f"{label} manifest collection {collection_name} is missing",
            label=label,
            artifact="manifest",
            location=f"/collections/{collection_name}",
        )
    if value.get("path") != member.manifest_path:
        raise _bundle_error(
            f"{label} manifest collection path mismatch: {collection_name}",
            label=label,
            artifact="manifest",
            location=f"/collections/{collection_name}/path",
        )
    if value.get("sha256") != artifact.sha256:
        raise _bundle_error(
            f"{label} manifest collection digest mismatch: {collection_name}",
            label=label,
            artifact="manifest",
            location=f"/collections/{collection_name}/sha256",
        )
    record_count = value.get("record_count")
    if not isinstance(record_count, int) or record_count < 0:
        raise _bundle_error(
            f"{label} manifest collection count is invalid: {collection_name}",
            label=label,
            artifact="manifest",
            location=f"/collections/{collection_name}/record_count",
        )
    actual_count = (
        1
        if member.encoding is ArtifactEncoding.JSON_OBJECT
        else sum(
            bool(line.strip())
            for line in _decode_utf8(artifact, member.name, label).splitlines()
        )
    )
    if actual_count != record_count:
        raise _bundle_error(
            f"{label} manifest collection count mismatch: {collection_name}",
            label=label,
            artifact="manifest",
            location=f"/collections/{collection_name}/record_count",
        )


def _json_object(
    artifact: TaskOutputArtifact,
    name: str,
    label: str,
) -> dict[str, Any]:
    try:
        value = json.loads(_decode_utf8(artifact, name, label))
    except json.JSONDecodeError as exc:
        raise _bundle_error(
            f"Agent {label} {name} is not valid JSON",
            label=label,
            artifact=name,
            location="/",
        ) from exc
    if not isinstance(value, dict):
        raise _bundle_error(
            f"Agent {label} {name} must be a JSON object",
            label=label,
            artifact=name,
            location="/",
        )
    return value


def _jsonl_objects(
    artifact: TaskOutputArtifact,
    name: str,
    label: str,
) -> tuple[dict[str, Any], ...]:
    values: list[dict[str, Any]] = []
    line_number = 0
    try:
        for line_number, line in enumerate(
            _decode_utf8(artifact, name, label).splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError("JSONL item must be an object")
            values.append(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _bundle_error(
            f"Agent {label} {name} JSONL is invalid at line {line_number}",
            label=label,
            artifact=name,
            location=f"/line/{line_number}",
        ) from exc
    return tuple(values)


def _decode_utf8(
    artifact: TaskOutputArtifact,
    name: str,
    label: str,
) -> str:
    try:
        return artifact.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _bundle_error(
            f"Agent {label} {name} must be UTF-8",
            label=label,
            artifact=name,
            location="/encoding",
        ) from exc


def _bundle_error(
    message: str,
    *,
    label: str,
    artifact: str,
    location: str,
    contract_version: str | None = None,
) -> TaskOutputError:
    return TaskOutputError(
        message,
        code="artifact_bundle_invalid",
        stage="bundle_integrity",
        artifact=f"{label}:{artifact}",
        location=location,
        contract_version=contract_version,
    )
