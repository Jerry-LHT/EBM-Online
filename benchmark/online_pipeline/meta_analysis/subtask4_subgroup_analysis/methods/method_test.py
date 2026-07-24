"""Deterministic subgroup analysis method."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from benchmark.online_pipeline.meta_analysis.subtask4_subgroup_analysis.methods.stats import (
    participant_count,
    pool_rows,
)


class Method:
    def run(self, *, instances: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return predict_subgroup_results(instances)


def predict_subgroup_results(instances: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for instance in instances:
        family_id = str((instance.get("analysis_setting") or {}).get("setting_family_id") or "")
        by_family[family_id].append(instance)
    predictions: dict[str, dict[str, Any]] = {}
    for family_instances in by_family.values():
        subgroup_estimates = []
        for instance in family_instances:
            setting = instance.get("analysis_setting") or {}
            subgroup = setting.get("subgroup") or {}
            if subgroup.get("source") != "official_subgroup_estimates":
                continue
            rows = instance.get("study_result_rows") or []
            methods = instance.get("analysis_methods") or []
            if not rows or not methods:
                continue
            method = methods[0]
            pooled = pool_rows(rows=rows, data_type=setting.get("data_type"))
            if pooled is None:
                continue
            study_ids = sorted({str(row.get("study_id") or "") for row in rows if row.get("study_id")})
            subgroup_estimates.append(
                {
                    "subgroup_estimate_id": f"subgroup-estimate::{setting.get('setting_id')}",
                    "setting_id": setting.get("setting_id"),
                    "setting_family_id": setting.get("setting_family_id"),
                    "method_id": method.get("method_id"),
                    "candidate_id": setting.get("candidate_id"),
                    "subgroup": subgroup,
                    "included_study_ids": study_ids,
                    "study_count": len(study_ids),
                    "participant_count": participant_count(rows),
                    "data_type": setting.get("data_type"),
                    "effect_measure": method.get("effect_measure"),
                    "analysis_model": method.get("analysis_model"),
                    "statistical_method": method.get("statistical_method"),
                    "ci_level": method.get("ci_level"),
                    "estimation_status": "calculated_by_method_test",
                    "effect_value": pooled["effect_value"],
                    "ci_lower": pooled["ci_lower"],
                    "ci_upper": pooled["ci_upper"],
                    "heterogeneity": {"tau2": 0.0, "chi2": 0.0, "df": max(len(rows) - 1, 0), "p_value": 1.0, "i2": 0.0},
                    "source_joined": True,
                    "source": {"method": "method_test"},
                }
            )
        test_rows = []
        if len(subgroup_estimates) >= 2:
            first = family_instances[0].get("analysis_setting") or {}
            test_rows.append(
                {
                    "subgroup_difference_test_id": f"subgroup-difference::{first.get('setting_family_id')}",
                    "candidate_id": first.get("candidate_id"),
                    "setting_family_id": first.get("setting_family_id"),
                    "comparison": first.get("comparison") or {},
                    "outcome": first.get("outcome") or {},
                    "timepoint": first.get("timepoint") or {"label": None, "window": None},
                    "data_type": first.get("data_type"),
                    "effect_measure": first.get("effect_measure"),
                    "level_estimate_ids": [row["subgroup_estimate_id"] for row in subgroup_estimates],
                    "test_status": "calculated_by_method_test",
                    "chi2": 0.0,
                    "df": max(len(subgroup_estimates) - 1, 0),
                    "p_value": 1.0,
                    "i2_between_subgroups": 0.0,
                }
            )
        for instance in family_instances:
            setting = instance.get("analysis_setting") or {}
            matching = [row for row in subgroup_estimates if row.get("setting_id") == setting.get("setting_id")]
            predictions[str(instance["instance_id"])] = {
                "subgroup_estimates": matching,
                "subgroup_difference_tests": test_rows if matching else [],
            }
    return predictions


def build_method() -> Method:
    return Method()
