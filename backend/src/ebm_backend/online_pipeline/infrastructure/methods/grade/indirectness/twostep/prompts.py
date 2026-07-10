"""Prompt rendering for the two-step indirectness method."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts_twostep"


def extraction_prompt(evidence_package: dict[str, Any]) -> str:
    template = prompt_text("extraction_user_template.txt")
    return (
        template.replace("{{EVIDENCE_JSON}}", _json(evidence_package))
        .replace("{{EXTRACTION_SCHEMA_JSON}}", _json(extraction_schema()))
    )


def threshold_prompt(*, evidence_package: dict[str, Any], extraction: dict[str, Any]) -> str:
    template = prompt_text("threshold_user_template.txt")
    return (
        template.replace("{{EVIDENCE_JSON}}", _json(evidence_package))
        .replace("{{EXTRACTION_JSON}}", _json(extraction))
        .replace("{{THRESHOLD_SCHEMA_JSON}}", _json(threshold_schema()))
    )


def adjudication_prompt(
    *,
    evidence_package: dict[str, Any],
    extraction: dict[str, Any],
    threshold_policy: dict[str, Any],
) -> str:
    template = prompt_text("adjudication_user_template.txt")
    return (
        template.replace("{{EVIDENCE_JSON}}", _json(evidence_package))
        .replace("{{EXTRACTION_JSON}}", _json(extraction))
        .replace("{{THRESHOLD_POLICY_JSON}}", _json(threshold_policy))
        .replace("{{OUTPUT_SCHEMA_JSON}}", _json(output_schema()))
    )


@lru_cache(maxsize=None)
def prompt_text(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def output_schema() -> dict[str, Any]:
    return _schema("output_schema.json", "Indirectness output schema must be a JSON object")


@lru_cache(maxsize=1)
def extraction_schema() -> dict[str, Any]:
    return _schema("extraction_schema.json", "Indirectness extraction schema must be a JSON object")


@lru_cache(maxsize=1)
def threshold_schema() -> dict[str, Any]:
    return _schema("threshold_schema.json", "Indirectness threshold schema must be a JSON object")


def _schema(name: str, error_message: str) -> dict[str, Any]:
    payload = json.loads((PROMPT_DIR / name).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(error_message)
    return payload


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
