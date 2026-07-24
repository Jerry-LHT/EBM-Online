"""Choose an analysis method before pooling, without using heterogeneity-test routing."""

from __future__ import annotations

import math
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.overall_estimation.statistical.stats import (
    STATISTICAL_POLICY_ID,
)


class Method:
    def run(self, *, instance: dict[str, Any]) -> list[dict[str, Any]]:
        setting = instance.get("analysis_setting") or {}
        setting_id = str(setting.get("setting_id") or "")
        data_type = str(setting.get("data_type") or "")
        rows = [row for row in instance.get("meta_analysis_data_rows") or [] if isinstance(row, dict)]
        if data_type not in {"Dichotomous", "Continuous"}:
            return [self._unsupported(setting_id=setting_id, data_type=data_type)]

        effect_measure, measure_status, measure_basis = _planned_effect_measure(
            setting=setting,
            data_type=data_type,
        )
        model_assumption, model_status, model_basis = _planned_model(setting=setting)
        if measure_status != "ready" or model_status != "ready":
            method_status = (
                measure_status if measure_status != "ready" else model_status
            )
            return [
                {
                    "method_id": f"method::{setting_id}",
                    "setting_id": setting_id,
                    "data_type": data_type,
                    "method_status": method_status,
                    "status": "not_supported",
                    "effect_measure": effect_measure or "",
                    "analysis_model": _analysis_model(model_assumption),
                    "statistical_method": "",
                    "ci_level": "95%",
                    "heterogeneity_estimator": None,
                    "interval_method": "",
                    "prediction_interval_enabled": False,
                    "statistical_policy_id": STATISTICAL_POLICY_ID,
                    "zero_cell_handling": None,
                    "smd_method": None,
                    "analysis_included_study_ids": [],
                    "analysis_excluded_studies": [],
                    "decision_basis": f"{measure_basis} {model_basis}".strip(),
                    "rationale": f"{measure_basis} {model_basis}".strip(),
                }
            ]

        included, excluded = _eligible_studies(
            rows=rows,
            data_type=data_type,
            effect_measure=effect_measure,
            continuous_result_frame_priority=_setting_definition_list(
                setting,
                "continuous_result_frame_priority",
            ),
        )
        if not included:
            method_status = "insufficient_data"
        else:
            method_status = "ready"
        if model_assumption == "common_effect":
            analysis_model = "fixed_effect"
            heterogeneity_estimator = None
        else:
            analysis_model = "random_effects"
            heterogeneity_estimator = "REML" if len(included) >= 2 else None
        interval_method = "Wald"
        statistical_method = (
            "Mantel-Haenszel"
            if data_type == "Dichotomous" and analysis_model == "fixed_effect"
            else "Inverse Variance"
        )
        zero_cells = data_type == "Dichotomous" and any(
            _has_zero_cell(_result_data(row)) for row in rows
        )
        subgroup = setting.get("subgroup") if isinstance(setting.get("subgroup"), dict) else {}
        is_overall = not subgroup.get("factor") and not subgroup.get("level")
        model_note = (
            "The planned varying-effects assumption is retained, but "
            "between-study heterogeneity is not estimable with one study."
            if model_assumption == "varying_effects" and len(included) == 1
            else model_basis
        )
        return [
            {
                "method_id": f"method::{setting_id}",
                "setting_id": setting_id,
                "data_type": data_type,
                "method_status": method_status,
                "status": "supported" if method_status == "ready" else "not_supported",
                "effect_measure": effect_measure or "",
                "analysis_model": analysis_model,
                "statistical_method": statistical_method,
                "ci_level": "95%",
                "heterogeneity_estimator": heterogeneity_estimator,
                "interval_method": interval_method,
                "prediction_interval_enabled": (
                    is_overall
                    and analysis_model == "random_effects"
                    and len(included) >= 5
                ),
                "statistical_policy_id": STATISTICAL_POLICY_ID,
                "zero_cell_handling": (
                    {
                        "method": "continuity_correction",
                        "correction_value": 0.5,
                        "uninformative_study_rule": "exclude_double_zero_or_double_one_for_relative_effect",
                        "application_scope": "individual_study_effect_and_variance",
                    }
                    if zero_cells and effect_measure in {"Risk Ratio", "Odds Ratio"}
                    else None
                ),
                "smd_method": "Hedges_g" if effect_measure == "Std. Mean Difference" else None,
                "analysis_included_study_ids": included,
                "analysis_excluded_studies": excluded,
                "decision_basis": (
                    f"{measure_basis} Model choice used the pre-pooling clinical assumption "
                    f"'{model_assumption}'; it was not selected from a heterogeneity test. "
                    f"{model_note}"
                ),
                "rationale": f"{measure_basis} {model_note}".strip(),
            }
        ]

    @staticmethod
    def _unsupported(*, setting_id: str, data_type: str) -> dict[str, Any]:
        return {
            "method_id": f"method::{setting_id}",
            "setting_id": setting_id,
            "data_type": data_type,
            "method_status": "unsupported_data_type",
            "status": "not_supported",
            "effect_measure": "",
            "analysis_model": "",
            "statistical_method": "",
            "ci_level": "95%",
            "heterogeneity_estimator": None,
            "interval_method": "",
            "prediction_interval_enabled": False,
            "statistical_policy_id": STATISTICAL_POLICY_ID,
            "zero_cell_handling": None,
            "smd_method": None,
            "analysis_included_study_ids": [],
            "analysis_excluded_studies": [],
            "rationale": f"Unsupported data type: {data_type or 'missing'}",
        }


def _planned_effect_measure(
    *,
    setting: dict[str, Any],
    data_type: str,
) -> tuple[str | None, str, str]:
    raw_planned = _setting_definition_value(setting, "planned_effect_measure")
    planned = _normalized_effect_measure(raw_planned)
    supported = (
        {"Risk Ratio", "Odds Ratio", "Risk Difference"}
        if data_type == "Dichotomous"
        else {"Mean Difference", "Std. Mean Difference"}
    )
    if planned in supported:
        return (
            planned,
            "ready",
            f"The frozen synthesis plan prespecified {planned} for this target.",
        )
    if raw_planned:
        return (
            planned,
            "incompatible_effect_measure",
            f"The frozen effect measure {raw_planned!r} is not valid for {data_type} data.",
        )
    return None, "invalid_plan", (
        "The frozen synthesis plan does not specify an effect measure for this target."
    )


def _planned_model(
    *,
    setting: dict[str, Any],
) -> tuple[str | None, str, str]:
    raw = _setting_definition_value(setting, "clinical_model_assumption")
    normalized = str(raw or "").strip().casefold().replace("_", " ")
    if normalized in {"common", "common effect", "fixed", "fixed effect"}:
        return (
            "common_effect",
            "ready",
            "The frozen synthesis plan prespecified a common-effect assumption.",
        )
    if normalized in {
        "varying",
        "varying effects",
        "random",
        "random effects",
    }:
        return (
            "varying_effects",
            "ready",
            "The frozen synthesis plan prespecified a varying-effects assumption.",
        )
    if raw:
        return (
            None,
            "invalid_plan",
            f"The frozen clinical model assumption {raw!r} is unsupported.",
        )
    return (
        None,
        "invalid_plan",
        "The frozen synthesis plan does not specify a clinical model assumption.",
    )


def _analysis_model(model_assumption: str | None) -> str:
    if model_assumption == "common_effect":
        return "fixed_effect"
    if model_assumption == "varying_effects":
        return "random_effects"
    return ""


def _normalized_effect_measure(value: str | None) -> str | None:
    normalized = str(value or "").strip().casefold().replace("_", " ")
    aliases = {
        "rr": "Risk Ratio",
        "risk ratio": "Risk Ratio",
        "or": "Odds Ratio",
        "odds ratio": "Odds Ratio",
        "rd": "Risk Difference",
        "risk difference": "Risk Difference",
        "md": "Mean Difference",
        "mean difference": "Mean Difference",
        "smd": "Std. Mean Difference",
        "standardized mean difference": "Std. Mean Difference",
        "standardised mean difference": "Std. Mean Difference",
        "std. mean difference": "Std. Mean Difference",
    }
    return aliases.get(normalized)


def _eligible_studies(
    *,
    rows: list[dict[str, Any]],
    data_type: str,
    effect_measure: str | None,
    continuous_result_frame_priority: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    included = []
    excluded = []
    by_study: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        study_id = str(row.get("study_id") or "")
        if study_id:
            by_study.setdefault(study_id, []).append(row)
    for study_id, study_rows in by_study.items():
        valid_results: set[tuple[float, ...]] = set()
        reason = "missing_required_result_data"
        for row in study_rows:
            if str(row.get("extraction_status") or "extracted") != "extracted":
                reason = "ambiguous_extraction"
                continue
            if str(row.get("data_type") or data_type) != data_type:
                reason = "unsupported_data_shape"
                continue
            data = _result_data(row)
            effect_multiplier: int | None = None
            if data_type == "Continuous":
                if _is_giv_result(data) and str(
                    data.get("effect_measure") or ""
                ) != str(effect_measure or ""):
                    reason = "incompatible_direct_effect_measure"
                    continue
                alignment = _continuous_effect_alignment(row)
                result_frame = str(alignment.get("result_frame") or "unclear")
                change_definition = str(
                    alignment.get("change_score_definition") or "unclear"
                )
                scale_direction = str(
                    alignment.get("scale_direction") or "unclear"
                )
                raw_multiplier = alignment.get("effect_multiplier")
                effect_multiplier = (
                    int(raw_multiplier)
                    if raw_multiplier in {-1, 1, -1.0, 1.0}
                    else None
                )
                if result_frame not in continuous_result_frame_priority:
                    reason = "incompatible_continuous_result_frame"
                    continue
                if (
                    result_frame == "change_from_baseline"
                    and change_definition
                    not in {"post_minus_baseline", "baseline_minus_post"}
                ):
                    reason = "uncertain_change_score_definition"
                    continue
                if (
                    effect_measure == "Std. Mean Difference"
                    and scale_direction
                    not in {"higher_is_better", "higher_is_worse"}
                ):
                    reason = "uncertain_smd_scale_direction"
                    continue
                if effect_multiplier not in {-1, 1}:
                    reason = "missing_continuous_effect_alignment"
                    continue
            if _valid_result(data, data_type=data_type):
                if (
                    data_type == "Dichotomous"
                    and effect_measure == "Risk Difference"
                    and _risk_difference_variance(data) <= 0
                ):
                    reason = "zero_variance_risk_difference"
                    continue
                if (
                    data_type == "Dichotomous"
                    and effect_measure in {"Risk Ratio", "Odds Ratio"}
                    and _no_relative_effect_information(data)
                ):
                    reason = "no_relative_effect_information"
                    continue
                valid_results.add(
                    _result_signature(
                        data,
                        data_type=data_type,
                        effect_multiplier=effect_multiplier,
                    )
                )
        if len(valid_results) == 1:
            included.append(study_id)
        else:
            if len(valid_results) > 1:
                reason = "multiple_estimable_results_require_resolution"
            excluded.append(
                {
                    "study_id": study_id,
                    "row_id": str(study_rows[0].get("row_id") or "") or None,
                    "note": reason,
                }
            )
    return included, excluded


def _result_signature(
    data: dict[str, Any],
    *,
    data_type: str,
    effect_multiplier: int | None,
) -> tuple[float, ...]:
    if _is_giv_result(data):
        return (
            _number(data.get("effect_value")),
            _number(data.get("standard_error")),
            float(effect_multiplier or 0),
        )
    fields = (
        (
            "experimental_events",
            "experimental_total",
            "control_events",
            "control_total",
        )
        if data_type == "Dichotomous"
        else (
            "experimental_mean",
            "experimental_sd",
            "experimental_total",
            "control_mean",
            "control_sd",
            "control_total",
        )
    )
    signature = tuple(_number(data.get(field)) for field in fields)
    return (
        (*signature, float(effect_multiplier or 0))
        if data_type == "Continuous"
        else signature
    )


def _result_data(row: dict[str, Any]) -> dict[str, Any]:
    items = row.get("result_items") if isinstance(row.get("result_items"), list) else None
    if items is None:
        items = row.get("candidate_results") if isinstance(row.get("candidate_results"), list) else []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("result_data"), dict):
            continue
        disposition = str(item.get("analysis_disposition") or "")
        if disposition == "ready_for_estimate" or item.get("include_in_estimate") is True:
            return item["result_data"]
    return row.get("result_data") if isinstance(row.get("result_data"), dict) else {}


def _continuous_effect_alignment(row: dict[str, Any]) -> dict[str, Any]:
    items = row.get("result_items") if isinstance(row.get("result_items"), list) else []
    for item in items:
        if isinstance(item, dict) and isinstance(
            item.get("continuous_effect_alignment"), dict
        ):
            return item["continuous_effect_alignment"]
    value = row.get("continuous_effect_alignment")
    return value if isinstance(value, dict) else {}


def _valid_result(data: dict[str, Any], *, data_type: str) -> bool:
    if data_type == "Dichotomous":
        a = _integer_number(data.get("experimental_events"))
        n1 = _integer_number(data.get("experimental_total"))
        c = _integer_number(data.get("control_events"))
        n0 = _integer_number(data.get("control_total"))
        return all(math.isfinite(value) for value in (a, n1, c, n0)) and min(a, c) >= 0 and min(n1, n0) > 0 and a <= n1 and c <= n0
    if _is_giv_result(data):
        effect = _number(data.get("effect_value"))
        standard_error = _number(data.get("standard_error"))
        return (
            math.isfinite(effect)
            and math.isfinite(standard_error)
            and standard_error > 0
            and str(data.get("effect_measure") or "") == "Mean Difference"
            and str(data.get("analysis_scale") or "natural") == "natural"
        )
    values = (
        _number(data.get("experimental_mean")),
        _number(data.get("experimental_sd")),
        _integer_number(data.get("experimental_total")),
        _number(data.get("control_mean")),
        _number(data.get("control_sd")),
        _integer_number(data.get("control_total")),
    )
    return all(math.isfinite(value) for value in values) and values[1] >= 0 and values[4] >= 0 and values[2] > 1 and values[5] > 1 and (values[1] > 0 or values[4] > 0)


def _is_giv_result(data: dict[str, Any]) -> bool:
    return "effect_value" in data or "standard_error" in data


def _risk_difference_variance(data: dict[str, Any]) -> float:
    a = _integer_number(data.get("experimental_events"))
    n1 = _integer_number(data.get("experimental_total"))
    c = _integer_number(data.get("control_events"))
    n0 = _integer_number(data.get("control_total"))
    if not all(math.isfinite(value) for value in (a, n1, c, n0)) or min(n1, n0) <= 0:
        return math.nan
    risk1 = a / n1
    risk0 = c / n0
    return risk1 * (1 - risk1) / n1 + risk0 * (1 - risk0) / n0


def _setting_definition_value(setting: dict[str, Any], name: str) -> str | None:
    source = setting.get("source_context") if isinstance(setting.get("source_context"), dict) else {}
    definition = source.get("setting_definition") if isinstance(source.get("setting_definition"), dict) else {}
    value = definition.get(name) or source.get(name)
    text = str(value or "").strip()
    return text or None


def _setting_definition_list(setting: dict[str, Any], name: str) -> list[str]:
    source = setting.get("source_context") if isinstance(setting.get("source_context"), dict) else {}
    definition = source.get("setting_definition") if isinstance(source.get("setting_definition"), dict) else {}
    value = definition.get(name) or source.get(name)
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _integer_number(value: Any) -> float:
    if isinstance(value, bool):
        return math.nan
    number = _number(value)
    return number if math.isfinite(number) and number.is_integer() else math.nan


def _has_zero_cell(data: dict[str, Any]) -> bool:
    if not data:
        return False
    a = _number(data.get("experimental_events"))
    n1 = _number(data.get("experimental_total"))
    c = _number(data.get("control_events"))
    n0 = _number(data.get("control_total"))
    return any(value == 0 for value in (a, n1 - a, c, n0 - c))


def _no_relative_effect_information(data: dict[str, Any]) -> bool:
    experimental_events = _number(data.get("experimental_events"))
    experimental_total = _number(data.get("experimental_total"))
    control_events = _number(data.get("control_events"))
    control_total = _number(data.get("control_total"))
    return (
        experimental_events == 0
        and control_events == 0
    ) or (
        experimental_events == experimental_total
        and control_events == control_total
    )


def build_method() -> Method:
    return Method()
