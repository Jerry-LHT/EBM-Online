"""Calculate subgroup estimates, enriched data rows, and interaction tests."""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.overall_estimation.statistical.stats import (
    chi_square_sf,
    effect_direction_convention,
    pool_effect_estimates,
    pool_rows,
)


class Method:
    def run(self, *, instances: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        results = {
            str(instance.get("instance_id")): {
                "subgroup_estimates": [],
                "subgroup_difference_tests": [],
                "meta_analysis_data_rows": [],
            }
            for instance in instances
        }
        computed: dict[tuple[str, ...], list[tuple[str, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for instance in instances:
            instance_id = str(instance.get("instance_id") or "")
            setting = instance.get("analysis_setting") or {}
            data_type = _required_data_type(setting.get("data_type"))
            subgroup = setting.get("subgroup") if isinstance(setting.get("subgroup"), dict) else {}
            factor = str(subgroup.get("factor") or "").strip()
            level = str(subgroup.get("level") or "").strip()
            if not factor or not level:
                continue
            methods = [item for item in instance.get("analysis_methods") or [] if isinstance(item, dict)]
            method = methods[0] if methods else {}
            method_status = _method_status(method)
            all_rows = _eligible_rows(
                rows=instance.get("meta_analysis_data_rows") or [],
                setting=setting,
            )
            included_ids = {str(item) for item in method.get("analysis_included_study_ids") or []}
            rows = [row for row in all_rows if str(row.get("study_id") or "") in included_ids]
            estimate_id = f"subgroup-estimate::{setting.get('setting_id')}"
            pooled = None
            if method_status == "ready":
                pooled = pool_rows(
                    rows=rows,
                    data_type=data_type,
                    effect_measure=str(method.get("effect_measure") or ""),
                    analysis_model=str(method.get("analysis_model") or "fixed_effect"),
                    statistical_method=str(method.get("statistical_method") or "") or None,
                    zero_cell_handling=method.get("zero_cell_handling") if isinstance(method.get("zero_cell_handling"), dict) else None,
                    smd_method=str(method.get("smd_method") or "") or None,
                    interval_method=str(method.get("interval_method") or "Wald"),
                    estimate_id=estimate_id,
                    estimate_scope="subgroup",
                    method_id=str(method.get("method_id") or "") or None,
                )
            study_ids = pooled["included_study_ids"] if pooled else []
            included_row_ids = pooled["included_data_row_ids"] if pooled else []
            data_rows = list((pooled or {}).get("meta_analysis_data_rows") or [])
            data_rows.extend(
                _mark_excluded_rows(
                    rows=[row for row in all_rows if str(row.get("data_row_id") or row.get("row_id") or "") not in set(included_row_ids)],
                    estimate_id=estimate_id,
                    method=method,
                    reason="method_not_ready" if method_status != "ready" else "study_not_estimable",
                )
            )
            estimate = _estimate(
                setting=setting,
                subgroup=subgroup,
                method=method,
                method_status=method_status,
                pooled=pooled,
                estimate_id=estimate_id,
                included_data_row_ids=included_row_ids,
            )
            results[instance_id]["subgroup_estimates"] = [estimate]
            results[instance_id]["meta_analysis_data_rows"] = data_rows
            if pooled:
                key = _interaction_key(setting=setting, method=method, factor=factor)
                computed[key].append((instance_id, estimate, pooled))
        for entries in computed.values():
            test = _difference_test(entries)
            for instance_id, _, _ in entries:
                results[instance_id]["subgroup_difference_tests"] = [test]
        return results


def _estimate(*, setting: dict[str, Any], subgroup: dict[str, Any], method: dict[str, Any], method_status: str, pooled: dict[str, Any] | None, estimate_id: str, included_data_row_ids: list[str]) -> dict[str, Any]:
    study_ids = pooled["included_study_ids"] if pooled else []
    return {
        "subgroup_estimate_id": estimate_id,
        "setting_id": setting.get("setting_id"),
        "setting_family_id": setting.get("setting_family_id"),
        "method_id": method.get("method_id"),
        "comparison": setting.get("comparison") or {},
        "outcome": setting.get("outcome") or {},
        "timepoint": setting.get("timepoint") or {},
        "subgroup": subgroup,
        "included_study_ids": study_ids,
        "included_data_row_ids": included_data_row_ids,
        "study_count": len(study_ids),
        "participant_count": pooled["participant_count"] if pooled else 0,
        "data_type": setting.get("data_type"),
        "effect_measure": method.get("effect_measure"),
        "analysis_model": method.get("analysis_model"),
        "statistical_method": pooled["statistical_method"] if pooled else method.get("statistical_method"),
        "ci_level": method.get("ci_level") or "95%",
        "interval_method": pooled["interval_method"] if pooled else method.get("interval_method") or "Wald",
        "estimation_status": "computed" if pooled else "insufficient_data",
        "effect_value": pooled["effect_value"] if pooled else None,
        "ci_lower": pooled["ci_lower"] if pooled else None,
        "ci_upper": pooled["ci_upper"] if pooled else None,
        "heterogeneity": (
            {"tau2": pooled["tau2"], "chi2": pooled["chi2"], "df": pooled["df"], "p_value": pooled["p_value"], "i2": pooled["i2"], "i2_method": pooled["i2_method"]}
            if pooled and len(study_ids) >= 2
            else None
        ),
        "effect_direction_convention": effect_direction_convention(
            data_type=str(setting.get("data_type") or ""),
            effect_measure=str(method.get("effect_measure") or ""),
        ),
        "estimation_notes": (
            "Computed from resolved MetaAnalysisDataRow values using the preselected method."
            + (f" {pooled['method_note']}" if pooled.get("method_note") else "")
            if pooled
            else f"Subgroup estimate unavailable because method status is {method_status!r} or no compatible rows remain."
        ),
    }


def _mark_excluded_rows(*, rows: list[dict[str, Any]], estimate_id: str, method: dict[str, Any], reason: str) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "data_row_id": str(row.get("data_row_id") or row.get("row_id") or ""),
            "method_id": method.get("method_id"),
            "estimate_id": estimate_id,
            "estimate_scope": "subgroup",
            "analysis_status": "not_analyzed" if reason == "method_not_ready" else "excluded",
            "analysis_exclusion_reason": reason,
            "effect_measure": method.get("effect_measure"),
            "analysis_model": method.get("analysis_model"),
            "statistical_method": method.get("statistical_method"),
        }
        for row in rows
    ]


def _eligible_rows(*, rows: list[Any], setting: dict[str, Any]) -> list[dict[str, Any]]:
    target = setting.get("subgroup") if isinstance(setting.get("subgroup"), dict) else {}
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        subgroup = row.get("subgroup") if isinstance(row.get("subgroup"), dict) else {}
        if (
            str(row.get("setting_id") or setting.get("setting_id") or "") != str(setting.get("setting_id") or "")
            or str(row.get("data_type") or setting.get("data_type") or "") != str(setting.get("data_type") or "")
            or str(subgroup.get("factor") or "") != str(target.get("factor") or "")
            or str(subgroup.get("level") or "") != str(target.get("level") or "")
        ):
            continue
        result.append(row)
    return result


def _difference_test(entries: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    first = entries[0][1]
    setting_family_id = str(first.get("setting_family_id") or "")
    factor = str((first.get("subgroup") or {}).get("factor") or "")
    scopes = {
        str((item[1].get("subgroup") or {}).get("scope") or "study_level")
        for item in entries
    }
    subgroup_scope = next(iter(scopes)) if len(scopes) == 1 else "mixed"
    study_sets = [set(item[1].get("included_study_ids") or []) for item in entries]
    independent = all(
        not study_sets[left].intersection(study_sets[right])
        for left in range(len(study_sets))
        for right in range(left + 1, len(study_sets))
    )
    base = {
        "test_id": f"subgroup-difference::{setting_family_id}::{_slug(factor)}",
        "subgroup_difference_test_id": f"subgroup-difference::{setting_family_id}::{_slug(factor)}",
        "setting_family_id": setting_family_id,
        "subgroup_factor": factor,
        "level_estimate_ids": [item[1]["subgroup_estimate_id"] for item in entries],
        "comparison": first.get("comparison") or {},
        "outcome": first.get("outcome") or {},
        "timepoint": first.get("timepoint") or {},
        "data_type": first.get("data_type"),
        "effect_measure": first.get("effect_measure"),
        "subgroup_scope": subgroup_scope,
    }
    if len(entries) < 2:
        return {**base, "test_status": "insufficient_subgroups", "test_notes": "At least two computed subgroup estimates are required."}
    if subgroup_scope == "participant_level":
        return _participant_interaction(entries=entries, base=base)
    if subgroup_scope != "study_level":
        return {
            **base,
            "test_status": "not_applicable",
            "test_method": "none",
            "test_notes": "Subgroup levels do not share one supported subgroup scope.",
        }
    if not independent:
        return {**base, "test_status": "not_applicable", "test_notes": "The same study contributes to multiple subgroup levels; the independence assumption is violated."}
    weights = [1 / item[2]["conventional_summary_variance"] for item in entries]
    effects = [item[2]["analysis_effect"] for item in entries]
    mean = sum(weight * effect for weight, effect in zip(weights, effects)) / sum(weights)
    q_between = sum(weight * (effect - mean) ** 2 for weight, effect in zip(weights, effects))
    df = len(entries) - 1
    return {
        **base,
        "test_status": "computed",
        "test_method": "between_subgroup_q",
        "chi2": q_between,
        "df": df,
        "p_value": chi_square_sf(q_between, df),
        "i2_between_subgroups": max(0.0, (q_between - df) / q_between * 100) if q_between > 0 else 0.0,
        "test_notes": "Formal inverse-variance interaction test across independent subgroup summaries.",
    }


def _participant_interaction(
    *,
    entries: list[tuple[str, dict[str, Any], dict[str, Any]]],
    base: dict[str, Any],
) -> dict[str, Any]:
    ordered = sorted(
        entries,
        key=lambda item: str((item[1].get("subgroup") or {}).get("level") or "").casefold(),
    )
    if len(ordered) != 2:
        return {
            **base,
            "test_status": "not_applicable",
            "test_method": "within_study_interaction",
            "test_notes": (
                "Participant-level interaction currently requires exactly two subgroup levels."
            ),
        }
    relations = {
        str(
            (item[1].get("subgroup") or {}).get("membership_relation")
            or "unknown"
        )
        for item in ordered
    }
    if relations != {"mutually_exclusive"}:
        return {
            **base,
            "test_status": "not_applicable",
            "test_method": "within_study_interaction",
            "test_notes": (
                "Participant-level interaction requires explicitly mutually exclusive "
                "subgroup membership; overlapping or uncertain levels were not compared."
            ),
        }
    level_a = str((ordered[0][1].get("subgroup") or {}).get("level") or "")
    level_b = str((ordered[1][1].get("subgroup") or {}).get("level") or "")
    rows_a = _included_effect_rows(ordered[0][2])
    rows_b = _included_effect_rows(ordered[1][2])
    paired_studies = sorted(set(rows_a).intersection(rows_b))
    if len(paired_studies) < 2:
        return {
            **base,
            "test_status": "insufficient_paired_studies",
            "test_method": "within_study_interaction",
            "level_a": level_a,
            "level_b": level_b,
            "paired_study_ids": paired_studies,
            "paired_study_count": len(paired_studies),
            "test_notes": (
                "At least two studies reporting both mutually exclusive participant "
                "levels are required to pool within-study interactions."
            ),
        }
    interaction_effects = [
        rows_a[study_id]["analysis_effect"] - rows_b[study_id]["analysis_effect"]
        for study_id in paired_studies
    ]
    interaction_variances = [
        rows_a[study_id]["variance"] + rows_b[study_id]["variance"]
        for study_id in paired_studies
    ]
    analysis_models = {str(item[1].get("analysis_model") or "") for item in ordered}
    interval_methods = {str(item[1].get("interval_method") or "Wald") for item in ordered}
    if len(analysis_models) != 1 or len(interval_methods) != 1:
        return {
            **base,
            "test_status": "not_applicable",
            "test_method": "within_study_interaction",
            "level_a": level_a,
            "level_b": level_b,
            "paired_study_ids": paired_studies,
            "paired_study_count": len(paired_studies),
            "test_notes": "Participant subgroup levels must use the same model and interval method.",
        }
    pooled = pool_effect_estimates(
        effects=interaction_effects,
        variances=interaction_variances,
        analysis_model=next(iter(analysis_models)),
        interval_method=next(iter(interval_methods)),
    )
    if pooled is None:
        return {
            **base,
            "test_status": "insufficient_data",
            "test_method": "within_study_interaction",
            "level_a": level_a,
            "level_b": level_b,
            "paired_study_ids": paired_studies,
            "paired_study_count": len(paired_studies),
            "test_notes": "The paired participant-level interactions were not estimable.",
        }
    ratio = str(base.get("effect_measure") or "") in {"Risk Ratio", "Odds Ratio"}
    transform = math.exp if ratio else lambda value: value
    return {
        **base,
        "test_status": "computed",
        "test_method": "within_study_interaction",
        "level_a": level_a,
        "level_b": level_b,
        "paired_study_ids": paired_studies,
        "paired_study_count": len(paired_studies),
        "interaction_effect_value": transform(pooled["analysis_effect"]),
        "interaction_ci_lower": transform(pooled["ci_lower"]),
        "interaction_ci_upper": transform(pooled["ci_upper"]),
        "interaction_scale": "ratio_of_ratios" if ratio else "difference_in_effect",
        "p_value": pooled["effect_test"]["p_value"],
        "interaction_heterogeneity": {
            "tau2": pooled["tau2"],
            "chi2": pooled["chi2"],
            "df": pooled["df"],
            "p_value": pooled["p_value"],
            "i2": pooled["i2"],
            "i2_method": pooled["i2_method"],
        },
        "test_notes": (
            f"Pooled within-study interaction for {level_a} minus {level_b}; "
            "only studies reporting both mutually exclusive participant levels contributed."
        ),
    }


def _included_effect_rows(pooled: dict[str, Any]) -> dict[str, dict[str, float]]:
    rows: dict[str, dict[str, float]] = {}
    for row in pooled.get("meta_analysis_data_rows") or []:
        if not isinstance(row, dict) or str(row.get("analysis_status") or "") != "included":
            continue
        study_id = str(row.get("study_id") or "")
        effect = row.get("analysis_effect")
        variance = row.get("variance")
        if study_id and isinstance(effect, (int, float)) and isinstance(variance, (int, float)) and variance > 0:
            rows[study_id] = {"analysis_effect": float(effect), "variance": float(variance)}
    return rows


def _interaction_key(*, setting: dict[str, Any], method: dict[str, Any], factor: str) -> tuple[str, ...]:
    comparison = setting.get("comparison") or {}
    outcome = setting.get("outcome") or {}
    timepoint = setting.get("timepoint") or {}
    return tuple(str(value or "").casefold() for value in (
        setting.get("setting_family_id"), comparison.get("experimental"), comparison.get("comparator"),
        outcome.get("label"), outcome.get("measure"), timepoint.get("label"), setting.get("data_type"),
        method.get("effect_measure"), method.get("analysis_model"), method.get("interval_method"),
        factor, (setting.get("subgroup") or {}).get("scope"),
    ))


def _method_status(method: dict[str, Any]) -> str:
    if method.get("method_status"):
        return str(method["method_status"])
    if method.get("status") == "supported" or method.get("effect_measure"):
        return "ready"
    return "insufficient_data"


def _required_data_type(value: Any) -> str:
    data_type = str(value or "").strip()
    if data_type not in {"Dichotomous", "Continuous"}:
        raise ValueError(f"Subgroup analysis supports only Dichotomous or Continuous data_type; received {data_type!r}")
    return data_type


def _slug(value: str) -> str:
    return "-".join(value.strip().casefold().split()) or "unknown"


def build_method() -> Method:
    return Method()
