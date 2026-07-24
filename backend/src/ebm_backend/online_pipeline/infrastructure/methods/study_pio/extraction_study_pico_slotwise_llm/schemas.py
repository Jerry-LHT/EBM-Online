"""Strict response schemas for the slotwise Study PICO stages."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.study_pio.extraction_study_pico_slotwise_llm.materials import (
    StageName,
)


_NON_EMPTY_STRING = {"type": "string", "minLength": 1}
_WARNINGS_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
}


def stage_response_schema(stage: StageName) -> dict[str, Any]:
    if stage == "population":
        return {
            "type": "object",
            "properties": {
                "population": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "eligibility_notes": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
                        },
                    },
                    "required": ["description", "eligibility_notes"],
                    "additionalProperties": False,
                },
                "warnings": _WARNINGS_SCHEMA,
            },
            "required": ["population", "warnings"],
            "additionalProperties": False,
        }
    if stage == "intervention_comparator":
        arm_schema = {
            "type": "object",
            "properties": {
                "label": _NON_EMPTY_STRING,
                "description": _NON_EMPTY_STRING,
            },
            "required": ["label", "description"],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                "interventions": {"type": "array", "items": arm_schema},
                "comparators": {"type": "array", "items": arm_schema},
                "warnings": _WARNINGS_SCHEMA,
            },
            "required": ["interventions", "comparators", "warnings"],
            "additionalProperties": False,
        }
    if stage == "outcome":
        return {
            "type": "object",
            "properties": {
                "outcomes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "outcome_label": _NON_EMPTY_STRING,
                            "measurement": _NON_EMPTY_STRING,
                            "timepoints": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "outcome_label",
                            "measurement",
                            "timepoints",
                        ],
                        "additionalProperties": False,
                    },
                },
                "warnings": _WARNINGS_SCHEMA,
            },
            "required": ["outcomes", "warnings"],
            "additionalProperties": False,
        }
    raise ValueError(f"Unsupported Study PIO stage: {stage}")
