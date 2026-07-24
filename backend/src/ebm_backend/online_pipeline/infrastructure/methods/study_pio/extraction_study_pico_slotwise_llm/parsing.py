"""Validate slotwise LLM payloads and map them to Study PICO domain objects."""

from __future__ import annotations

import re
from typing import Any

from ebm_backend.online_pipeline.domain.study_characteristics import (
    StudyComparatorCharacteristics,
    StudyInterventionCharacteristics,
    StudyOutcomeCharacteristics,
    StudyPopulationCharacteristics,
)


_POPULATION_KEYS = {"population", "warnings"}
_INTERVENTION_COMPARATOR_KEYS = {"interventions", "comparators", "warnings"}
_OUTCOME_KEYS = {"outcomes", "warnings"}


def validate_stage_payload(*, stage: str, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"{stage} extraction must return a JSON object")
    if stage == "population":
        _require_exact_keys(payload, _POPULATION_KEYS, context=stage)
        parse_population(payload)
    elif stage == "intervention_comparator":
        _require_exact_keys(payload, _INTERVENTION_COMPARATOR_KEYS, context=stage)
        parse_interventions(payload)
        parse_comparators(payload)
    elif stage == "outcome":
        _require_exact_keys(payload, _OUTCOME_KEYS, context=stage)
        parse_outcomes(payload)
    else:
        raise ValueError(f"Unsupported Study PIO stage: {stage}")
    parse_warnings(payload)


def parse_population(payload: dict[str, Any]) -> StudyPopulationCharacteristics:
    value = _required_dict(payload, "population")
    _require_exact_keys(
        value,
        {"description", "eligibility_notes"},
        context="population",
    )
    description = _required_string(value, "description", allow_empty=True)
    raw_notes = value["eligibility_notes"]
    if raw_notes is not None and not isinstance(raw_notes, str):
        raise ValueError("population.eligibility_notes must be a string or null")
    eligibility_notes = _optional_text(raw_notes)
    return StudyPopulationCharacteristics(
        description=description,
        eligibility_notes=eligibility_notes,
    )


def parse_interventions(
    payload: dict[str, Any],
) -> list[StudyInterventionCharacteristics]:
    results: list[StudyInterventionCharacteristics] = []
    for index, item in enumerate(_required_dict_list(payload, "interventions")):
        _require_exact_keys(item, {"label", "description"}, context=f"interventions[{index}]")
        label = _required_string(item, "label")
        description = _required_string(item, "description")
        results.append(
            StudyInterventionCharacteristics(
                label=_label(label),
                description=description,
            )
        )
    return results


def parse_comparators(
    payload: dict[str, Any],
) -> list[StudyComparatorCharacteristics]:
    results: list[StudyComparatorCharacteristics] = []
    for index, item in enumerate(_required_dict_list(payload, "comparators")):
        _require_exact_keys(item, {"label", "description"}, context=f"comparators[{index}]")
        label = _required_string(item, "label")
        description = _required_string(item, "description")
        results.append(
            StudyComparatorCharacteristics(
                label=_label(label),
                description=description,
            )
        )
    return results


def parse_outcomes(payload: dict[str, Any]) -> list[StudyOutcomeCharacteristics]:
    results: list[StudyOutcomeCharacteristics] = []
    for index, item in enumerate(_required_dict_list(payload, "outcomes")):
        context = f"outcomes[{index}]"
        _require_exact_keys(
            item,
            {"outcome_label", "measurement", "timepoints"},
            context=context,
        )
        outcome_label = _required_string(item, "outcome_label")
        measurement = _required_string(item, "measurement")
        timepoints = _required_string_list(item, "timepoints", context=context)
        results.append(
            StudyOutcomeCharacteristics(
                outcome_label=_label(outcome_label),
                measurement=measurement,
                timepoints=timepoints,
            )
        )
    return results


def parse_warnings(payload: dict[str, Any]) -> list[str]:
    return _required_string_list(payload, "warnings", context="warnings", allow_empty=True)


def _require_exact_keys(value: dict[str, Any], expected: set[str], *, context: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise ValueError(
            f"{context} has invalid fields; missing={missing}, extra={extra}"
        )


def _required_dict(payload: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _required_dict_list(
    payload: dict[str, Any], field_name: str
) -> list[dict[str, Any]]:
    value = payload.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{field_name}[{index}] must be an object")
    return value


def _required_string(
    payload: dict[str, Any], field_name: str, *, allow_empty: bool = False
) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    text = _text(value)
    if not allow_empty and not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _required_string_list(
    payload: dict[str, Any],
    field_name: str,
    *,
    context: str,
    allow_empty: bool = False,
) -> list[str]:
    value = payload.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f"{context}.{field_name} must be an array")
    results: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{context}.{field_name}[{index}] must be a string")
        text = _text(item)
        if not text and not allow_empty:
            raise ValueError(f"{context}.{field_name}[{index}] must not be empty")
        if text:
            results.append(text)
    return results


def _label(value: Any) -> str:
    return _text(value)[:120].rstrip(" ,.;:")


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
