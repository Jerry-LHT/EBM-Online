"""Deterministic overall estimate method."""

from __future__ import annotations

from typing import Any

from benchmark.online_pipeline.meta_analysis.subtask5_overall_estimates.methods.stats import (
    participant_count,
    pool_rows,
)


class Method:
    def run(self, *, instance: dict[str, Any]) -> list[dict[str, Any]]:
        return predict_overall_estimates(instance)


def predict_overall_estimates(instance: dict[str, Any]) -> list[dict[str, Any]]:
    setting = instance.get("analysis_setting") or {}
    rows = instance.get("study_result_rows") or []
    methods = instance.get("analysis_methods") or []
    if not rows or not methods:
        return []
    method = methods[0]
    pooled = pool_rows(rows=rows, data_type=setting.get("data_type"))
    if pooled is None:
        return []
    study_ids = sorted({str(row.get("study_id") or "") for row in rows if row.get("study_id")})
    return [
        {
            "overall_estimate_id": f"overall-estimate::{setting.get('setting_id')}",
            "setting_id": setting.get("setting_id"),
            "setting_family_id": setting.get("setting_family_id"),
            "method_id": method.get("method_id"),
            "candidate_id": setting.get("candidate_id"),
            "included_study_ids": study_ids,
            "study_count": len(study_ids),
            "participant_count": participant_count(rows),
            "data_type": setting.get("data_type"),
            "effect_measure": method.get("effect_measure"),
            "analysis_model": method.get("analysis_model"),
            "statistical_method": method.get("statistical_method"),
            "ci_level": method.get("ci_level"),
            "effect_value": pooled["effect_value"],
            "ci_lower": pooled["ci_lower"],
            "ci_upper": pooled["ci_upper"],
            "prediction_interval": {"lower": None, "upper": None},
            "heterogeneity": {"tau2": 0.0, "chi2": 0.0, "df": max(len(rows) - 1, 0), "p_value": 1.0, "i2": 0.0},
            "effect_test": {"z": None, "p_value": None},
            "estimation_status": "calculated_by_method_test",
            "source_joined": True,
            "source": {"method": "method_test"},
        }
    ]


def build_method() -> Method:
    return Method()
