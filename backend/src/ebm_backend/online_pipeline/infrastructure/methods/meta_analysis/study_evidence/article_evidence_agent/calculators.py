"""Deterministic completion of arm-level primitives from typed materials."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from scipy.stats import t as student_t


CALCULATOR_VERSION = "cochrane_arm_material_calculator_v1"


@dataclass(frozen=True)
class ArmCalculation:
    values: dict[str, float | int]
    field_traces: dict[str, dict[str, Any]]
    warnings: list[str]


def solve_arm(
    *,
    data_type: str,
    materials: list[dict[str, Any]],
) -> ArmCalculation:
    if data_type == "Dichotomous":
        return _solve_dichotomous(materials)
    if data_type == "Continuous":
        return _solve_continuous(materials)
    return ArmCalculation({}, {}, [f"unsupported_data_type:{data_type}"])


def _solve_dichotomous(materials: list[dict[str, Any]]) -> ArmCalculation:
    warnings: list[str] = []
    total, total_material, total_error = _unique_value_for_kinds(
        materials,
        {"analyzed_total", "result_denominator"},
    )
    if total_error:
        warnings.append(total_error)
    events, event_material, event_error = _unique_value(materials, "event_count")
    if event_error:
        warnings.append(event_error)
    traces: dict[str, dict[str, Any]] = {}
    values: dict[str, float | int] = {}

    total_int = _finite_integer(total)
    if total is not None and total_int is None:
        warnings.append("analyzed_total_must_be_a_finite_integer")
    if total_int is not None and total_int > 0 and total_material is not None:
        values["total"] = total_int
        traces["total"] = _direct_trace(total_material)

    event_int = _finite_integer(events)
    if events is not None and event_int is None:
        warnings.append("event_count_must_be_a_finite_integer")
    if event_int is not None and event_material is not None:
        values["events"] = event_int
        traces["events"] = _direct_trace(event_material)

    if "events" not in values and total_int is not None:
        non_events, non_event_material, non_event_error = _unique_value(
            materials,
            "non_event_count",
        )
        if non_event_error:
            warnings.append(non_event_error)
        non_event_int = _finite_integer(non_events)
        if non_event_int is not None and non_event_material is not None:
            derived = total_int - non_event_int
            if 0 <= derived <= total_int:
                values["events"] = derived
                traces["events"] = _derived_trace(
                    formula="events = analyzed_total - non_event_count",
                    inputs=[total_material, non_event_material],
                    assumptions=[],
                )

    if "events" not in values and total_int is not None:
        percentage, percentage_material, percentage_error = _unique_value(
            materials,
            "percentage",
        )
        if percentage_error:
            warnings.append(percentage_error)
        if percentage is not None and percentage_material is not None:
            decimals = _optional_integer(percentage_material.get("decimal_places"))
            derived, reason = _events_from_rounded_percentage(
                total=total_int,
                percentage=float(percentage),
                decimal_places=decimals,
            )
            if derived is None:
                warnings.append(reason)
            else:
                values["events"] = derived
                traces["events"] = _derived_trace(
                    formula="events is the unique integer compatible with the reported rounded percentage and analyzed total",
                    inputs=[total_material, percentage_material],
                    assumptions=["reported_percentage_uses_conventional_rounding"],
                )

    if "events" in values and "total" in values:
        non_events, _, non_event_error = _unique_value(materials, "non_event_count")
        if non_event_error:
            warnings.append(non_event_error)
        non_event_int = _finite_integer(non_events)
        if non_event_int is not None and int(values["events"]) + non_event_int != int(values["total"]):
            values.pop("events", None)
            traces.pop("events", None)
            warnings.append("event_and_non_event_counts_do_not_sum_to_analyzed_total")

    if "events" in values and "total" in values:
        percentage, percentage_material, percentage_error = _unique_value(materials, "percentage")
        if percentage_error:
            warnings.append(percentage_error)
        if percentage is not None and percentage_material is not None:
            decimals = _optional_integer(percentage_material.get("decimal_places"))
            if decimals is not None and not _reported_percentage_matches_count(
                events=int(values["events"]),
                total=int(values["total"]),
                percentage=float(percentage),
                decimal_places=decimals,
            ):
                values.pop("events", None)
                traces.pop("events", None)
                warnings.append("event_count_conflicts_with_reported_percentage")

    if "events" in values and "total" in values:
        if not 0 <= int(values["events"]) <= int(values["total"]):
            return ArmCalculation({}, {}, [*warnings, "events_outside_zero_to_total"])
    return ArmCalculation(values, traces, _unique_text(warnings))


def _solve_continuous(materials: list[dict[str, Any]]) -> ArmCalculation:
    warnings: list[str] = []
    traces: dict[str, dict[str, Any]] = {}
    values: dict[str, float | int] = {}

    total, total_material, total_error = _unique_value_for_kinds(
        materials,
        {"analyzed_total", "result_denominator"},
    )
    if total_error:
        warnings.append(total_error)
    total_int = _finite_integer(total)
    if total is not None and total_int is None:
        warnings.append("analyzed_total_must_be_a_finite_integer")
    if total_int is not None and total_int > 1 and total_material is not None:
        values["total"] = total_int
        traces["total"] = _direct_trace(total_material)

    mean, mean_material, mean_error = _unique_value(materials, "mean")
    if mean_error:
        warnings.append(mean_error)
    if mean is not None and mean_material is not None and math.isfinite(float(mean)):
        values["mean"] = float(mean)
        traces["mean"] = _direct_trace(mean_material)

    sd, sd_material, sd_error = _unique_value(materials, "standard_deviation")
    if sd_error:
        warnings.append(sd_error)
    if sd is not None and sd_material is not None and math.isfinite(float(sd)) and float(sd) >= 0:
        values["sd"] = float(sd)
        traces["sd"] = _direct_trace(sd_material)

    if "sd" not in values and total_int is not None:
        variance, variance_material, variance_error = _unique_value(materials, "variance")
        if variance_error:
            warnings.append(variance_error)
        if variance is not None and variance_material is not None and float(variance) >= 0:
            values["sd"] = math.sqrt(float(variance))
            traces["sd"] = _derived_trace(
                formula="sd = sqrt(arm_variance)",
                inputs=[variance_material],
                assumptions=["reported_variance_is_for_the_arm_result"],
            )

    if "sd" not in values and total_int is not None:
        se_materials = [
            material
            for material in materials
            if material.get("kind") == "standard_error"
            and material.get("statistical_scope") == "arm"
            and material.get("applies_to") in {"mean", "change_mean"}
        ]
        se, se_material, se_error = _unique_material_value(se_materials)
        if se_error:
            warnings.append(se_error)
        if se is not None and se_material is not None and float(se) >= 0:
            values["sd"] = float(se) * math.sqrt(total_int)
            traces["sd"] = _derived_trace(
                formula="sd = arm_mean_se * sqrt(analyzed_n)",
                inputs=[se_material, total_material],
                assumptions=["standard_error_is_for_the_arm_mean"],
            )

    if "sd" not in values and total_int is not None:
        ci_materials = [
            material
            for material in materials
            if material.get("kind") == "confidence_interval"
            and material.get("statistical_scope") == "arm"
            and material.get("applies_to") in {"mean", "change_mean"}
        ]
        ci_material, ci_error = _unique_material(ci_materials)
        if ci_error:
            warnings.append(ci_error)
        if ci_material is not None:
            derived, reason = _sd_from_arm_mean_ci(
                material=ci_material,
                mean=float(values["mean"]) if "mean" in values else None,
                n=total_int,
            )
            if derived is None:
                warnings.append(reason)
            else:
                values["sd"] = derived
                traces["sd"] = _derived_trace(
                    formula="se = (ci_upper - ci_lower) / (2 * t_quantile); sd = se * sqrt(analyzed_n)",
                    inputs=[ci_material, total_material],
                    assumptions=[
                        "confidence_interval_is_for_the_arm_mean",
                        "t_distribution_with_df_equal_to_n_minus_1",
                    ],
                )

    return ArmCalculation(values, traces, _unique_text(warnings))


def _events_from_rounded_percentage(
    *,
    total: int,
    percentage: float,
    decimal_places: int | None,
) -> tuple[int | None, str]:
    if total <= 0 or not math.isfinite(percentage) or not 0 <= percentage <= 100:
        return None, "invalid_percentage_or_total"
    if decimal_places is None or not 0 <= decimal_places <= 6:
        return None, "percentage_decimal_places_required"
    half_unit = 0.5 * (10 ** (-decimal_places))
    lower = max(0.0, percentage - half_unit)
    upper = min(100.0, percentage + half_unit)
    minimum = max(0, math.ceil((lower * total / 100.0) - 1e-12))
    maximum = min(total, math.floor((upper * total / 100.0) - 1e-12))
    candidates = [
        events
        for events in range(minimum, maximum + 1)
        if abs(round(100.0 * events / total, decimal_places) - percentage)
        <= 0.5 * (10 ** (-decimal_places)) + 1e-12
    ]
    if len(candidates) != 1:
        return None, "reported_percentage_does_not_identify_one_event_count"
    return candidates[0], ""


def _reported_percentage_matches_count(
    *,
    events: int,
    total: int,
    percentage: float,
    decimal_places: int,
) -> bool:
    if total <= 0 or not 0 <= decimal_places <= 6:
        return False
    tolerance = 0.5 * (10 ** (-decimal_places)) + 1e-12
    return abs((100.0 * events / total) - percentage) <= tolerance


def _sd_from_arm_mean_ci(
    *,
    material: dict[str, Any],
    mean: float | None,
    n: int,
) -> tuple[float | None, str]:
    lower = _optional_float(material.get("lower"))
    upper = _optional_float(material.get("upper"))
    level = _normalized_confidence_level(material.get("confidence_level"))
    if lower is None or upper is None or not lower < upper or level is None:
        return None, "invalid_arm_mean_confidence_interval"
    if mean is not None:
        left = mean - lower
        right = upper - mean
        tolerance = max(1e-8, 0.05 * max(abs(left), abs(right), 1.0))
        if abs(left - right) > tolerance:
            return None, "arm_mean_confidence_interval_is_not_symmetric"
    critical = float(student_t.ppf(1.0 - (1.0 - level) / 2.0, df=n - 1))
    if not math.isfinite(critical) or critical <= 0:
        return None, "invalid_t_critical_value"
    sd = ((upper - lower) / (2.0 * critical)) * math.sqrt(n)
    if not math.isfinite(sd) or sd < 0:
        return None, "invalid_derived_standard_deviation"
    return sd, ""


def _unique_value(
    materials: list[dict[str, Any]],
    kind: str,
) -> tuple[float | None, dict[str, Any] | None, str | None]:
    return _unique_material_value(
        [material for material in materials if material.get("kind") == kind]
    )


def _unique_value_for_kinds(
    materials: list[dict[str, Any]],
    kinds: set[str],
) -> tuple[float | None, dict[str, Any] | None, str | None]:
    return _unique_material_value(
        [material for material in materials if material.get("kind") in kinds]
    )


def _unique_material_value(
    materials: list[dict[str, Any]],
) -> tuple[float | None, dict[str, Any] | None, str | None]:
    material, error = _unique_material(materials)
    if material is None:
        return None, None, error
    value = _optional_float(material.get("value"))
    if value is None:
        return None, None, f"material_without_numeric_value:{material.get('material_id')}"
    return value, material, None


def _unique_material(
    materials: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    supplied = [material for material in materials if isinstance(material, dict)]
    if not supplied:
        return None, None
    usable = [material for material in supplied if not material.get("uncertainties")]
    if not usable:
        kinds = sorted({str(material.get("kind") or "unknown") for material in supplied})
        return None, f"uncertain_materials:{','.join(kinds)}"
    signatures = {
        (
            _optional_float(material.get("value")),
            _optional_float(material.get("lower")),
            _optional_float(material.get("upper")),
            _normalized_confidence_level(material.get("confidence_level")),
        )
        for material in usable
    }
    if len(signatures) != 1:
        kinds = sorted({str(material.get("kind") or "unknown") for material in usable})
        return None, f"conflicting_materials:{','.join(kinds)}"
    return usable[0], None


def _direct_trace(material: dict[str, Any]) -> dict[str, Any]:
    derivation = material.get("derivation_trace")
    if isinstance(derivation, dict):
        return {
            "calculator_version": CALCULATOR_VERSION,
            "method": str(derivation.get("method") or "calculated"),
            "formula": derivation.get("formula"),
            "input_material_ids": list(derivation.get("input_material_ids") or []),
            "assumptions": list(derivation.get("assumptions") or []),
        }
    return {
        "calculator_version": CALCULATOR_VERSION,
        "method": "direct",
        "formula": None,
        "input_material_ids": [material.get("material_id")],
        "assumptions": [],
    }


def _derived_trace(
    *,
    formula: str,
    inputs: list[dict[str, Any] | None],
    assumptions: list[str],
) -> dict[str, Any]:
    return {
        "calculator_version": CALCULATOR_VERSION,
        "method": "calculated",
        "formula": formula,
        "input_material_ids": [
            material.get("material_id")
            for material in inputs
            if isinstance(material, dict) and material.get("material_id")
        ],
        "assumptions": assumptions,
    }


def _finite_integer(value: Any) -> int | None:
    number = _optional_float(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _optional_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalized_confidence_level(value: Any) -> float | None:
    level = _optional_float(value)
    if level is None:
        return None
    if level > 1:
        level /= 100.0
    return level if 0 < level < 1 else None


def _unique_text(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
