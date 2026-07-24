"""Strict structured-output schema for GRADE risk-of-bias judgement."""

from __future__ import annotations

from typing import Any


def response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "assessment_status": {
                "type": "string",
                "enum": ["completed", "not_evaluable"],
            },
            "severity": {
                "type": ["string", "null"],
                "enum": ["not_serious", "serious", "very_serious", None],
            },
            "rationale": {"type": "string"},
            "driving_evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "study_id": {"type": "string"},
                        "domains": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["study_id", "domains"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "assessment_status",
            "severity",
            "rationale",
            "driving_evidence",
        ],
        "additionalProperties": False,
    }
