"""Shared validation for versioned Agent-authored artifact collections."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Generic, TypeVar

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import TypeAdapter, ValidationError

from ebm_backend.online_pipeline_v2.domain.common import DomainValidationError
from .contracts import TaskOutputError


ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True, slots=True)
class VersionedArtifactContract(Generic[ArtifactT]):
    """One authoritative wire schema followed by typed domain construction."""

    name: str
    version: str
    adapter: TypeAdapter[ArtifactT]

    def json_schema(self) -> dict[str, object]:
        schema = deepcopy(self.adapter.json_schema())
        _close_typed_objects(schema)
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = (
            "https://ebm-online.local/artifact-contracts/"
            f"{self.version}.schema.json"
        )
        Draft202012Validator.check_schema(schema)
        return schema

    def canonical_schema_json(self) -> str:
        return (
            json.dumps(
                self.json_schema(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    def validate_python(
        self,
        value: object,
        *,
        artifact: str,
    ) -> ArtifactT:
        schema_value = _json_schema_value(value)
        schema_error = next(
            iter(
                sorted(
                    Draft202012Validator(self.json_schema()).iter_errors(
                        schema_value
                    ),
                    key=lambda item: tuple(str(part) for part in item.absolute_path),
                )
            ),
            None,
        )
        if schema_error is not None:
            location = _json_pointer(schema_error)
            raise TaskOutputError(
                f"{artifact} violates {self.version} at {location}: "
                f"{_schema_error_message(schema_error)}",
                code="artifact_schema_invalid",
                stage="artifact_schema",
                artifact=artifact,
                location=location,
                contract_version=self.version,
            )
        try:
            return self.adapter.validate_python(value)
        except (
            ValidationError,
            DomainValidationError,
            TypeError,
            ValueError,
        ) as exc:
            location, message = _typed_error(exc)
            raise TaskOutputError(
                f"{artifact} violates {self.version} domain invariants at "
                f"{location}: {message}",
                code="artifact_domain_invalid",
                stage="domain_invariant",
                artifact=artifact,
                location=location,
                contract_version=self.version,
            ) from exc


def _close_typed_objects(value: object) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object" and "additionalProperties" not in value:
            value["additionalProperties"] = False
        for child in value.values():
            _close_typed_objects(child)
    elif isinstance(value, list):
        for child in value:
            _close_typed_objects(child)


def _json_schema_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _json_schema_value(child)
            for key, child in value.items()
        }
    if isinstance(value, tuple | list):
        return [_json_schema_value(child) for child in value]
    return value


def _json_pointer(error: JsonSchemaValidationError) -> str:
    if not error.absolute_path:
        return "/"
    escaped = (
        str(part).replace("~", "~0").replace("/", "~1")
        for part in error.absolute_path
    )
    return "/" + "/".join(escaped)


def _schema_error_message(error: JsonSchemaValidationError) -> str:
    if error.validator in {"required", "additionalProperties"}:
        return error.message
    if error.validator == "type":
        return f"expected JSON type {error.validator_value!r}"
    return f"failed JSON Schema constraint {error.validator!r}"


def _typed_error(
    error: ValidationError | DomainValidationError | TypeError | ValueError,
) -> tuple[str, str]:
    if isinstance(error, ValidationError):
        first = error.errors(include_input=False, include_url=False)[0]
        location = "/" + "/".join(
            str(part).replace("~", "~0").replace("/", "~1")
            for part in first.get("loc", ())
        )
        return location or "/", str(first.get("msg", "validation failed"))[:1_000]
    return "/", str(error)[:1_000]
