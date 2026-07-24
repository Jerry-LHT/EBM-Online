"""Strict threshold contract owned by the expert-threshold method."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


THRESHOLD_SCALES = {
    "absolute_risk_difference_per_1000",
    "mean_difference",
    "standardized_mean_difference",
    "unavailable",
}
OUTCOME_DIRECTIONS = {
    "lower_is_better",
    "higher_is_better",
    "event_is_harmful",
    "event_is_beneficial",
    "unclear",
}


@dataclass(frozen=True)
class ThresholdProfile:
    status: str
    threshold_scale: str
    important_benefit: float | None
    important_harm: float | None
    important_benefit_magnitude: float | None
    important_harm_magnitude: float | None
    unit: str
    outcome_direction: str
    effect_direction_convention: str
    basis: str
    source_urls: list[str]
    source_summary: str
    rationale: str
    confidence: str


def threshold_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {
        "status": {"type": "string", "enum": ["usable", "unavailable"]},
        "threshold_scale": {
            "type": "string",
            "enum": sorted(THRESHOLD_SCALES),
        },
        "important_benefit_magnitude": {"type": ["number", "null"]},
        "important_harm_magnitude": {"type": ["number", "null"]},
        "unit": {"type": "string"},
        "outcome_direction": {
            "type": "string",
            "enum": sorted(OUTCOME_DIRECTIONS),
        },
        "basis": {
            "type": "string",
            "enum": ["source_backed", "expert_judgement", "unavailable"],
        },
        "source_urls": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
        },
        "source_summary": {"type": "string"},
        "rationale": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low", "none"],
        },
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def parse_threshold(
    raw: dict[str, Any],
    *,
    expected_scale: str,
    effect_direction_convention: str,
) -> ThresholdProfile:
    status = _choice(raw.get("status"), {"usable", "unavailable"}, "status")
    scale = _choice(raw.get("threshold_scale"), THRESHOLD_SCALES, "threshold_scale")
    direction = _choice(
        raw.get("outcome_direction"),
        OUTCOME_DIRECTIONS,
        "outcome_direction",
    )
    basis = _choice(
        raw.get("basis"),
        {"source_backed", "expert_judgement", "unavailable"},
        "basis",
    )
    confidence = _choice(
        raw.get("confidence"),
        {"high", "medium", "low", "none"},
        "confidence",
    )
    urls = _urls(raw.get("source_urls"))
    rationale = str(raw.get("rationale") or "").strip()
    source_summary = str(raw.get("source_summary") or "").strip()
    unit = str(raw.get("unit") or "").strip()
    benefit_magnitude = _optional_number(raw.get("important_benefit_magnitude"))
    harm_magnitude = _optional_number(raw.get("important_harm_magnitude"))

    if not rationale:
        raise ValueError("GRADE imprecision threshold rationale must not be empty")
    if status == "unavailable":
        if scale != "unavailable" or basis != "unavailable":
            raise ValueError(
                "Unavailable GRADE imprecision thresholds must use unavailable scale and basis"
            )
        if benefit_magnitude is not None or harm_magnitude is not None:
            raise ValueError(
                "Unavailable GRADE imprecision thresholds must not contain numeric boundaries"
            )
        if confidence != "none":
            raise ValueError(
                "Unavailable GRADE imprecision thresholds must use confidence=none"
            )
        return ThresholdProfile(
            status=status,
            threshold_scale=scale,
            important_benefit=None,
            important_harm=None,
            important_benefit_magnitude=None,
            important_harm_magnitude=None,
            unit=unit,
            outcome_direction=direction,
            effect_direction_convention=effect_direction_convention,
            basis=basis,
            source_urls=urls,
            source_summary=source_summary,
            rationale=rationale,
            confidence=confidence,
        )

    if scale != expected_scale:
        raise ValueError(
            "GRADE imprecision threshold scale does not match the effect estimate: "
            f"expected {expected_scale}, got {scale}"
        )
    if basis not in {"source_backed", "expert_judgement"}:
        raise ValueError("Usable GRADE imprecision threshold has invalid basis")
    if confidence == "none":
        raise ValueError("Usable thresholds require a non-none confidence")
    if basis == "source_backed":
        if not urls:
            raise ValueError("Source-backed threshold requires at least one source URL")
        if confidence not in {"high", "medium"}:
            raise ValueError(
                "Source-backed thresholds require high or medium confidence"
            )
        if not source_summary:
            raise ValueError("Source-backed threshold requires a source summary")
    if benefit_magnitude is None or harm_magnitude is None:
        raise ValueError("Usable threshold requires benefit and harm magnitudes")
    if benefit_magnitude <= 0 or harm_magnitude <= 0:
        raise ValueError("Usable threshold magnitudes must be positive")
    if direction == "unclear":
        raise ValueError(
            "Usable thresholds require a known outcome direction"
        )
    if not unit:
        raise ValueError("Usable threshold unit must not be empty")
    benefit, harm = _signed_boundaries(
        benefit_magnitude=benefit_magnitude,
        harm_magnitude=harm_magnitude,
        outcome_direction=direction,
        effect_direction_convention=effect_direction_convention,
    )
    return ThresholdProfile(
        status=status,
        threshold_scale=scale,
        important_benefit=benefit,
        important_harm=harm,
        important_benefit_magnitude=benefit_magnitude,
        important_harm_magnitude=harm_magnitude,
        unit=unit,
        outcome_direction=direction,
        effect_direction_convention=effect_direction_convention,
        basis=basis,
        source_urls=urls,
        source_summary=source_summary,
        rationale=rationale,
        confidence=confidence,
    )


def expected_threshold_scale(effect_measure: str) -> str | None:
    return {
        "Risk Ratio": "absolute_risk_difference_per_1000",
        "Odds Ratio": "absolute_risk_difference_per_1000",
        "Risk Difference": "absolute_risk_difference_per_1000",
        "Mean Difference": "mean_difference",
        "Std. Mean Difference": "standardized_mean_difference",
    }.get(effect_measure)


def expected_effect_direction_convention(effect_measure: str) -> str | None:
    return {
        "Risk Ratio": "experimental_relative_to_control",
        "Odds Ratio": "experimental_relative_to_control",
        "Risk Difference": "experimental_relative_to_control",
        "Mean Difference": "original_measure_direction",
        "Std. Mean Difference": "positive_favors_experimental",
    }.get(effect_measure)


def _signed_boundaries(
    *,
    benefit_magnitude: float,
    harm_magnitude: float,
    outcome_direction: str,
    effect_direction_convention: str,
) -> tuple[float, float]:
    if effect_direction_convention == "positive_favors_experimental":
        return benefit_magnitude, -harm_magnitude
    if effect_direction_convention not in {
        "experimental_relative_to_control",
        "original_measure_direction",
    }:
        raise ValueError(
            "Unsupported GRADE imprecision effect direction convention"
        )
    if outcome_direction in {"lower_is_better", "event_is_harmful"}:
        return -benefit_magnitude, harm_magnitude
    return benefit_magnitude, -harm_magnitude


def _choice(value: Any, allowed: set[str], name: str) -> str:
    text = str(value or "").strip()
    if text not in allowed:
        raise ValueError(f"Unsupported GRADE imprecision {name}: {text}")
    return text


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean threshold values are not numeric thresholds")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Threshold values must be finite")
    return number


def _urls(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("GRADE imprecision source_urls must be an array")
    urls = [str(item).strip() for item in value if str(item).strip()]
    if len(urls) != len(set(urls)):
        raise ValueError("GRADE imprecision source URLs must be unique")
    if any(not item.startswith(("https://", "http://")) for item in urls):
        raise ValueError("GRADE imprecision source URLs must be HTTP(S) URLs")
    return urls
