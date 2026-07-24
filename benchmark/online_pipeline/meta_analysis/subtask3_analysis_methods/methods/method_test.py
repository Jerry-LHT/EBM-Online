"""Deterministic analysis-method decision method."""

from __future__ import annotations

from typing import Any



class Method:
    def run(self, *, instance: dict[str, Any]) -> list[dict[str, Any]]:
        return predict_analysis_methods(instance)


def predict_analysis_methods(instance: dict[str, Any]) -> list[dict[str, Any]]:
    setting = instance.get("analysis_setting") or {}
    effect_measure = setting.get("effect_measure") or ""
    data_type = setting.get("data_type") or ""
    included_studies = sorted(str(study_id) for study_id in (instance.get("included_studies") or []) if study_id)

    statistical_method = "MH" if data_type == "Dichotomous" else "IV"
    analysis_model = "random_effect"
    if "fixed" in str((setting.get("analysis_name") or "")).lower():
        analysis_model = "fixed_effect"

    return [
        {
            "setting_id": setting.get("setting_id"),
            "method_id": f"method::{setting.get('setting_id')}",
            "effect_measure": effect_measure,
            "analysis_model": analysis_model,
            "statistical_method": statistical_method,
            "ci_level": "95%",
            "subgroup_estimates_enabled": bool((setting.get("subgroup_scope") or {}).get("has_official_subgroup_estimate")),
            "overall_estimates_enabled": (setting.get("subgroup") or {}).get("source") == "overall",
            "test_for_subgroup_differences": bool((setting.get("subgroup_scope") or {}).get("has_official_subgroup_estimate")),
            "analysis_included_study_ids": included_studies,
            "source": "method_test",
        }
    ]


def build_method() -> Method:
    return Method()
