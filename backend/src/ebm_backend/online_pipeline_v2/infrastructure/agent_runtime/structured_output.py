"""Strict JSON parsing and JSON Schema validation for final Agent output."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .errors import AgentOutputError, AgentOutputSchemaError


def make_responses_strict_schema(
    schema: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one schema to the shared Responses strict-output contract.

    Every property is required, nullable fields express optional values
    explicitly, defaults are omitted, and undeclared object properties are
    rejected. The input mapping is not mutated.
    """
    normalized = deepcopy(dict(schema))
    _make_objects_strict(normalized)
    return validate_output_schema(normalized)


def validate_output_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(schema)
    try:
        Draft202012Validator.check_schema(normalized)
    except SchemaError as exc:
        raise AgentOutputSchemaError(
            f"Invalid Agent output JSON Schema: {exc.message}"
        ) from exc
    if normalized.get("type") != "object":
        raise AgentOutputSchemaError(
            "Agent output JSON Schema root type must be object"
        )
    return normalized


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentOutputError("Agent final output is not valid JSON") from exc
    if not isinstance(value, dict):
        raise AgentOutputError("Agent final output must be a JSON object")
    return value


def validate_structured_output(
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_schema = validate_output_schema(schema)
    output = dict(value)
    try:
        Draft202012Validator(normalized_schema).validate(output)
    except ValidationError as exc:
        location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
        raise AgentOutputSchemaError(
            f"Agent output violates JSON Schema at {location}: {exc.message}"
        ) from exc
    return output


def _make_objects_strict(value: object) -> None:
    if isinstance(value, dict):
        value.pop("default", None)
        properties = value.get("properties")
        if isinstance(properties, dict):
            value["additionalProperties"] = False
            value["required"] = list(properties)
        for nested in value.values():
            _make_objects_strict(nested)
    elif isinstance(value, list):
        for nested in value:
            _make_objects_strict(nested)
