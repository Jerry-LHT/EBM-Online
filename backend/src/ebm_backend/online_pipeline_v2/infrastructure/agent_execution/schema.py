"""Provider-neutral strict structured-output schema normalization."""

from copy import deepcopy
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskOutputError,
)


def strict_task_output_schema(
    schema: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = deepcopy(dict(schema))
    _make_objects_strict(normalized)
    try:
        Draft202012Validator.check_schema(normalized)
    except SchemaError as exc:
        raise TaskOutputError(
            f"Invalid task output JSON Schema: {exc.message}"
        ) from exc
    if normalized.get("type") != "object":
        raise TaskOutputError("task output JSON Schema root type must be object")
    return normalized


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
