"""Strict result-blind study-to-target applicability classification."""

from __future__ import annotations

from typing import Any


PICO_DOMAINS = ("population", "intervention", "comparator", "outcome")
INFORMATION_STATUSES = {"sufficient", "study_information_insufficient"}
DIRECTNESS_RATINGS = {
    "sufficiently_direct",
    "probably_sufficiently_direct",
    "probably_not_sufficiently_direct",
    "not_sufficiently_direct",
    "not_assessable",
}
ASSESSABLE_DIRECTNESS_RATINGS = DIRECTNESS_RATINGS - {"not_assessable"}
CONCERN_DIRECTNESS_RATINGS = {
    "probably_not_sufficiently_direct",
    "not_sufficiently_direct",
}
EFFECT_DIFFERENCE_LIKELIHOODS = {
    "unlikely",
    "possible",
    "likely",
    "very_likely",
    "unclear",
}
ELIGIBLE_EFFECT_DIFFERENCE_LIKELIHOODS = {"possible", "likely", "very_likely"}
MECHANISMS = {
    "none",
    "effect_modification",
    "baseline_risk",
    "effect_modification_and_baseline_risk",
    "surrogate_or_proxy",
    "measurement_or_timing",
    "comparison_pathway",
}
FACETS = {
    "population": {
        "condition",
        "disease_severity",
        "life_stage_or_age",
        "comorbidity",
        "demographics",
        "subgroup",
        "setting",
    },
    "intervention": {
        "identity",
        "components",
        "dose_or_intensity",
        "duration",
        "delivery",
        "provider_expertise",
        "cointervention",
        "setting",
    },
    "comparator": {
        "identity",
        "components",
        "dose_or_intensity",
        "duration",
        "delivery",
        "provider_expertise",
        "cointervention",
        "setting",
    },
    "outcome": {
        "construct",
        "patient_importance",
        "surrogate",
        "definition",
        "measurement",
        "followup_time",
    },
}
ALLOWED_FIELDS = {
    "population": {
        "target.population",
        "target.subgroup",
        "review.population",
        "screening.inclusion",
        "screening.exclusion",
        "study.population",
        "study.subgroup",
    },
    "intervention": {
        "target.intervention",
        "review.intervention",
        "screening.inclusion",
        "screening.exclusion",
        "study.intervention",
        "study.candidate_interventions",
        "mapping.intervention",
    },
    "comparator": {
        "target.comparator",
        "review.comparator",
        "screening.inclusion",
        "screening.exclusion",
        "study.comparator",
        "study.candidate_comparators",
        "mapping.comparator",
    },
    "outcome": {
        "target.outcome",
        "target.outcome_measure",
        "target.timepoint",
        "review.outcome",
        "screening.inclusion",
        "screening.exclusion",
        "study.outcome",
        "study.result_timepoint",
        "study.outcome_timepoints",
        "study.candidate_outcomes",
        "mapping.outcome",
        "mapping.timepoint",
    },
}


def classification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["assessment_status", "study_assessments"],
        "properties": {
            "assessment_status": {"type": "string", "enum": ["completed"]},
            "study_assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["data_row_id", "study_id", "domains"],
                    "properties": {
                        "data_row_id": {"type": "string", "minLength": 1},
                        "study_id": {"type": "string", "minLength": 1},
                        "domains": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": list(PICO_DOMAINS),
                            "properties": {
                                domain: _domain_schema(domain)
                                for domain in PICO_DOMAINS
                            },
                        },
                    },
                },
            },
        },
    }


def parse_classification(
    payload: dict[str, Any],
    *,
    expected_rows: list[tuple[str, str, dict[str, bool]]],
) -> dict[str, Any]:
    _require_keys(payload, {"assessment_status", "study_assessments"}, "classification")
    if payload["assessment_status"] != "completed":
        raise ValueError("assessment_status must be completed")
    raw_rows = payload["study_assessments"]
    if not isinstance(raw_rows, list) or len(raw_rows) != len(expected_rows):
        raise ValueError(
            "study_assessments must contain exactly one item per contributing DataRow"
        )
    parsed_rows = [
        _parse_study_assessment(raw, expected=expected)
        for raw, expected in zip(raw_rows, expected_rows)
    ]
    return {"assessment_status": "completed", "study_assessments": parsed_rows}


def is_eligible_concern_factor(factor: dict[str, Any]) -> bool:
    return (
        factor["directness"] in CONCERN_DIRECTNESS_RATINGS
        and factor["effect_difference_likelihood"]
        in ELIGIBLE_EFFECT_DIFFERENCE_LIKELIHOODS
        and factor["mechanism"] != "none"
    )


def _domain_schema(domain: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "information_status",
            "overall_directness",
            "factors",
        ],
        "properties": {
            "information_status": {
                "type": "string",
                "enum": sorted(INFORMATION_STATUSES),
            },
            "overall_directness": {
                "type": "string",
                "enum": sorted(DIRECTNESS_RATINGS),
            },
            "factors": {
                "type": "array",
                "items": _factor_schema(domain),
            },
        },
    }


def _factor_schema(domain: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "facet",
            "target_value",
            "study_value",
            "directness",
            "effect_difference_likelihood",
            "mechanism",
            "difference_summary",
            "supporting_fields",
        ],
        "properties": {
            "facet": {"type": "string", "enum": sorted(FACETS[domain])},
            "target_value": {"type": "string", "minLength": 1},
            "study_value": {"type": "string", "minLength": 1},
            "directness": {
                "type": "string",
                "enum": sorted(ASSESSABLE_DIRECTNESS_RATINGS),
            },
            "effect_difference_likelihood": {
                "type": "string",
                "enum": sorted(EFFECT_DIFFERENCE_LIKELIHOODS),
            },
            "mechanism": {"type": "string", "enum": sorted(MECHANISMS)},
            "difference_summary": {"type": "string", "minLength": 1},
            "supporting_fields": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "string",
                    "enum": sorted(ALLOWED_FIELDS[domain]),
                },
            },
        },
    }


def _parse_study_assessment(
    raw: Any,
    *,
    expected: tuple[str, str, dict[str, bool]],
) -> dict[str, Any]:
    item = _object(raw, "study assessment")
    _require_keys(item, {"data_row_id", "study_id", "domains"}, "study assessment")
    data_row_id = _text(item["data_row_id"], "data_row_id")
    study_id = _text(item["study_id"], "study_id")
    expected_row_id, expected_study_id, availability = expected
    if (data_row_id, study_id) != (expected_row_id, expected_study_id):
        raise ValueError(
            "study assessments must preserve contributing DataRow and study order"
        )
    raw_domains = _object(item["domains"], "domains")
    _require_keys(raw_domains, set(PICO_DOMAINS), "domains")
    domains = {
        domain: _parse_domain(
            raw_domains[domain],
            domain=domain,
            expected_available=availability[domain],
        )
        for domain in PICO_DOMAINS
    }
    return {
        "data_row_id": data_row_id,
        "study_id": study_id,
        "domains": domains,
    }


def _parse_domain(
    raw: Any,
    *,
    domain: str,
    expected_available: bool,
) -> dict[str, Any]:
    item = _object(raw, domain)
    _require_keys(
        item,
        {"information_status", "overall_directness", "factors"},
        domain,
    )
    information_status = _enum(
        item["information_status"], INFORMATION_STATUSES, f"{domain}.information_status"
    )
    directness = _enum(
        item["overall_directness"], DIRECTNESS_RATINGS, f"{domain}.overall_directness"
    )
    raw_factors = item["factors"]
    if not isinstance(raw_factors, list):
        raise ValueError(f"{domain}.factors must be an array")
    factors = [_parse_factor(value, domain=domain) for value in raw_factors]
    factor_keys = [(value["facet"], value["mechanism"]) for value in factors]
    if len(set(factor_keys)) != len(factor_keys):
        raise ValueError(f"{domain}.factors must not duplicate facet and mechanism")

    if not expected_available:
        if (
            information_status != "study_information_insufficient"
            or directness != "not_assessable"
            or factors
        ):
            raise ValueError(
                f"unavailable {domain} evidence must be not_assessable with no factors"
            )
    elif information_status != "sufficient" or directness == "not_assessable":
        raise ValueError(f"available {domain} evidence must be assessable")
    elif directness in CONCERN_DIRECTNESS_RATINGS and not any(
        is_eligible_concern_factor(value) for value in factors
    ):
        raise ValueError(
            f"{domain} concern directness requires an eligible concern factor"
        )
    elif directness not in CONCERN_DIRECTNESS_RATINGS and any(
        is_eligible_concern_factor(value) for value in factors
    ):
        raise ValueError(
            f"{domain} overall directness conflicts with its concern factors"
        )
    return {
        "information_status": information_status,
        "overall_directness": directness,
        "factors": factors,
    }


def _parse_factor(raw: Any, *, domain: str) -> dict[str, Any]:
    item = _object(raw, f"{domain} factor")
    expected = {
        "facet",
        "target_value",
        "study_value",
        "directness",
        "effect_difference_likelihood",
        "mechanism",
        "difference_summary",
        "supporting_fields",
    }
    _require_keys(item, expected, f"{domain} factor")
    result = {
        "facet": _enum(item["facet"], FACETS[domain], f"{domain}.facet"),
        "target_value": _text(item["target_value"], f"{domain}.target_value"),
        "study_value": _text(item["study_value"], f"{domain}.study_value"),
        "directness": _enum(
            item["directness"],
            ASSESSABLE_DIRECTNESS_RATINGS,
            f"{domain}.directness",
        ),
        "effect_difference_likelihood": _enum(
            item["effect_difference_likelihood"],
            EFFECT_DIFFERENCE_LIKELIHOODS,
            f"{domain}.effect_difference_likelihood",
        ),
        "mechanism": _enum(item["mechanism"], MECHANISMS, f"{domain}.mechanism"),
        "difference_summary": _text(
            item["difference_summary"], f"{domain}.difference_summary"
        ),
        "supporting_fields": _supporting_fields(
            item["supporting_fields"], domain=domain
        ),
    }
    if result["directness"] in CONCERN_DIRECTNESS_RATINGS:
        if _normalized_value(result["target_value"]) == _normalized_value(
            result["study_value"]
        ):
            raise ValueError(
                f"{domain} concern factor requires different target and study values"
            )
        if result["effect_difference_likelihood"] not in (
            ELIGIBLE_EFFECT_DIFFERENCE_LIKELIHOODS
        ) or result["mechanism"] == "none":
            raise ValueError(
                f"{domain} concern factor requires a plausible effect-difference mechanism"
            )
    elif result["mechanism"] != "none" and result[
        "effect_difference_likelihood"
    ] == "unlikely":
        raise ValueError(
            f"{domain} factor with an unlikely effect difference must use mechanism none"
        )
    return result


def _supporting_fields(value: Any, *, domain: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{domain}.supporting_fields must be a non-empty array")
    result = [_text(item, f"{domain}.supporting_fields") for item in value]
    if len(set(result)) != len(result):
        raise ValueError(f"{domain}.supporting_fields must be unique")
    invalid = [item for item in result if item not in ALLOWED_FIELDS[domain]]
    if invalid:
        raise ValueError(
            f"{domain}.supporting_fields contains unsupported fields: {invalid}"
        )
    return result


def _require_keys(payload: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{context} keys must exactly match schema; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _enum(value: Any, allowed: set[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _normalized_value(value: str) -> str:
    return " ".join(value.casefold().split())
