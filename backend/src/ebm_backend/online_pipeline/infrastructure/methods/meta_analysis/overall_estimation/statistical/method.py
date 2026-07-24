"""Calculate an overall estimate and enriched analysis data rows."""

from __future__ import annotations

from typing import Any

from .stats import effect_direction_convention, pool_rows


class Method:
    def run(self, *, instance: dict[str, Any]) -> dict[str, Any]:
        setting = instance.get("analysis_setting") or {}
        data_type = _required_data_type(setting.get("data_type"))
        subgroup = setting.get("subgroup") if isinstance(setting.get("subgroup"), dict) else {}
        if subgroup.get("factor") or subgroup.get("level"):
            return {"overall_estimates": [], "meta_analysis_data_rows": []}
        methods = [item for item in instance.get("analysis_methods") or [] if isinstance(item, dict)]
        method = methods[0] if methods else {}
        status = _method_status(method)
        all_rows = _eligible_rows(
            rows=instance.get("meta_analysis_data_rows") or [],
            setting_id=str(setting.get("setting_id") or ""),
            data_type=data_type,
        )
        included_ids = {str(item) for item in method.get("analysis_included_study_ids") or []}
        rows = [row for row in all_rows if str(row.get("study_id") or "") in included_ids]
        estimate_id = f"overall-estimate::{setting.get('setting_id')}"
        pooled = None
        if status == "ready":
            pooled = pool_rows(
                rows=rows,
                data_type=data_type,
                effect_measure=str(method.get("effect_measure") or ""),
                analysis_model=str(method.get("analysis_model") or "fixed_effect"),
                statistical_method=str(method.get("statistical_method") or "") or None,
                zero_cell_handling=method.get("zero_cell_handling") if isinstance(method.get("zero_cell_handling"), dict) else None,
                smd_method=str(method.get("smd_method") or "") or None,
                interval_method=str(method.get("interval_method") or "Wald"),
                prediction_interval_enabled=bool(method.get("prediction_interval_enabled")),
                estimate_id=estimate_id,
                estimate_scope="overall",
                method_id=str(method.get("method_id") or "") or None,
            )
        estimation_status = "computed" if pooled else "insufficient_data"
        study_ids = pooled["included_study_ids"] if pooled else []
        included_row_ids = pooled["included_data_row_ids"] if pooled else []
        data_rows = list((pooled or {}).get("meta_analysis_data_rows") or [])
        data_rows.extend(
            _mark_excluded_rows(
                rows=[row for row in all_rows if str(row.get("data_row_id") or row.get("row_id") or "") not in set(included_row_ids)],
                estimate_id=estimate_id,
                method=method,
                reason="method_not_ready" if status != "ready" else "study_not_estimable",
                scope="overall",
            )
        )
        estimate = {
            "overall_estimate_id": estimate_id,
            "setting_id": setting.get("setting_id"),
            "setting_family_id": setting.get("setting_family_id"),
            "method_id": method.get("method_id"),
            "included_study_ids": study_ids,
            "included_data_row_ids": included_row_ids,
            "study_count": len(study_ids),
            "participant_count": pooled["participant_count"] if pooled else 0,
            "data_type": setting.get("data_type"),
            "effect_measure": method.get("effect_measure"),
            "analysis_model": method.get("analysis_model"),
            "statistical_method": pooled["statistical_method"] if pooled else method.get("statistical_method"),
            "ci_level": method.get("ci_level") or "95%",
            "interval_method": pooled["interval_method"] if pooled else method.get("interval_method") or "Wald",
            "estimation_status": estimation_status,
            "effect_value": pooled["effect_value"] if pooled else None,
            "ci_lower": pooled["ci_lower"] if pooled else None,
            "ci_upper": pooled["ci_upper"] if pooled else None,
            "prediction_interval": pooled["prediction_interval"] if pooled else None,
            "heterogeneity": (
                {"tau2": pooled["tau2"], "chi2": pooled["chi2"], "df": pooled["df"], "p_value": pooled["p_value"], "i2": pooled["i2"], "i2_method": pooled["i2_method"]}
                if pooled and len(study_ids) >= 2
                else None
            ),
            "effect_test": pooled["effect_test"] if pooled else None,
            "effect_direction_convention": effect_direction_convention(
                data_type=data_type,
                effect_measure=str(method.get("effect_measure") or ""),
            ),
            "estimation_notes": (
                "Computed from resolved MetaAnalysisDataRow values using the preselected method."
                + (f" {pooled['method_note']}" if pooled.get("method_note") else "")
                if pooled
                else f"Estimate unavailable because method status is {status!r} or no compatible rows remain."
            ),
        }
        return {"overall_estimates": [estimate], "meta_analysis_data_rows": data_rows}


def _eligible_rows(*, rows: list[Any], setting_id: str, data_type: str) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        subgroup = row.get("subgroup") if isinstance(row.get("subgroup"), dict) else {}
        if (
            str(row.get("setting_id") or setting_id) != setting_id
            or str(row.get("data_type") or data_type) != data_type
            or subgroup.get("factor")
            or subgroup.get("level")
        ):
            continue
        result.append(row)
    return result


def _mark_excluded_rows(*, rows: list[dict[str, Any]], estimate_id: str, method: dict[str, Any], reason: str, scope: str) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "data_row_id": str(row.get("data_row_id") or row.get("row_id") or ""),
            "method_id": method.get("method_id"),
            "estimate_id": estimate_id,
            "estimate_scope": scope,
            "analysis_status": "not_analyzed" if reason == "method_not_ready" else "excluded",
            "analysis_exclusion_reason": reason,
            "effect_measure": method.get("effect_measure"),
            "analysis_model": method.get("analysis_model"),
            "statistical_method": method.get("statistical_method"),
        }
        for row in rows
    ]


def _method_status(method: dict[str, Any]) -> str:
    if method.get("method_status"):
        return str(method["method_status"])
    if method.get("status") == "supported" or method.get("effect_measure"):
        return "ready"
    return "insufficient_data"


def _required_data_type(value: Any) -> str:
    data_type = str(value or "").strip()
    if data_type not in {"Dichotomous", "Continuous"}:
        raise ValueError(
            "Overall estimation supports only Dichotomous or Continuous "
            f"data_type; received {data_type!r}"
        )
    return data_type


def build_method() -> Method:
    return Method()
