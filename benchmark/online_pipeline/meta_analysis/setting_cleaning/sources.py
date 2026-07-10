"""Source shaping for meta-analysis setting cleaning.

This module is intentionally deterministic. It turns the frozen official
analysis CSV snapshot into family-level source bundles and field-specific
cleaning candidates. LLM code consumes these candidates, but this module never
calls an LLM.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SUPPORTED_DATA_TYPES = {"Dichotomous", "Continuous"}
def normalize_official_rows(official_dir: Path) -> dict[str, list[dict[str, Any]]]:
    overall_rows: list[dict[str, Any]] = []
    data_rows: list[dict[str, Any]] = []
    subgroup_rows: list[dict[str, Any]] = []
    for review_dir in sorted(path for path in official_dir.iterdir() if path.is_dir()):
        review_id = review_dir.name
        overall_rows.extend(_normalized_csv_rows(review_dir / f"{review_id}-overall-estimates-and-settings.csv", review_id=review_id))
        data_rows.extend(_normalized_csv_rows(review_dir / f"{review_id}-data-rows.csv", review_id=review_id))
        subgroup_rows.extend(_normalized_csv_rows(review_dir / f"{review_id}-subgroup-estimates.csv", review_id=review_id))
    retained_keys = {
        row["analysis_key"]
        for row in overall_rows
        if _clean((row.get("raw") or {}).get("Data type")) in SUPPORTED_DATA_TYPES
    }
    return {
        "overall": [row for row in overall_rows if row["analysis_key"] in retained_keys],
        "data_rows": [row for row in data_rows if row["analysis_key"] in retained_keys],
        "subgroup_estimates": [row for row in subgroup_rows if row["analysis_key"] in retained_keys],
    }


def build_analysis_family_sources(
    *,
    overall_rows: list[dict[str, Any]],
    data_rows: list[dict[str, Any]],
    subgroup_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    data_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    subgroup_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data_rows:
        data_by_key[row["analysis_key"]].append(row)
    for row in subgroup_rows:
        subgroup_by_key[row["analysis_key"]].append(row)

    families = []
    for row in sorted(overall_rows, key=lambda item: item["analysis_key"]):
        raw = row["raw"]
        key = row["analysis_key"]
        family_data_rows = data_by_key.get(key, [])
        family_subgroup_rows = subgroup_by_key.get(key, [])
        review_id = row["review_id"]
        analysis_group = row["analysis_group"]
        analysis_number = row["analysis_number"]
        families.append(
            {
                "family_source_id": f"family-source::{review_id}::{analysis_group}::{analysis_number}",
                "candidate_id": f"candidate::{review_id}::{analysis_group}::{analysis_number}",
                "setting_family_id": f"setting-family::{review_id}::{analysis_group}::{analysis_number}",
                "review_id": review_id,
                "analysis_group": analysis_group,
                "analysis_number": analysis_number,
                "analysis_key": key,
                "analysis_name": _clean(raw.get("Analysis name")),
                "analysis_group_name": _clean(raw.get("Analysis group name")),
                "explicit_labels": {
                    "experimental_group_label": _nullable(raw.get("Experimental group label")),
                    "control_group_label": _nullable(raw.get("Control group label")),
                },
                "method_source": _method_source(raw),
                "study_row_source": _study_row_source(family_data_rows),
                "subgroup_estimate_source": _subgroup_estimate_source(raw, family_subgroup_rows),
                "source": {
                    "dataset": "cochrane_meta_official_snapshot",
                    "official_analysis_key": key,
                    "overall_source_file": row["source_file"],
                    "overall_row_index": row["row_index"],
                },
            }
        )
    return families


def build_field_candidates(families: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    comparison: list[dict[str, Any]] = []
    outcome: list[dict[str, Any]] = []
    timepoint: list[dict[str, Any]] = []
    for family in families:
        base = {
            "candidate_id": family["candidate_id"],
            "review_id": family["review_id"],
            "analysis_group": family["analysis_group"],
            "analysis_number": family["analysis_number"],
            "analysis_name": family["analysis_name"],
            "analysis_group_name": family["analysis_group_name"],
        }
        method = family.get("method_source") or {}
        study = family.get("study_row_source") or {}
        comparison.append(
            {
                **base,
                "explicit_labels": family.get("explicit_labels") or {},
            }
        )
        outcome.append(
            {
                **base,
                "data_type": method.get("data_type"),
                "effect_measure": method.get("effect_measure"),
                "subgroup_labels_preview": [row["label"] for row in (study.get("subgroup_labels") or [])[:20]],
            }
        )
        timepoint.append(
            {
                **base,
                "footnotes": (study.get("footnotes") or [])[:20],
                "study_row_footnotes": (study.get("footnote_rows") or [])[:50],
                "outcome_hint": None,
            }
        )
    return {"comparison": comparison, "outcome": outcome, "timepoint": timepoint}


def method_from_family(family: dict[str, Any]) -> dict[str, Any]:
    method = family.get("method_source") or {}
    return {
        "candidate_id": family["candidate_id"],
        "setting_family_id": family["setting_family_id"],
        "data_type": method.get("data_type"),
        "effect_measure": method.get("effect_measure"),
        "statistical_method": method.get("statistical_method"),
        "analysis_model": normalize_analysis_model(method.get("analysis_model")),
        "ci_level": method.get("estimate_ci") or method.get("ci_pi_level") or method.get("study_ci") or "95%",
        "overall_estimates_enabled": bool(method.get("overall_estimates_enabled")),
        "subgroup_estimates_enabled": bool(method.get("subgroup_estimates_enabled")),
        "test_for_subgroup_differences": bool(method.get("test_for_subgroup_differences")),
        "source": "official_overall_estimates_and_settings_csv",
    }


def assemble_setting(
    *,
    family: dict[str, Any],
    comparison: dict[str, Any],
    outcome: dict[str, Any],
    timepoint: dict[str, Any],
    method: dict[str, Any],
) -> dict[str, Any]:
    return {
        "candidate_id": family["candidate_id"],
        "setting_family_id": family["setting_family_id"],
        "review_id": family["review_id"],
        "analysis_group": family["analysis_group"],
        "analysis_number": family["analysis_number"],
        "analysis_name": family["analysis_name"],
        "analysis_group_name": family["analysis_group_name"],
        "population_scope": {"label": "review population", "source": "default_review_scope"},
        "comparison": comparison.get("comparison") or {"experimental": None, "comparator": None},
        "comparison_structure": comparison.get("comparison_structure") or {"type": "unclear", "rationale": None},
        "outcome": outcome.get("outcome") or {"outcome_concept": None, "outcome_measure": None},
        "timepoint": timepoint.get("timepoint") or {"label": None, "window": None},
        "data_type": method.get("data_type"),
        "effect_measure": method.get("effect_measure"),
        "method": method,
        "eligible_study_ids": list((family.get("study_row_source") or {}).get("eligible_study_ids") or []),
        "source_context": {
            "study_row_footnotes": list((family.get("study_row_source") or {}).get("footnote_rows") or []),
        },
        "scope_flags": scope_flags(family),
        "source_provenance": family.get("source") or {},
        "setting_quality": setting_quality(comparison=comparison, outcome=outcome, method=method),
        "cleaning": {
            "method": (comparison.get("method") or outcome.get("method") or timepoint.get("method") or "llm_direct_v1"),
            "warnings": _setting_warnings(comparison=comparison, outcome=outcome, method=method),
        },
    }


def normalize_analysis_model(value: Any) -> str:
    text = _clean(value).lower()
    if not text:
        return ""
    if "random" in text:
        return "random_effect"
    if "fixed" in text:
        return "fixed_effect"
    return text.replace(" ", "_")


def scope_flags(family: dict[str, Any]) -> dict[str, Any]:
    method = family.get("method_source") or {}
    data_type = method.get("data_type")
    analysis_name = _clean(family.get("analysis_name"))
    data_rows = (family.get("study_row_source") or {}).get("row_count") or 0
    has_time_to = bool(re.search(r"\b(time\s+to|duration\s+of|days?\s+to)\b", analysis_name, flags=re.IGNORECASE))
    has_survival = bool(re.search(r"\b(hazard\s+ratio|HR|log[- ]?rank|kaplan[- ]?meier|survival\s+curve|time[- ]?to[- ]?event)\b", analysis_name, flags=re.IGNORECASE))
    notes: list[str] = []
    if has_time_to:
        notes.append("time_to_or_duration_phrase")
    if has_survival:
        notes.append("survival_analysis_signal")
    if has_survival:
        data_shape = "unsupported_time_to_event"
        include = False
    elif data_type == "Dichotomous":
        data_shape = "supported_arm_level_dichotomous"
        include = data_rows > 0
    elif data_type == "Continuous":
        data_shape = "supported_arm_level_continuous"
        include = data_rows > 0
    else:
        data_shape = "uncertain"
        include = False
    return {
        "data_shape": data_shape,
        "include_in_primary_eval": include,
        "has_time_to_phrase": has_time_to,
        "has_survival_analysis_signal": has_survival,
        "has_complete_arm_level_numeric_data": data_rows > 0 and data_type in SUPPORTED_DATA_TYPES,
        "notes": notes,
    }


def setting_quality(*, comparison: dict[str, Any], outcome: dict[str, Any], method: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    structure_type = ((comparison.get("comparison_structure") or {}).get("type")) or "unclear"
    if structure_type != "pairwise":
        reasons.append(f"comparison_structure_{structure_type}")
    out = outcome.get("outcome") or {}
    if not out.get("outcome_concept"):
        reasons.append("missing_outcome_concept")
    if method.get("data_type") not in SUPPORTED_DATA_TYPES:
        reasons.append("unsupported_data_type")
    return {
        "ready_for_pairwise_meta_analysis": structure_type == "pairwise",
        "ready_for_downstream_setting_build": not reasons,
        "review_reasons": reasons,
    }


def slug(value: Any) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return "".join(char.lower() if char.isalnum() else "-" for char in ascii_value).strip("-") or "none"


def _normalized_csv_rows(path: Path, *, review_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, raw in enumerate(reader):
            analysis_group = _clean(raw.get("Analysis group"))
            analysis_number = _clean(raw.get("Analysis number"))
            rows.append(
                {
                    "review_id": review_id,
                    "analysis_group": analysis_group,
                    "analysis_number": analysis_number,
                    "analysis_key": f"{review_id}::{analysis_group}::{analysis_number}",
                    "source_file": str(path),
                    "row_index": index,
                    "raw": {str(key): _clean(value) for key, value in raw.items()},
                }
            )
    return rows


def _method_source(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "data_type": _clean(raw.get("Data type")),
        "effect_measure": _clean(raw.get("Effect measure")),
        "statistical_method": _clean(raw.get("Statistical method")),
        "analysis_model": _clean(raw.get("Analysis model")),
        "study_ci": _clean(raw.get("Study CI")),
        "estimate_ci": _clean(raw.get("Estimate CI")),
        "ci_pi_level": _clean(raw.get("CI/PI level")),
        "overall_estimates_enabled": _truthy(raw.get("Overall estimates")),
        "subgroup_estimates_enabled": _truthy(raw.get("Subgroup estimates")),
        "test_for_subgroup_differences": _truthy(raw.get("Test for subgroup differences")),
    }


def _study_row_source(rows: list[dict[str, Any]]) -> dict[str, Any]:
    study_ids = sorted({_clean(row["raw"].get("Study")) for row in rows if _clean(row["raw"].get("Study"))})
    subgroup_counts = Counter(_clean(row["raw"].get("Subgroup")) for row in rows if _clean(row["raw"].get("Subgroup")))
    footnotes = []
    footnote_rows = []
    for row in rows:
        note = _clean(row["raw"].get("Footnotes"))
        if note and note not in footnotes:
            footnotes.append(note)
        if note:
            footnote_rows.append(
                {
                    "study_id": _nullable(row["raw"].get("Study")),
                    "subgroup": _nullable(row["raw"].get("Subgroup")),
                    "applicability": _nullable(row["raw"].get("Applicability")),
                    "footnote": note,
                    "row_index": row["row_index"],
                }
            )
    applicability_counts = Counter(_clean(row["raw"].get("Applicability")) for row in rows if _clean(row["raw"].get("Applicability")))
    return {
        "eligible_study_ids": study_ids,
        "subgroup_labels": [
            {"label": label, "study_count": count}
            for label, count in sorted(subgroup_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "applicability_counts": dict(sorted(applicability_counts.items())),
        "footnotes": footnotes,
        "footnote_rows": footnote_rows,
        "row_count": len(rows),
    }


def _subgroup_estimate_source(overall_raw: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    levels = []
    for row in sorted(rows, key=lambda item: (_to_int_or_large(item["raw"].get("Subgroup number")), _clean(item["raw"].get("Subgroup")))):
        raw = row["raw"]
        levels.append(
            {
                "subgroup_number": _clean(raw.get("Subgroup number")),
                "label": _clean(raw.get("Subgroup")),
                "source_file": row["source_file"],
                "row_index": row["row_index"],
                "estimate": _estimate_fields(raw),
            }
        )
    return {
        "levels": levels,
        "difference_test": {
            "chi2": _nullable(overall_raw.get("Subgroup Chi²")),
            "df": _nullable(overall_raw.get("Subgroup df")),
            "p": _nullable(overall_raw.get("Subgroup P")),
            "i2": _nullable(overall_raw.get("Subgroup I²")),
        },
    }


def _estimate_fields(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "mean": _nullable(raw.get("Mean")),
        "ci_start": _nullable(raw.get("CI start")),
        "ci_end": _nullable(raw.get("CI end")),
        "experimental_n": _nullable(raw.get("Experimental N")),
        "control_n": _nullable(raw.get("Control N")),
        "experimental_cases": _nullable(raw.get("Experimental cases")),
        "control_cases": _nullable(raw.get("Control cases")),
        "heterogeneity_chi2": _nullable(raw.get("Heterogeneity Chi²")),
        "heterogeneity_df": _nullable(raw.get("Heterogeneity df")),
        "heterogeneity_p": _nullable(raw.get("Heterogeneity P")),
        "heterogeneity_i2": _nullable(raw.get("Heterogeneity I²")),
        "heterogeneity_tau2": _nullable(raw.get("Heterogeneity Tau²")),
    }


def _setting_warnings(*, comparison: dict[str, Any], outcome: dict[str, Any], method: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    comp = comparison.get("comparison") or {}
    out = outcome.get("outcome") or {}
    if not comp.get("experimental") or not comp.get("comparator"):
        warnings.append("missing_comparison_arm")
    if not out.get("outcome_concept"):
        warnings.append("missing_outcome_concept")
    if method.get("data_type") not in SUPPORTED_DATA_TYPES:
        warnings.append("unsupported_data_type")
    return warnings


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "yes", "1", "y"}


def _nullable(value: Any) -> str | None:
    text = _clean(value)
    if not text or text.lower() in {"null", "none", "#n/a", "not applicable", "not_applicable"}:
        return None
    return text


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("&gt;", ">").replace("&lt;", "<").split())


def _to_int_or_large(value: Any) -> int:
    try:
        return int(float(str(value or "").strip()))
    except ValueError:
        return 10**9
