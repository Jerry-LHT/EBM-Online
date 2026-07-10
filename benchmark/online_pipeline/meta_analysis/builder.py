"""Build Meta Analysis benchmark datasets from frozen official Cochrane CSVs."""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from benchmark.online_pipeline.meta_analysis.setting_cleaning.cache import (
    SETTING_CLEANING_VERSION,
    setting_has_valid_comparison_cache,
)
from benchmark.online_pipeline.meta_analysis.setting_cleaning.sources import (
    build_analysis_family_sources,
    build_field_candidates,
    normalize_analysis_model,
    normalize_official_rows,
    slug,
)
from benchmark.online_pipeline.shared.building import (
    DEFAULT_SEED,
    RAW_DATA_DIR,
    ROOT,
    select_records,
    sha256_file,
    sha256_json,
    source_manifest,
    stable_order,
)
from benchmark.online_pipeline.shared.jsonl import read_jsonl, write_jsonl
from benchmark.online_pipeline.shared.report_utils import write_json


MODULE = "meta_analysis"
SOURCE = "cochrane_meta_v2"
LEGACY_SOURCES = {"cochrane_meta_v1"}
BUILDER_VERSION = "online-pipeline-builder-v4-meta"
SMOKE_SIZE = 5
SUBTASK2_SMOKE_REGRESSION_SOURCE_IDS = (
    # Dichotomous semantic row alignment; source setting lacks the article row label.
    "meta-analysis::CD001431::11::2::subgroup::4",
    # Continuous outcome-measure ambiguity under a broad decisional-conflict setting.
    "meta-analysis::CD001431::4::6::subgroup::2",
    # Continuous complex table/timepoint/statistic selection.
    "meta-analysis::CD004376::4::6::subgroup::1",
    # Dichotomous timepoint and article-arm mapping.
    "meta-analysis::CD011381::1::4::subgroup::23",
    # Repeated targets for one study under the same setting; candidate recall is required.
    "meta-analysis::CD011769::14::5::subgroup::1",
)
UPSTREAM_DATA_PACKAGE = Path("sr-cleaned/code/external/cleaned-pico/data_package/zip")
CLEANED_ARTICLES_DIR = RAW_DATA_DIR / "cleaned_articles"
SUBTASK2_AUDIT_REGISTRY = RAW_DATA_DIR / "meta_analysis" / "intermediate" / "subtask2_audit_registry.jsonl"


def build_dataset(
    *,
    source: str,
    dataset_name: str,
    sample_size: int | None = None,
    seed: str = DEFAULT_SEED,
    source_url: str | None = None,
    allow_deterministic_fallback: bool = False,
    shared_settings_root: str | Path | None = None,
) -> dict[str, Any]:
    if source not in {SOURCE, *LEGACY_SOURCES}:
        raise ValueError(f"Unsupported meta_analysis source: {source}")
    raw_root = Path(source_url) if source_url else RAW_DATA_DIR / MODULE
    if not _raw_snapshot_exists(raw_root):
        freeze_raw_snapshot(raw_root=raw_root)
    raw_result = build_raw(
        raw_root=raw_root,
        allow_deterministic_fallback=allow_deterministic_fallback,
        shared_settings_root=shared_settings_root,
    )
    records, manifest, analysis = load_source(raw_root=raw_root, source=source)
    selected = select_records(records, sample_size=sample_size, seed=seed, module=MODULE)
    splits = build_splits(selected, seed=seed)
    dataset_result = write_dataset(
        dataset_name=dataset_name,
        records=selected,
        splits=splits,
        source=source,
        source_manifest_data=manifest,
        seed=seed,
        sample_size=sample_size,
        source_record_count=analysis["dataset_record_count"],
        dataset_analysis_data={**analysis, "raw_build": raw_result},
    )
    return {
        **dataset_result,
        "source_manifest": manifest,
    }


def freeze_raw_snapshot(*, raw_root: Path = RAW_DATA_DIR / MODULE) -> dict[str, Any]:
    """Freeze official analysis CSVs if they are available upstream.

    Existing snapshots are preserved. This avoids depending on old task_b files
    for the current benchmark source.
    """

    source_dir = raw_root / "source"
    official_dir = source_dir / "official_analysis_csv_snapshot"
    source_dir.mkdir(parents=True, exist_ok=True)
    official_dir.mkdir(parents=True, exist_ok=True)

    copied_files: list[str] = []
    missing_upstream = not UPSTREAM_DATA_PACKAGE.exists()
    if UPSTREAM_DATA_PACKAGE.exists():
        for review_dir in sorted(path for path in UPSTREAM_DATA_PACKAGE.iterdir() if path.is_dir()):
            review_id = review_dir.name
            analysis_dir = review_dir / "analysis-data"
            if not analysis_dir.exists():
                continue
            target_review_dir = official_dir / review_id
            target_review_dir.mkdir(parents=True, exist_ok=True)
            for suffix in ("data-rows", "overall-estimates-and-settings", "subgroup-estimates"):
                source_path = analysis_dir / f"{review_id}-{suffix}.csv"
                if source_path.exists():
                    target_path = target_review_dir / source_path.name
                    if not target_path.exists() or sha256_file(source_path) != sha256_file(target_path):
                        shutil.copy2(source_path, target_path)
                    copied_files.append(str(target_path.relative_to(raw_root)))

    review_ids = sorted(path.name for path in official_dir.iterdir() if path.is_dir()) if official_dir.exists() else []
    summary = {
        "source": SOURCE,
        "upstream_data_package": str(UPSTREAM_DATA_PACKAGE),
        "upstream_missing": missing_upstream,
        "review_count": len(review_ids),
        "copied_official_csv_count": len(copied_files),
        "note": "Frozen snapshot uses official Cochrane analysis CSVs only; XML is not re-cleaned and task_b is not a cleaning source.",
    }
    write_json(raw_root / "source_manifest.json", summary)
    return summary


def build_raw(
    *,
    raw_root: Path = RAW_DATA_DIR / MODULE,
    allow_deterministic_fallback: bool = False,
    shared_settings_root: str | Path | None = None,
) -> dict[str, Any]:
    source_dir = raw_root / "source"
    intermediate_dir = raw_root / "intermediate"
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    normalized = normalize_official_rows(source_dir / "official_analysis_csv_snapshot")
    settings_root = Path(shared_settings_root) if shared_settings_root else None
    if settings_root is not None and settings_root.exists() and (settings_root / "setting_cleaned.jsonl").exists():
        return _build_raw_from_shared_settings(raw_root=raw_root, normalized=normalized, settings_root=settings_root)
    all_families = build_analysis_family_sources(
        overall_rows=normalized["overall"],
        data_rows=normalized["data_rows"],
        subgroup_rows=normalized["subgroup_estimates"],
    )
    families = _load_linked_families(intermediate_dir=intermediate_dir, all_families=all_families)
    setting_families = _load_setting_families(
        intermediate_dir=intermediate_dir,
        families=families,
        allow_deterministic_fallback=allow_deterministic_fallback,
    )
    analysis_settings = _expand_analysis_settings(setting_families=setting_families, families=families)
    study_result_rows, binding_audit = _build_study_result_rows(
        official_data_rows=normalized["data_rows"],
        analysis_settings=analysis_settings,
    )
    analysis_settings = _attach_subgroup_scopes(analysis_settings=analysis_settings, study_result_rows=study_result_rows)
    analysis_methods = _build_analysis_methods(
        setting_families=setting_families,
        analysis_settings=analysis_settings,
        study_result_rows=study_result_rows,
    )
    overall_estimates = _build_overall_estimates(
        official_overall_rows=normalized["overall"],
        analysis_settings=analysis_settings,
        analysis_methods=analysis_methods,
        study_result_rows=study_result_rows,
    )
    subgroup_results = _build_subgroup_results(
        setting_families=setting_families,
        analysis_settings=analysis_settings,
        families=families,
        analysis_methods=analysis_methods,
        study_result_rows=study_result_rows,
    )
    records = _records_from_raw(
        analysis_settings=analysis_settings,
        study_result_rows=study_result_rows,
        analysis_methods=analysis_methods,
        overall_estimates=overall_estimates,
        subgroup_results=subgroup_results,
    )
    analysis = _raw_quality_report(
        normalized=normalized,
        families=families,
        setting_families=setting_families,
        analysis_settings=analysis_settings,
        study_result_rows=study_result_rows,
        analysis_methods=analysis_methods,
        overall_estimates=overall_estimates,
        subgroup_results=subgroup_results,
        records=records,
        binding_audit=binding_audit,
    )
    analysis["setting_source"] = _setting_cleaning_source_report(
        mode="meta_analysis_linked_article_required",
        source_path=intermediate_dir / "setting_cleaned.jsonl",
        linked_family_count=len(families),
        setting_family_count=len(setting_families),
    )

    write_jsonl(intermediate_dir / "official_overall_rows.jsonl", normalized["overall"], sort_keys=False)
    write_jsonl(intermediate_dir / "official_data_rows.jsonl", normalized["data_rows"], sort_keys=False)
    write_jsonl(intermediate_dir / "official_subgroup_estimate_rows.jsonl", normalized["subgroup_estimates"], sort_keys=False)
    write_jsonl(intermediate_dir / "analysis_family_sources.jsonl", families, sort_keys=False)
    write_jsonl(intermediate_dir / "analysis_settings.jsonl", analysis_settings, sort_keys=False)
    write_jsonl(intermediate_dir / "study_result_rows.jsonl", study_result_rows, sort_keys=False)
    write_jsonl(intermediate_dir / "analysis_methods.jsonl", analysis_methods, sort_keys=False)
    write_jsonl(intermediate_dir / "overall_estimates.jsonl", overall_estimates, sort_keys=False)
    write_jsonl(intermediate_dir / "subgroup_results.jsonl", subgroup_results, sort_keys=False)
    write_jsonl(intermediate_dir / "study_result_binding_audit.jsonl", binding_audit, sort_keys=False)
    write_jsonl(intermediate_dir / "05_dataset_records.jsonl", records, sort_keys=False)
    write_json(intermediate_dir / "raw_quality_report.json", analysis)
    write_jsonl(
        intermediate_dir / "raw_quality_preview.jsonl",
        stable_order(records, seed="42:meta_analysis:preview", module=MODULE)[: min(20, len(records))],
        sort_keys=False,
    )
    return analysis


def _build_raw_from_shared_settings(
    *,
    raw_root: Path,
    normalized: dict[str, list[dict[str, Any]]],
    settings_root: Path,
) -> dict[str, Any]:
    intermediate_dir = raw_root / "intermediate"
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    families = read_jsonl(settings_root / "family_sources.jsonl")
    setting_families = read_jsonl(settings_root / "setting_cleaned.jsonl")
    _validate_setting_families(setting_families=setting_families, families=families, source_path=settings_root / "setting_cleaned.jsonl")
    review_ids = {str(row["review_id"]) for row in families}
    normalized = {
        key: [row for row in rows if str(row.get("review_id")) in review_ids]
        for key, rows in normalized.items()
    }
    analysis_settings = _expand_analysis_settings(setting_families=setting_families, families=families)
    study_result_rows, binding_audit = _build_study_result_rows(
        official_data_rows=normalized["data_rows"],
        analysis_settings=analysis_settings,
    )
    analysis_settings = _attach_subgroup_scopes(analysis_settings=analysis_settings, study_result_rows=study_result_rows)
    analysis_methods = _build_analysis_methods(
        setting_families=setting_families,
        analysis_settings=analysis_settings,
        study_result_rows=study_result_rows,
    )
    overall_estimates = _build_overall_estimates(
        official_overall_rows=normalized["overall"],
        analysis_settings=analysis_settings,
        analysis_methods=analysis_methods,
        study_result_rows=study_result_rows,
    )
    subgroup_results = _build_subgroup_results(
        setting_families=setting_families,
        analysis_settings=analysis_settings,
        families=families,
        analysis_methods=analysis_methods,
        study_result_rows=study_result_rows,
    )
    records = _records_from_raw(
        analysis_settings=analysis_settings,
        study_result_rows=study_result_rows,
        analysis_methods=analysis_methods,
        overall_estimates=overall_estimates,
        subgroup_results=subgroup_results,
    )
    analysis = _raw_quality_report(
        normalized=normalized,
        families=families,
        setting_families=setting_families,
        analysis_settings=analysis_settings,
        study_result_rows=study_result_rows,
        analysis_methods=analysis_methods,
        overall_estimates=overall_estimates,
        subgroup_results=subgroup_results,
        records=records,
        binding_audit=binding_audit,
    )
    analysis["setting_source"] = {
        "mode": "shared_grade_required",
        "settings_root": str(settings_root),
        "full_family_filter": "grade_gold_reviews",
        "article_link_filter_applied_before_subtask_build": False,
        "setting_cleaning_version": SETTING_CLEANING_VERSION,
        "setting_family_count": len(setting_families),
        "setting_cleaned_sha256": sha256_file(settings_root / "setting_cleaned.jsonl"),
    }

    write_jsonl(intermediate_dir / "official_overall_rows.jsonl", normalized["overall"], sort_keys=False)
    write_jsonl(intermediate_dir / "official_data_rows.jsonl", normalized["data_rows"], sort_keys=False)
    write_jsonl(intermediate_dir / "official_subgroup_estimate_rows.jsonl", normalized["subgroup_estimates"], sort_keys=False)
    write_jsonl(intermediate_dir / "analysis_family_sources.jsonl", families, sort_keys=False)
    write_jsonl(intermediate_dir / "analysis_settings.jsonl", analysis_settings, sort_keys=False)
    write_jsonl(intermediate_dir / "study_result_rows.jsonl", study_result_rows, sort_keys=False)
    write_jsonl(intermediate_dir / "analysis_methods.jsonl", analysis_methods, sort_keys=False)
    write_jsonl(intermediate_dir / "overall_estimates.jsonl", overall_estimates, sort_keys=False)
    write_jsonl(intermediate_dir / "subgroup_results.jsonl", subgroup_results, sort_keys=False)
    write_jsonl(intermediate_dir / "study_result_binding_audit.jsonl", binding_audit, sort_keys=False)
    write_jsonl(intermediate_dir / "05_dataset_records.jsonl", records, sort_keys=False)
    write_json(intermediate_dir / "raw_quality_report.json", analysis)
    write_jsonl(
        intermediate_dir / "raw_quality_preview.jsonl",
        stable_order(records, seed="42:meta_analysis:preview", module=MODULE)[: min(20, len(records))],
        sort_keys=False,
    )
    return analysis


def load_source(*, raw_root: Path, source: str = SOURCE) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    records_path = raw_root / "intermediate" / "05_dataset_records.jsonl"
    if not records_path.exists():
        build_raw(raw_root=raw_root)
    records = read_jsonl(records_path)
    analysis = json.loads((raw_root / "intermediate" / "raw_quality_report.json").read_text(encoding="utf-8"))
    manifest = source_manifest(
        source=source,
        records=records,
        source_url=str(raw_root),
        raw_sha256=_raw_snapshot_sha256(raw_root),
        extra={
            "builder_version": BUILDER_VERSION,
            "loader": "official_cochrane_analysis_csv_llm_direct_setting_cleaning",
            "raw_root": str(raw_root),
            "source_manifest": str(raw_root / "source_manifest.json"),
            "family_count": analysis["family_count"],
            "analysis_setting_count": analysis["analysis_setting_count"],
            "study_result_row_count": analysis["study_result_row_count"],
            "overall_estimate_count": analysis["overall_estimate_count"],
            "subgroup_result_count": analysis["subgroup_result_count"],
        },
    )
    return records, manifest, analysis


def build_splits(records: list[dict[str, Any]], *, seed: str = DEFAULT_SEED) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str((record.get("strata") or {}).get("review_id") or "unknown")].append(record)
    review_ids = sorted(grouped)
    ordered_reviews = sorted(review_ids, key=lambda review_id: sha256_json({"seed": seed, "module": MODULE, "review_id": review_id}))
    dev_review_count = round(len(ordered_reviews) * 0.4)
    if len(ordered_reviews) > 1:
        dev_review_count = min(max(1, dev_review_count), len(ordered_reviews) - 1)
    dev_reviews = set(ordered_reviews[:dev_review_count])
    dev: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for review_id in review_ids:
        target = dev if review_id in dev_reviews else test
        target.extend(grouped[review_id])
    dev = sorted(dev, key=lambda record: record["source_id"])
    test = sorted(test, key=lambda record: record["source_id"])
    smoke = _smoke_records(dev or test, seed=seed)
    return {"smoke": sorted(smoke, key=lambda record: record["source_id"]), "dev": dev, "test": test}


def write_dataset(
    *,
    dataset_name: str,
    records: list[dict[str, Any]],
    splits: dict[str, list[dict[str, Any]]],
    source: str,
    source_manifest_data: dict[str, Any],
    seed: str,
    sample_size: int | None,
    source_record_count: int,
    dataset_analysis_data: dict[str, Any],
) -> None:
    article_bundle = _collect_shared_articles(records=records)
    subtask2_key_filter = _subtask2_key_filter_enabled(dataset_name)
    subtask2_pairwise_comparison_filter = _subtask2_pairwise_comparison_filter_enabled(dataset_name)
    subtask2_candidate_filter = _subtask2_candidate_filter_enabled(dataset_name)

    subtask_specs = _subtask_specs_for_dataset(dataset_name)
    subtask_counts: dict[str, dict[str, Any]] = {}
    dataset_dirs: dict[str, str] = {}
    for subtask_name, builder in subtask_specs.items():
        subtask_dir = ROOT / MODULE / subtask_name / "datasets" / dataset_name
        dataset_dirs[subtask_name] = str(subtask_dir)
        if subtask_dir.exists():
            shutil.rmtree(subtask_dir)
        subtask_dir.mkdir(parents=True, exist_ok=True)
        subtask_records = builder(
            records,
            article_bundle=article_bundle,
            subtask2_key_filter=subtask2_key_filter,
            subtask2_pairwise_comparison_filter=subtask2_pairwise_comparison_filter,
            subtask2_candidate_filter=subtask2_candidate_filter,
        )
        if subtask_name == "subtask2_study_results":
            _write_shared_articles(shared_dir=subtask_dir / "shared", article_bundle=article_bundle)
            _write_package_records(subtask_dir / "shared", subtask_records)
        else:
            _write_package_records(subtask_dir / "shared", subtask_records)
        _write_records(subtask_dir, subtask_records)
        split_counts: dict[str, int] = {"all": len(subtask_records)}
        for split_name, split_records in splits.items():
            split_source_ids = {record["source_id"] for record in split_records}
            subtask_split_records = [record for record in subtask_records if record["source_id"] in split_source_ids]
            if subtask_name == "subtask4_subgroup_analysis" and split_name == "smoke":
                subtask_split_records = _expand_subtask4_smoke_records(
                    split_records=subtask_split_records,
                    all_subtask_records=subtask_records,
                )
            if split_name == "smoke":
                subtask_split_records = _fill_subtask_smoke_records(
                    split_records=subtask_split_records,
                    all_subtask_records=subtask_records,
                    dev_records=splits.get("dev") or [],
                    seed=seed,
                    subtask_name=subtask_name,
                )
            _write_records(subtask_dir / "splits" / split_name, subtask_split_records)
            split_counts[split_name] = len(subtask_split_records)
        _write_subtask_schema(subtask_dir / "schema.md", subtask_name=subtask_name)
        _write_subtask_manifests(
            subtask_dir=subtask_dir,
            subtask_name=subtask_name,
            records=subtask_records,
            split_counts=split_counts,
            source=source,
            source_manifest_data=source_manifest_data,
            seed=seed,
            sample_size=sample_size,
            source_record_count=source_record_count,
            dataset_analysis_data=dataset_analysis_data,
        )
        subtask_counts[subtask_name] = {
            "split_counts": split_counts,
            "coverage": _subtask_manifest_coverage(subtask_name=subtask_name, records=subtask_records),
        }

    split_manifest = {
        "builder_version": BUILDER_VERSION,
        "seed": seed,
        "module": MODULE,
        "dataset_name": dataset_name,
        "source": source,
        "sample_size": sample_size,
        "source_record_count": source_record_count,
        "selected_count": len(records),
        "split_strategy": "seeded_review_level_dev40_test60_smoke5_from_dev",
        "subtasks": {
            subtask_name: {
                "count": info["split_counts"]["all"],
                "split_counts": {name: count for name, count in info["split_counts"].items() if name != "all"},
                "dataset_path": str(Path(subtask_name) / "datasets" / dataset_name),
                **info["coverage"],
            }
            for subtask_name, info in subtask_counts.items()
        },
        "splits": {
            split_name: {
                "count": len(split_records),
                "instance_ids": [record["instance"]["instance_id"] for record in split_records],
            }
            for split_name, split_records in {"all": records, **splits}.items()
        },
    }
    build_manifest = {
        "builder_version": BUILDER_VERSION,
        "module": MODULE,
        "dataset_name": dataset_name,
        "source": source,
        "sample_size": sample_size,
        "source_record_count": source_record_count,
        "selected_count": len(records),
        "seed": seed,
        "source_manifest_sha256": sha256_json(source_manifest_data),
        "split_manifest_sha256": sha256_json(split_manifest),
    }
    return {
        "dataset_dirs": dataset_dirs,
        "build_manifest": build_manifest,
        "split_manifest": split_manifest,
    }


def _load_setting_families(
    *,
    intermediate_dir: Path,
    families: list[dict[str, Any]],
    allow_deterministic_fallback: bool,
) -> list[dict[str, Any]]:
    cleaned_path = intermediate_dir / "setting_cleaned.jsonl"
    if cleaned_path.exists():
        cleaned = read_jsonl(cleaned_path)
        cleaned_by_id = {row["candidate_id"]: row for row in cleaned}
        if all(family["candidate_id"] in cleaned_by_id for family in families):
            setting_families = [cleaned_by_id[family["candidate_id"]] for family in families]
            _validate_setting_families(setting_families=setting_families, families=families, source_path=cleaned_path)
            return setting_families
    if allow_deterministic_fallback:
        fallback_path = intermediate_dir / "setting_adjudicated.deterministic_fallback.jsonl"
        if fallback_path.exists():
            fallback = read_jsonl(fallback_path)
            fallback_by_id = {row["candidate_id"]: row for row in fallback}
            if all(family["candidate_id"] in fallback_by_id for family in families):
                return [fallback_by_id[family["candidate_id"]] for family in families]
    raise FileNotFoundError(
        f"Missing full setting cleaning file: {cleaned_path}. "
        "Run `PYTHONPATH=backend/src python benchmark/online_pipeline/meta_analysis/setting_cleaning/cleaner.py full "
        "--workers 16 --resume --llm-config llm.local.json` first."
    )


def _validate_setting_families(*, setting_families: list[dict[str, Any]], families: list[dict[str, Any]], source_path: Path) -> None:
    candidates = build_field_candidates(families)["comparison"]
    candidate_lookup = {row["candidate_id"]: row for row in candidates}
    invalid = []
    for setting in setting_families:
        candidate_id = str(setting.get("candidate_id") or "")
        candidate = candidate_lookup.get(candidate_id)
        if candidate is None or not setting_has_valid_comparison_cache(setting, candidate):
            invalid.append(candidate_id or "<missing>")
            if len(invalid) >= 10:
                break
    if invalid:
        raise ValueError(
            f"Setting cleaning artifact is not {SETTING_CLEANING_VERSION}: {source_path}. "
            f"Invalid candidate examples: {', '.join(invalid)}. "
            "Run meta_analysis setting_cleaning/cleaner.py full without old cache reuse first."
        )


def _setting_cleaning_source_report(
    *,
    mode: str,
    source_path: Path,
    linked_family_count: int,
    setting_family_count: int,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "source_path": str(source_path),
        "setting_cleaning_version": SETTING_CLEANING_VERSION,
        "linked_family_count": linked_family_count,
        "setting_family_count": setting_family_count,
        "setting_cleaned_sha256": sha256_file(source_path),
    }


def _load_linked_families(*, intermediate_dir: Path, all_families: list[dict[str, Any]]) -> list[dict[str, Any]]:
    linked_path = intermediate_dir / "analysis_family_sources.linked.jsonl"
    if not linked_path.exists():
        raise FileNotFoundError(
            f"Missing linked family source file: {linked_path}. "
            "Run `PYTHONPATH=backend/src python benchmark/online_pipeline/meta_analysis/setting_cleaning/cleaner.py normalize` first."
        )
    linked = read_jsonl(linked_path)
    linked_by_id = {row["candidate_id"]: row for row in linked}
    all_by_id = {row["candidate_id"]: row for row in all_families}
    missing = sorted(candidate_id for candidate_id in linked_by_id if candidate_id not in all_by_id)
    if missing:
        raise ValueError(f"Linked family source contains {len(missing)} candidate_ids missing from normalized official rows")
    return [linked_by_id[row["candidate_id"]] for row in linked]


def _expand_analysis_settings(*, setting_families: list[dict[str, Any]], families: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family_sources = {row["candidate_id"]: row for row in families}
    settings: list[dict[str, Any]] = []
    for setting_family in setting_families:
        family = family_sources[setting_family["candidate_id"]]
        base = _analysis_setting_base(setting_family)
        overall = {
            **base,
            "setting_id": f"setting::{setting_family['review_id']}::{setting_family['analysis_group']}::{setting_family['analysis_number']}::overall",
            "subgroup": {"level": None, "subgroup_number": None, "source": "overall"},
            "subgroup_scope": {
                "has_official_subgroup_estimate": False,
                "joined_study_rows": False,
                "included_in_primary_eval": True,
                "exclusion_reason": None,
            },
        }
        settings.append(overall)
        levels = (family.get("subgroup_estimate_source") or {}).get("levels") or []
        for level in levels:
            label = level.get("label")
            if not label:
                continue
            subgroup_number = level.get("subgroup_number")
            settings.append(
                {
                    **base,
                    "setting_id": f"setting::{setting_family['review_id']}::{setting_family['analysis_group']}::{setting_family['analysis_number']}::subgroup::{slug(subgroup_number or label)}",
                    "subgroup": {
                        "level": label,
                        "subgroup_number": subgroup_number,
                        "source": "official_subgroup_estimates",
                    },
                    "subgroup_scope": {
                        "has_official_subgroup_estimate": True,
                        "joined_study_rows": False,
                        "included_in_primary_eval": False,
                        "exclusion_reason": "no_joined_study_rows",
                    },
                }
            )
    return sorted(settings, key=lambda row: row["setting_id"])


def _analysis_setting_base(setting_family: dict[str, Any]) -> dict[str, Any]:
    method = setting_family.get("method") or {}
    return {
        "setting_family_id": setting_family["setting_family_id"],
        "candidate_id": setting_family["candidate_id"],
        "review_id": setting_family["review_id"],
        "analysis_group": setting_family["analysis_group"],
        "analysis_number": setting_family["analysis_number"],
        "analysis_name": setting_family["analysis_name"],
        "analysis_group_name": setting_family["analysis_group_name"],
        "population_scope": setting_family.get("population_scope") or {"label": "review population", "source": "default_review_scope"},
        "comparison": {
            "experimental": (setting_family.get("comparison") or {}).get("experimental"),
            "comparator": (setting_family.get("comparison") or {}).get("comparator"),
            "text": _comparison_text(setting_family.get("comparison") or {}),
        },
        "outcome": {
            "label": (setting_family.get("outcome") or {}).get("outcome_concept"),
            "measure": (setting_family.get("outcome") or {}).get("outcome_measure"),
            "benefit_direction": (setting_family.get("outcome") or {}).get("benefit_direction"),
        },
        "timepoint": setting_family.get("timepoint") or {"label": None, "window": None},
        "data_type": method.get("data_type") or setting_family.get("data_type"),
        "effect_measure": method.get("effect_measure") or setting_family.get("effect_measure"),
        "eligible_study_ids": list(setting_family.get("eligible_study_ids") or []),
        "source_context": setting_family.get("source_context") or {},
        "scope_flags": setting_family.get("scope_flags") or {},
        "comparison_structure": setting_family.get("comparison_structure") or {},
        "setting_quality": setting_family.get("setting_quality") or {},
        "source": {
            "dataset": SOURCE,
            "official_analysis_key": f"{setting_family['review_id']}::{setting_family['analysis_group']}::{setting_family['analysis_number']}",
            "setting_cleaning": (setting_family.get("cleaning") or {}).get("method"),
        },
    }


def _build_study_result_rows(
    *,
    official_data_rows: list[dict[str, Any]],
    analysis_settings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    settings_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    subgroup_setting_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for setting in analysis_settings:
        settings_by_family[setting["setting_family_id"]].append(setting)
        subgroup = setting.get("subgroup") or {}
        if subgroup.get("source") == "official_subgroup_estimates" and subgroup.get("level"):
            subgroup_setting_by_key[(setting["setting_family_id"], _norm(subgroup.get("level")))] = setting
    families_with_official_subgroups = {family_id for family_id, _ in subgroup_setting_by_key}
    overall_by_family = {
        family_id: next(setting for setting in settings if (setting.get("subgroup") or {}).get("source") == "overall")
        for family_id, settings in settings_by_family.items()
    }

    rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for source_row in official_data_rows:
        raw = source_row["raw"]
        family_id = f"setting-family::{source_row['review_id']}::{source_row['analysis_group']}::{source_row['analysis_number']}"
        overall = overall_by_family.get(family_id)
        if not overall:
            audit.append({"analysis_key": source_row["analysis_key"], "row_index": source_row["row_index"], "status": "missing_overall_setting"})
            continue
        targets = []
        subgroup_label = raw.get("Subgroup")
        subgroup_setting = subgroup_setting_by_key.get((family_id, _norm(subgroup_label)))
        if subgroup_setting:
            targets.append(subgroup_setting)
        elif _norm(subgroup_label) and family_id in families_with_official_subgroups:
            audit.append(
                {
                    "analysis_key": source_row["analysis_key"],
                    "row_index": source_row["row_index"],
                    "status": "subgroup_label_unmatched",
                    "subgroup_label": subgroup_label,
                }
            )
        elif _norm(subgroup_label):
            audit.append(
                {
                    "analysis_key": source_row["analysis_key"],
                    "row_index": source_row["row_index"],
                    "status": "study_row_subgroup_without_official_subgroup_estimate",
                    "subgroup_label": subgroup_label,
                }
            )
        applicability = _norm(raw.get("Applicability"))
        should_join_overall = (
            "overall" in applicability
            or not family_id in families_with_official_subgroups
            or (not applicability and not _norm(subgroup_label))
        )
        if subgroup_setting and should_join_overall:
            audit.append(
                {
                    "analysis_key": source_row["analysis_key"],
                    "row_index": source_row["row_index"],
                    "status": "skipped_overall_due_to_subgroup_preference",
                    "subgroup_label": subgroup_label,
                    "applicability": raw.get("Applicability"),
                    "overall_setting_id": overall.get("setting_id"),
                    "subgroup_setting_id": subgroup_setting.get("setting_id"),
                }
            )
            should_join_overall = False
        if (
            should_join_overall
        ):
            targets.append(overall)
        for setting in targets:
            result_data = _result_data(raw, setting.get("data_type"))
            if result_data is None:
                audit.append({"analysis_key": source_row["analysis_key"], "row_index": source_row["row_index"], "status": "invalid_numeric_data"})
                continue
            rows.append(
                {
                    "row_id": f"row::{source_row['analysis_key']}::{source_row['row_index']}::{_slug_setting_tail(setting['setting_id'])}",
                    "setting_id": setting["setting_id"],
                    "study_id": raw.get("Study") or "",
                    "study_year": raw.get("Study year") or None,
                    "footnote": raw.get("Footnotes") or None,
                    "extraction_status": "extracted",
                    "data_type": setting.get("data_type"),
                    "comparison": {
                        "experimental_arm": (setting.get("comparison") or {}).get("experimental"),
                        "control_arm": (setting.get("comparison") or {}).get("comparator"),
                    },
                    "outcome": {
                        "label": (setting.get("outcome") or {}).get("label"),
                        "timepoint": (setting.get("timepoint") or {}).get("label"),
                    },
                    "subgroup": setting.get("subgroup") or {},
                    "result_data": result_data,
                    "source": {
                        "source_file": source_row["source_file"],
                        "row_index": source_row["row_index"],
                        "analysis_key": source_row["analysis_key"],
                    },
                }
            )
    return sorted(rows, key=lambda row: row["row_id"]), audit


def _attach_subgroup_scopes(*, analysis_settings: list[dict[str, Any]], study_result_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    row_count_by_setting = Counter(row["setting_id"] for row in study_result_rows)
    scoped = []
    for setting in analysis_settings:
        subgroup = setting.get("subgroup") or {}
        joined = row_count_by_setting.get(setting["setting_id"], 0) > 0
        has_official = subgroup.get("source") == "official_subgroup_estimates"
        if has_official:
            subgroup_scope = {
                "has_official_subgroup_estimate": True,
                "joined_study_rows": joined,
                "included_in_primary_eval": joined,
                "exclusion_reason": None if joined else "no_joined_study_rows",
            }
        else:
            subgroup_scope = {
                "has_official_subgroup_estimate": False,
                "joined_study_rows": joined,
                "included_in_primary_eval": True,
                "exclusion_reason": None,
            }
        scoped.append({**setting, "subgroup_scope": subgroup_scope})
    return scoped


def _build_analysis_methods(
    *,
    setting_families: list[dict[str, Any]],
    analysis_settings: list[dict[str, Any]],
    study_result_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    method_by_candidate = {row["candidate_id"]: row.get("method") or {} for row in setting_families}
    study_ids_by_setting, _ = _study_ids_and_participants_by_setting(study_result_rows)
    methods = []
    for setting in analysis_settings:
        method = method_by_candidate.get(setting["candidate_id"]) or {}
        methods.append(
            {
                "setting_id": setting["setting_id"],
                "method_id": f"method::{setting['setting_id']}",
                "effect_measure": method.get("effect_measure") or setting.get("effect_measure"),
                "analysis_model": normalize_analysis_model(method.get("analysis_model")),
                "statistical_method": method.get("statistical_method") or "",
                "ci_level": method.get("ci_level") or "95%",
                "subgroup_estimates_enabled": bool(method.get("subgroup_estimates_enabled")),
                "overall_estimates_enabled": bool(method.get("overall_estimates_enabled")),
                "test_for_subgroup_differences": bool(method.get("test_for_subgroup_differences")),
                "analysis_included_study_ids": sorted(study_ids_by_setting.get(setting["setting_id"], set())),
                "source": "official_overall_estimates_and_settings_csv",
            }
        )
    return sorted(methods, key=lambda row: row["setting_id"])


def _build_overall_estimates(
    *,
    official_overall_rows: list[dict[str, Any]],
    analysis_settings: list[dict[str, Any]],
    analysis_methods: list[dict[str, Any]],
    study_result_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    method_by_setting = {row["setting_id"]: row for row in analysis_methods}
    study_ids_by_setting, participant_count_by_setting = _study_ids_and_participants_by_setting(study_result_rows)
    overall_setting_by_key = {
        f"{setting['review_id']}::{setting['analysis_group']}::{setting['analysis_number']}": setting
        for setting in analysis_settings
        if (setting.get("subgroup") or {}).get("source") == "overall"
    }

    estimates = []
    for source_row in official_overall_rows:
        setting = overall_setting_by_key.get(source_row["analysis_key"])
        if not setting:
            continue
        raw = source_row["raw"]
        if not _has_official_overall_estimate(raw):
            continue
        method = method_by_setting.get(setting["setting_id"]) or {}
        estimates.append(
            {
                "overall_estimate_id": f"overall-estimate::{setting['setting_id']}",
                "setting_id": setting["setting_id"],
                "setting_family_id": setting["setting_family_id"],
                "method_id": method.get("method_id"),
                "candidate_id": setting["candidate_id"],
                "included_study_ids": sorted(study_ids_by_setting.get(setting["setting_id"], set())),
                "study_count": len(study_ids_by_setting.get(setting["setting_id"], set())),
                "participant_count": participant_count_by_setting.get(setting["setting_id"], 0),
                "data_type": setting.get("data_type"),
                "effect_measure": method.get("effect_measure") or setting.get("effect_measure"),
                "analysis_model": method.get("analysis_model"),
                "statistical_method": method.get("statistical_method"),
                "ci_level": method.get("ci_level"),
                "effect_value": _to_optional_float(raw.get("Mean")),
                "ci_lower": _to_optional_float(raw.get("CI start")),
                "ci_upper": _to_optional_float(raw.get("CI end")),
                "prediction_interval": {
                    "lower": _to_optional_float(raw.get("PI start")),
                    "upper": _to_optional_float(raw.get("PI end")),
                },
                "heterogeneity": {
                    "tau2": _to_optional_float(raw.get("Heterogeneity Tau²")),
                    "chi2": _to_optional_float(raw.get("Heterogeneity Chi²")),
                    "df": _to_optional_int(raw.get("Heterogeneity df")),
                    "p_value": _to_optional_float(raw.get("Heterogeneity P")),
                    "i2": _to_optional_float(raw.get("Heterogeneity I²")),
                },
                "effect_test": {
                    "z": _to_optional_float(raw.get("Effect Z")),
                    "p_value": _to_optional_float(raw.get("Effect P")),
                },
                "estimation_status": "reported_by_official_csv",
                "source_joined": bool(study_ids_by_setting.get(setting["setting_id"])),
                "source": {
                    "source_file": source_row["source_file"],
                    "row_index": source_row["row_index"],
                    "analysis_key": source_row["analysis_key"],
                },
            }
        )
    return sorted(estimates, key=lambda row: row["overall_estimate_id"])


def _build_subgroup_results(
    *,
    setting_families: list[dict[str, Any]],
    analysis_settings: list[dict[str, Any]],
    families: list[dict[str, Any]],
    analysis_methods: list[dict[str, Any]],
    study_result_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    family_sources = {row["candidate_id"]: row for row in families}
    settings_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for setting in analysis_settings:
        settings_by_family[setting["setting_family_id"]].append(setting)
    study_ids_by_setting, participant_count_by_setting = _study_ids_and_participants_by_setting(study_result_rows)
    method_by_setting = {row["setting_id"]: row for row in analysis_methods}
    results = []
    for setting_family in setting_families:
        family = family_sources[setting_family["candidate_id"]]
        levels = (family.get("subgroup_estimate_source") or {}).get("levels") or []
        if not levels:
            continue
        settings = settings_by_family.get(setting_family["setting_family_id"]) or []
        setting_by_number = {
            str((setting.get("subgroup") or {}).get("subgroup_number") or ""): setting
            for setting in settings
            if (setting.get("subgroup") or {}).get("source") == "official_subgroup_estimates"
        }
        setting_by_label = {
            _norm((setting.get("subgroup") or {}).get("level")): setting
            for setting in settings
            if (setting.get("subgroup") or {}).get("source") == "official_subgroup_estimates"
        }
        estimates = []
        for level in levels:
            setting = setting_by_number.get(str(level.get("subgroup_number") or ""))
            if not setting:
                setting = setting_by_label.get(_norm(level.get("label")))
            if not setting:
                continue
            estimate = level.get("estimate") or {}
            method = method_by_setting.get(setting["setting_id"]) or {}
            joined = bool(study_ids_by_setting.get(setting["setting_id"]))
            estimates.append(
                {
                    "subgroup_estimate_id": f"subgroup-estimate::{setting['setting_id']}",
                    "setting_id": setting["setting_id"],
                    "setting_family_id": setting["setting_family_id"],
                    "method_id": method.get("method_id"),
                    "candidate_id": setting["candidate_id"],
                    "subgroup": setting.get("subgroup") or {},
                    "included_study_ids": sorted(study_ids_by_setting.get(setting["setting_id"], set())),
                    "study_count": len(study_ids_by_setting.get(setting["setting_id"], set())),
                    "participant_count": participant_count_by_setting.get(setting["setting_id"], 0),
                    "data_type": setting.get("data_type"),
                    "effect_measure": method.get("effect_measure") or setting.get("effect_measure"),
                    "analysis_model": method.get("analysis_model"),
                    "statistical_method": method.get("statistical_method") or "",
                    "ci_level": method.get("ci_level") or "95%",
                    "estimation_status": "reported_by_official_csv",
                    "effect_value": _to_optional_float(estimate.get("mean")),
                    "ci_lower": _to_optional_float(estimate.get("ci_start")),
                    "ci_upper": _to_optional_float(estimate.get("ci_end")),
                    "heterogeneity": {
                        "tau2": _to_optional_float(estimate.get("heterogeneity_tau2")),
                        "chi2": _to_optional_float(estimate.get("heterogeneity_chi2")),
                        "df": _to_optional_int(estimate.get("heterogeneity_df")),
                        "p_value": _to_optional_float(estimate.get("heterogeneity_p")),
                        "i2": _to_optional_float(estimate.get("heterogeneity_i2")),
                    },
                    "source_joined": joined,
                    "subgroup_scope": setting.get("subgroup_scope") or {},
                }
            )
        difference = (family.get("subgroup_estimate_source") or {}).get("difference_test") or {}
        tests = []
        if estimates and any(difference.get(field) for field in ("chi2", "df", "p", "i2")):
            first_setting = setting_by_number.get(str(levels[0].get("subgroup_number") or "")) or (
                setting_by_label.get(_norm(levels[0].get("label"))) if levels else None
            )
            tests.append(
                {
                    "subgroup_difference_test_id": f"subgroup-difference::{setting_family['setting_family_id']}",
                    "candidate_id": setting_family["candidate_id"],
                    "setting_family_id": setting_family["setting_family_id"],
                    "comparison": (first_setting or {}).get("comparison") or {},
                    "outcome": (first_setting or {}).get("outcome") or {},
                    "timepoint": (first_setting or {}).get("timepoint") or {"label": None, "window": None},
                    "data_type": (first_setting or {}).get("data_type"),
                    "effect_measure": (first_setting or {}).get("effect_measure"),
                    "level_estimate_ids": [row["subgroup_estimate_id"] for row in estimates],
                    "test_status": "reported_by_official_csv",
                    "chi2": _to_optional_float(difference.get("chi2")),
                    "df": _to_optional_int(difference.get("df")),
                    "p_value": _to_optional_float(difference.get("p")),
                    "i2_between_subgroups": _to_optional_float(difference.get("i2")),
                }
            )
        results.append(
            {
                "setting_family_id": setting_family["setting_family_id"],
                "subgroup_estimates": estimates,
                "subgroup_difference_tests": tests,
            }
        )
    return sorted(results, key=lambda row: row["setting_family_id"])


def _records_from_raw(
    *,
    analysis_settings: list[dict[str, Any]],
    study_result_rows: list[dict[str, Any]],
    analysis_methods: list[dict[str, Any]],
    overall_estimates: list[dict[str, Any]],
    subgroup_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_setting: dict[str, list[dict[str, Any]]] = defaultdict(list)
    methods_by_setting: dict[str, list[dict[str, Any]]] = defaultdict(list)
    overall_by_setting: dict[str, list[dict[str, Any]]] = defaultdict(list)
    subgroup_by_family = {row["setting_family_id"]: row for row in subgroup_results}
    for row in study_result_rows:
        rows_by_setting[row["setting_id"]].append(row)
    for row in analysis_methods:
        methods_by_setting[row["setting_id"]].append(row)
    for row in overall_estimates:
        overall_by_setting[row["setting_id"]].append(row)
    records = []
    for setting in analysis_settings:
        instance_id = setting["setting_id"].replace("setting::", "meta-analysis::")
        family_subgroups = subgroup_by_family.get(setting["setting_family_id"]) or {"subgroup_estimates": [], "subgroup_difference_tests": []}
        related_subgroups = [row for row in family_subgroups.get("subgroup_estimates") or [] if row.get("setting_id") == setting["setting_id"]]
        related_tests = family_subgroups.get("subgroup_difference_tests") or []
        analysis_setting = _instance_setting(setting)
        gold = {
            "instance_id": instance_id,
            "review_id": setting["review_id"],
            "analysis_settings": [analysis_setting],
            "study_result_rows": sorted(rows_by_setting.get(setting["setting_id"]) or [], key=lambda row: row["row_id"]),
            "analysis_methods": methods_by_setting.get(setting["setting_id"]) or [],
            "overall_estimates": overall_by_setting.get(setting["setting_id"]) or [],
            "subgroup_results": {
                "subgroup_estimates": related_subgroups,
                "subgroup_difference_tests": related_tests if related_subgroups else [],
            },
            "source": setting["source"],
        }
        records.append(
            {
                "source_id": instance_id,
                "instance": {
                    "instance_id": instance_id,
                    "review_id": setting["review_id"],
                    "analysis_setting": analysis_setting,
                    "included_studies": setting.get("eligible_study_ids") or [],
                    "source_context": setting.get("source_context") or {},
                    "source_refs": setting["source"],
                },
                "gold": gold,
                "strata": {
                    "review_id": setting["review_id"],
                    "data_type": setting.get("data_type"),
                    "has_official_subgroup_estimate": bool((setting.get("subgroup_scope") or {}).get("has_official_subgroup_estimate")),
                    "has_subtask4_gold": bool(related_subgroups),
                    "has_subtask5_gold": bool(overall_by_setting.get(setting["setting_id"])),
                    "subgroup_in_primary_eval": bool((setting.get("subgroup_scope") or {}).get("included_in_primary_eval"))
                    and bool(related_subgroups),
                    "include_in_primary_eval": (setting.get("scope_flags") or {}).get("include_in_primary_eval"),
                    "data_shape": (setting.get("scope_flags") or {}).get("data_shape"),
                    "has_time_to_phrase": (setting.get("scope_flags") or {}).get("has_time_to_phrase"),
                    "has_survival_analysis_signal": (setting.get("scope_flags") or {}).get("has_survival_analysis_signal"),
                },
            }
        )
    return sorted(records, key=lambda row: row["source_id"])


def _instance_setting(setting: dict[str, Any]) -> dict[str, Any]:
    return {
        "setting_id": setting["setting_id"],
        "setting_family_id": setting["setting_family_id"],
        "candidate_id": setting["candidate_id"],
        "analysis_group": setting["analysis_group"],
        "analysis_number": setting["analysis_number"],
        "analysis_name": setting["analysis_name"],
        "analysis_group_name": setting["analysis_group_name"],
        "population_scope": setting.get("population_scope"),
        "comparison": setting.get("comparison"),
        "comparison_structure": setting.get("comparison_structure") or {},
        "outcome": setting.get("outcome"),
        "timepoint": setting.get("timepoint"),
        "subgroup": setting.get("subgroup"),
        "subgroup_scope": setting.get("subgroup_scope") or {},
        "data_type": setting.get("data_type"),
        "effect_measure": setting.get("effect_measure"),
        "eligible_study_ids": setting.get("eligible_study_ids") or [],
        "source_context": setting.get("source_context") or {},
        "scope_flags": setting.get("scope_flags") or {},
        "setting_quality": setting.get("setting_quality") or {},
    }


def _raw_quality_report(
    *,
    normalized: dict[str, list[dict[str, Any]]],
    families: list[dict[str, Any]],
    setting_families: list[dict[str, Any]],
    analysis_settings: list[dict[str, Any]],
    study_result_rows: list[dict[str, Any]],
    analysis_methods: list[dict[str, Any]],
    overall_estimates: list[dict[str, Any]],
    subgroup_results: list[dict[str, Any]],
    records: list[dict[str, Any]],
    binding_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    overall_estimate_joined_count = sum(1 for row in overall_estimates if row.get("source_joined"))
    subgroup_estimate_count = sum(len(row.get("subgroup_estimates") or []) for row in subgroup_results)
    subgroup_setting_count = sum(1 for setting in analysis_settings if (setting.get("subgroup") or {}).get("source") == "official_subgroup_estimates")
    subgroup_estimate_joined_count = sum(
        1
        for row in subgroup_results
        for estimate in row.get("subgroup_estimates") or []
        if estimate.get("source_joined")
    )
    subgroup_data_row_unmatched_count = sum(1 for row in binding_audit if row.get("status") == "subgroup_label_unmatched")
    subgroup_preferred_overall_skip_count = sum(
        1 for row in binding_audit if row.get("status") == "skipped_overall_due_to_subgroup_preference"
    )
    return {
        "source": SOURCE,
        "study_result_row_policy": "canonical_source_row_assignment; subgroup rows are preferred over duplicated overall rows when official Applicability is SUBGROUP_AND_OVERALL",
        "official_overall_row_count": len(normalized["overall"]),
        "official_data_row_count": len(normalized["data_rows"]),
        "official_subgroup_estimate_row_count": len(normalized["subgroup_estimates"]),
        "family_count": len(families),
        "setting_family_count": len(setting_families),
        "analysis_setting_count": len(analysis_settings),
        "study_result_row_count": len(study_result_rows),
        "analysis_method_count": len(analysis_methods),
        "overall_estimate_count": len(overall_estimates),
        "overall_estimate_joined_count": overall_estimate_joined_count,
        "overall_estimate_unjoined_count": len(overall_estimates) - overall_estimate_joined_count,
        "subgroup_result_count": len(subgroup_results),
        "subgroup_setting_count": subgroup_setting_count,
        "subgroup_estimate_count": subgroup_estimate_count,
        "subgroup_estimate_joined_count": subgroup_estimate_joined_count,
        "subgroup_estimate_unjoined_count": subgroup_estimate_count - subgroup_estimate_joined_count,
        "subgroup_data_row_unmatched_count": subgroup_data_row_unmatched_count,
        "subgroup_preferred_overall_skip_count": subgroup_preferred_overall_skip_count,
        "dataset_record_count": len(records),
        "binding_audit_count": len(binding_audit),
        "data_type_counts": dict(sorted(Counter(setting.get("data_type") for setting in analysis_settings).items())),
        "setting_size_counts": dict(sorted(Counter(len(record["gold"]["study_result_rows"]) for record in records).items())),
        "review_counts": dict(sorted(Counter(record["instance"]["review_id"] for record in records).items())),
    }


def _comparison_text(comparison: dict[str, Any]) -> str:
    experimental = comparison.get("experimental")
    comparator = comparison.get("comparator")
    if experimental and comparator:
        return f"{experimental} versus {comparator}"
    return ""


def _result_data(raw: dict[str, Any], data_type: str | None) -> dict[str, Any] | None:
    try:
        if data_type == "Dichotomous":
            return {
                "experimental_events": _to_int(raw.get("Experimental cases")),
                "experimental_total": _to_int(raw.get("Experimental N")),
                "control_events": _to_int(raw.get("Control cases")),
                "control_total": _to_int(raw.get("Control N")),
            }
        if data_type == "Continuous":
            return {
                "experimental_mean": _to_float(raw.get("Experimental mean")),
                "experimental_sd": _to_float(raw.get("Experimental SD")),
                "experimental_total": _to_int(raw.get("Experimental N")),
                "control_mean": _to_float(raw.get("Control mean")),
                "control_sd": _to_float(raw.get("Control SD")),
                "control_total": _to_int(raw.get("Control N")),
            }
    except ValueError:
        return None
    return None


def _smoke_records(records: list[dict[str, Any]], *, seed: str) -> list[dict[str, Any]]:
    ordered = stable_order(records, seed=f"{seed}:{MODULE}:smoke", module=MODULE)
    selected: list[dict[str, Any]] = []
    for predicate in (
        lambda row: (row.get("strata") or {}).get("subgroup_in_primary_eval") and (row.get("strata") or {}).get("data_type") == "Dichotomous",
        lambda row: (row.get("strata") or {}).get("data_type") == "Continuous",
        lambda row: (row.get("strata") or {}).get("data_type") == "Dichotomous",
    ):
        for record in ordered:
            if predicate(record) and record["source_id"] not in {item["source_id"] for item in selected}:
                selected.append(record)
                break
    for record in ordered:
        if len(selected) >= min(SMOKE_SIZE, len(records)):
            break
        if record["source_id"] not in {item["source_id"] for item in selected}:
            selected.append(record)
    return selected[: min(SMOKE_SIZE, len(records))]


def _expand_subtask4_smoke_records(
    *,
    split_records: list[dict[str, Any]],
    all_subtask_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    family_ids = {
        str((record.get("instance") or {}).get("analysis_setting", {}).get("setting_family_id") or "")
        for record in split_records
    }
    if not family_ids:
        return split_records
    expanded = [
        record
        for record in all_subtask_records
        if str((record.get("instance") or {}).get("analysis_setting", {}).get("setting_family_id") or "") in family_ids
    ]
    return sorted(expanded, key=lambda record: record["source_id"])


def _fill_subtask_smoke_records(
    *,
    split_records: list[dict[str, Any]],
    all_subtask_records: list[dict[str, Any]],
    dev_records: list[dict[str, Any]],
    seed: str,
    subtask_name: str,
) -> list[dict[str, Any]]:
    if len(split_records) >= min(SMOKE_SIZE, len(all_subtask_records)):
        if subtask_name != "subtask2_study_results":
            return sorted(split_records, key=lambda record: record["source_id"])
        selected = {record["source_id"]: record for record in split_records}
    else:
        selected = {record["source_id"]: record for record in split_records}
    if subtask_name == "subtask2_study_results":
        records_by_id = {record["source_id"]: record for record in all_subtask_records}
        for source_id in SUBTASK2_SMOKE_REGRESSION_SOURCE_IDS:
            record = records_by_id.get(source_id)
            if record is not None:
                selected[source_id] = record
        if len(selected) >= min(SMOKE_SIZE, len(all_subtask_records)):
            ordered_selected = sorted(selected.values(), key=lambda record: record["source_id"])
            regression_ids = set(SUBTASK2_SMOKE_REGRESSION_SOURCE_IDS)
            required = [record for record in ordered_selected if record["source_id"] in regression_ids]
            optional = [record for record in ordered_selected if record["source_id"] not in regression_ids]
            return sorted((required + optional)[: min(SMOKE_SIZE, len(all_subtask_records))], key=lambda record: record["source_id"])
    dev_source_ids = {record["source_id"] for record in dev_records}
    dev_candidates = [record for record in all_subtask_records if record["source_id"] in dev_source_ids]
    fallback_candidates = dev_candidates or all_subtask_records
    ordered = stable_order(fallback_candidates, seed=f"{seed}:{MODULE}:{subtask_name}:smoke", module=MODULE)
    for record in ordered:
        if len(selected) >= min(SMOKE_SIZE, len(all_subtask_records)):
            break
        selected.setdefault(record["source_id"], record)
    return sorted(selected.values(), key=lambda record: record["source_id"])


def _subtask_manifest_coverage(*, subtask_name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    if subtask_name != "subtask2_study_results":
        return {}
    primary_eval_count = 0
    linked_article_total = 0
    linked_gold_row_total = 0
    excluded_missing_article_row_total = 0
    status_counts: Counter[str] = Counter()
    source_support_status_counts: Counter[str] = Counter()
    missing_study_total = 0
    for record in records:
        coverage = ((record.get("instance") or {}).get("article_coverage") or {})
        if coverage.get("primary_eval_eligible"):
            primary_eval_count += 1
        linked_article_total += int(coverage.get("linked_article_count") or 0)
        linked_gold_row_total += int(coverage.get("linked_gold_row_count") or 0)
        excluded_missing_article_row_total += int(coverage.get("excluded_missing_article_gold_row_count") or 0)
        status_counts[str(coverage.get("coverage_status") or "unknown")] += 1
        for status, count in (coverage.get("source_support_status_counts") or {}).items():
            source_support_status_counts[str(status)] += int(count or 0)
        missing_study_total += len(coverage.get("missing_study_ids") or [])
    return {
        "primary_eval_count": primary_eval_count,
        "linked_article_count": linked_article_total,
        "linked_gold_row_count": linked_gold_row_total,
        "excluded_missing_article_gold_row_count": excluded_missing_article_row_total,
        "missing_article_study_count": missing_study_total,
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "source_support_status_counts": dict(sorted(source_support_status_counts.items())),
    }


def _write_package_records(directory: Path, records: list[dict[str, Any]]) -> None:
    write_jsonl(directory / "package_records.jsonl", records, sort_keys=False)


def _collect_shared_articles(*, records: list[dict[str, Any]]) -> dict[str, Any]:
    study_ids: set[str] = set()
    for record in records:
        instance = record.get("instance") or {}
        for study_id in instance.get("included_studies") or []:
            if study_id:
                study_ids.add(str(study_id))
        for row in (record.get("gold") or {}).get("study_result_rows") or []:
            if row.get("study_id"):
                study_ids.add(str(row["study_id"]))

    article_rows: list[dict[str, Any]] = []
    article_ids_by_study_id: dict[str, list[str]] = defaultdict(list)
    source_paths: dict[str, str] = {}
    if CLEANED_ARTICLES_DIR.exists():
        for source_path in sorted(CLEANED_ARTICLES_DIR.glob("*.json")):
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            study_id = payload.get("study_id")
            article_id = payload.get("article_id")
            if not study_id or not article_id or str(study_id) not in study_ids:
                continue
            source_paths[source_path.name] = str(source_path)
            article_ids_by_study_id[str(study_id)].append(str(article_id))
            article_rows.append(
                {
                    "article_id": str(article_id),
                    "study_id": str(study_id),
                    "relative_path": str(Path("shared") / "articles" / source_path.name),
                    "source": payload.get("source") or "cleaned_articles",
                    "table_count": len(payload.get("tables") or []),
                    "has_xml_content": bool(payload.get("xml_content")),
                }
            )
    return {
        "article_index": sorted(article_rows, key=lambda row: (row["study_id"], row["article_id"])),
        "article_ids_by_study_id": {study_id: sorted(article_ids) for study_id, article_ids in article_ids_by_study_id.items()},
        "source_paths": source_paths,
    }


def _write_shared_articles(*, shared_dir: Path, article_bundle: dict[str, Any]) -> None:
    article_index_path = shared_dir / "article_index.jsonl"
    articles_dir = shared_dir / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)
    for name, source_path in (article_bundle.get("source_paths") or {}).items():
        shutil.copy2(Path(source_path), articles_dir / name)
    write_jsonl(article_index_path, article_bundle.get("article_index") or [], sort_keys=False)


def _write_records(directory: Path, records: list[dict[str, Any]]) -> None:
    write_jsonl(directory / "instances.jsonl", [record["instance"] for record in records], sort_keys=False)
    write_jsonl(directory / "gold.jsonl", [record["gold"] for record in records], sort_keys=False)


def _write_subtask_schema(path: Path, *, subtask_name: str) -> None:
    descriptions = {
        "subtask2_study_results": (
            "# meta_analysis subtask2 dataset\n\n"
            "Files:\n"
            "- `instances.jsonl`\n"
            "  - `instance_id`: stable instance key derived from one `AnalysisSetting`\n"
            "  - `review_id`: Cochrane review ID\n"
            "  - `analysis_setting`: cleaned setting definition with\n"
            "    - `setting_id`, `setting_family_id`, `candidate_id`\n"
            "    - `analysis_group`, `analysis_number`, `analysis_name`, `analysis_group_name`\n"
            "    - `population_scope`, `comparison`, `comparison_structure`\n"
            "    - `outcome`, `timepoint`, `subgroup`, `subgroup_scope`\n"
            "    - `data_type`, `effect_measure`\n"
            "    - `eligible_study_ids`, optional `eligible_study_candidates`, `source_context`, `scope_flags`, `setting_quality`\n"
            "    - `eligible_study_candidates[]`, when present, contains `study_id`, optional `article_id`, and either\n"
            "      `extraction_task_id` for candidate-set datasets or legacy `extraction_targets[]` with `target_id`\n"
            "    - candidate-set datasets may include `extraction_hint_parts`, a benchmark-side non-numeric context object\n"
            "      that adapters can convert to workflow `extraction_hint` using an explicit hint policy\n"
            "  - `included_studies`: eligible study IDs for this setting instance\n"
            "  - `article_ids`: article IDs available in `../shared/article_index.jsonl`\n"
            "  - `article_study_links`: `study_id -> article_id` links for this instance\n"
            "  - `article_coverage`: coverage summary with eligible count, linked count, missing study IDs,\n"
            "    linked gold row count, excluded missing-article gold row count, and `coverage_status`\n"
            "  - `source_context`: auxiliary context such as study-row footnotes\n"
            "    - current v1 records may use this as a compatibility source for target-level non-numeric extraction hints\n"
            "  - `source_refs`: source provenance including official analysis key\n"
            "- shared article layer\n"
            "  - `../shared/article_index.jsonl`: `article_id`, `study_id`, `relative_path`, `source`, `table_count`, `has_xml_content`\n"
            "  - `../shared/articles/*.json`: cleaned article payloads consumed by Subtask 2 methods\n"
            "- dataset variants\n"
            "  - `*-key-filter`: keeps rows whose required gold numeric values are directly present in the current article inputs\n"
            "  - `*-pairwise-comparison-filter`: Subtask-2-only legacy target-slot dataset; additionally keeps only settings with explicit pairwise setting-level comparison from `analysis_group_name`, non-empty experimental/comparator labels, and rows whose subgroup label does not introduce another pairwise comparison\n"
            "  - `*-candidate-filter`: Subtask-2-only candidate-set dataset; groups official rows by setting-study and evaluates `candidate_results[]` with set-level matching\n"
            "- `gold.jsonl`\n"
            "  - `instance_id`, `review_id`, `source`\n"
            "  - `study_result_rows`: canonical official study rows whose `study_id` has at least one linked article; when the same official row is both subgroup and overall, the subgroup assignment is preferred; each row contains\n"
            "    - `row_id`, `setting_id`, `study_id`, `study_year`, `footnote`\n"
            "    - `extraction_status`, `data_type`\n"
            "    - `comparison`, `outcome`, `subgroup`\n"
            "    - `result_data`\n"
            "    - optional benchmark-side audit fields: `review_label`, `audit_note`\n"
            "  - `study_result_candidate_sets` when present: one gold candidate set per setting-study extraction task, with `gold_candidate_results[]`\n"
            "    - optional benchmark-side audit fields: `review_label`, `audit_note`\n"
            "    - `source`\n"
        ),
        "subtask3_analysis_methods": (
            "# meta_analysis subtask3 dataset\n\n"
            "Files:\n"
            "- `instances.jsonl`\n"
            "  - same top-level input shape as Subtask 2:\n"
            "    - `instance_id`, `review_id`, `analysis_setting`, `included_studies`, `source_context`, `source_refs`\n"
            "- `gold.jsonl`\n"
            "  - `instance_id`, `review_id`, `source`\n"
            "  - `analysis_methods`: list containing the official method record for this setting\n"
            "    - `setting_id`, `method_id`\n"
            "    - `effect_measure`, `analysis_model`, `statistical_method`, `ci_level`\n"
            "    - `overall_estimates_enabled`, `subgroup_estimates_enabled`, `test_for_subgroup_differences`\n"
            "    - `analysis_included_study_ids`\n"
            "    - `source`\n"
        ),
        "subtask4_subgroup_analysis": (
            "# meta_analysis subtask4 dataset\n\n"
            "Files:\n"
            "- `instances.jsonl`\n"
            "  - `instance_id`, `review_id`\n"
            "  - `analysis_setting`\n"
            "  - `study_result_rows`: canonical official study rows for this setting; duplicated overall/subgroup source rows keep the subgroup assignment\n"
            "  - `analysis_methods`: official method record for this setting\n"
            "  - `included_studies`, `source_context`, `source_refs`\n"
            "- `gold.jsonl`\n"
            "  - `instance_id`, `review_id`, `source`\n"
            "  - `subgroup_results`\n"
            "    - `subgroup_estimates`: list of official subgroup pooled estimates for this setting\n"
            "      - `subgroup_estimate_id`, `setting_id`, `setting_family_id`, `method_id`, `candidate_id`\n"
            "      - `subgroup`, `included_study_ids`, `study_count`, `participant_count`\n"
            "      - `data_type`, `effect_measure`, `analysis_model`, `statistical_method`, `ci_level`\n"
            "      - `effect_value`, `ci_lower`, `ci_upper`, `heterogeneity`, `estimation_status`, `source_joined`, `source`\n"
            "    - `subgroup_difference_tests`: family-level official subgroup-difference tests carried with this setting when subgroup gold exists\n"
            "      - `subgroup_difference_test_id`, `candidate_id`, `setting_family_id`\n"
            "      - `comparison`, `outcome`, `timepoint`, `data_type`, `effect_measure`\n"
            "      - `level_estimate_ids`, `chi2`, `df`, `p_value`, `i2_between_subgroups`, `test_status`\n"
        ),
        "subtask5_overall_estimates": (
            "# meta_analysis subtask5 dataset\n\n"
            "Files:\n"
            "- `instances.jsonl`\n"
            "  - `instance_id`, `review_id`\n"
            "  - `analysis_setting`\n"
            "  - `study_result_rows`: canonical official study rows for this setting; duplicated overall/subgroup source rows keep the subgroup assignment\n"
            "  - `analysis_methods`: official method record for this setting\n"
            "  - `included_studies`, `source_context`, `source_refs`\n"
            "- `gold.jsonl`\n"
            "  - `instance_id`, `review_id`, `source`\n"
            "  - `overall_estimates`: list of official overall pooled estimates for this setting\n"
            "    - `overall_estimate_id`, `setting_id`, `setting_family_id`, `method_id`, `candidate_id`\n"
            "    - `included_study_ids`, `study_count`, `participant_count`\n"
            "    - `data_type`, `effect_measure`, `analysis_model`, `statistical_method`, `ci_level`\n"
            "    - `effect_value`, `ci_lower`, `ci_upper`\n"
            "    - `prediction_interval`, `heterogeneity`, `effect_test`\n"
            "    - `estimation_status`, `source_joined`, `source`\n"
        ),
    }
    path.write_text(descriptions[subtask_name], encoding="utf-8")


def _write_package_schema(path: Path) -> None:
    path.write_text(
        "# meta_analysis package dataset\n\n"
        "Files:\n"
        "- `instances.jsonl`\n"
        "  - `instance_id`, `review_id`\n"
        "  - `analysis_setting`: full cleaned setting definition\n"
        "  - `included_studies`\n"
        "  - `source_context`\n"
        "  - `source_refs`\n"
        "- `gold.jsonl`\n"
        "  - `instance_id`, `review_id`, `source`\n"
        "  - `analysis_settings`: single-item list containing the same setting definition used by the module package\n"
        "  - `study_result_rows`: official study-level joined rows\n"
        "  - `analysis_methods`: official method row(s) for the setting\n"
        "  - `overall_estimates`: official overall pooled estimate row(s) for the setting\n"
        "  - `subgroup_results`\n"
        "    - `subgroup_estimates`\n"
        "    - `subgroup_difference_tests`\n",
        encoding="utf-8",
    )


def _write_subtask_manifests(
    *,
    subtask_dir: Path,
    subtask_name: str,
    records: list[dict[str, Any]],
    split_counts: dict[str, int],
    source: str,
    source_manifest_data: dict[str, Any],
    seed: str,
    sample_size: int | None,
    source_record_count: int,
    dataset_analysis_data: dict[str, Any],
) -> None:
    split_manifest = {
        "builder_version": BUILDER_VERSION,
        "seed": seed,
        "module": MODULE,
        "subtask": subtask_name,
        "dataset_name": subtask_dir.name,
        "source": source,
        "sample_size": sample_size,
        "source_record_count": source_record_count,
        "selected_count": len(records),
        "split_strategy": "seeded_review_level_dev40_test60_smoke5_from_dev",
        "split_counts": split_counts,
        "splits": {
            split_name: {
                "count": split_counts.get(split_name, 0),
            }
            for split_name in ("all", "smoke", "dev", "test")
        },
    }
    build_manifest = {
        "builder_version": BUILDER_VERSION,
        "module": MODULE,
        "subtask": subtask_name,
        "dataset_name": subtask_dir.name,
        "source": source,
        "sample_size": sample_size,
        "source_record_count": source_record_count,
        "selected_count": len(records),
        "seed": seed,
        "source_manifest_sha256": sha256_json(source_manifest_data),
        "split_manifest_sha256": sha256_json(split_manifest),
    }
    write_json(subtask_dir / "source_manifest.json", source_manifest_data)
    write_json(subtask_dir / "split_manifest.json", split_manifest)
    write_json(subtask_dir / "build_manifest.json", build_manifest)
    write_json(subtask_dir / "dataset_analysis.json", dataset_analysis_data)


def _raw_snapshot_exists(raw_root: Path) -> bool:
    official_dir = raw_root / "source" / "official_analysis_csv_snapshot"
    return official_dir.is_dir() and any(official_dir.glob("*/*-overall-estimates-and-settings.csv"))


def _raw_snapshot_sha256(raw_root: Path) -> str:
    values = []
    for path in sorted((raw_root / "source" / "official_analysis_csv_snapshot").rglob("*")):
        if path.is_file():
            values.append((str(path.relative_to(raw_root)), sha256_file(path)))
    return sha256_json(values)


def _slug_setting_tail(setting_id: str) -> str:
    return slug(setting_id.split("::", 4)[-1])


def _study_ids_and_participants_by_setting(study_result_rows: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, int]]:
    study_ids_by_setting: dict[str, set[str]] = defaultdict(set)
    participant_count_by_setting: dict[str, int] = defaultdict(int)
    for row in study_result_rows:
        setting_id = row["setting_id"]
        if row.get("study_id"):
            study_ids_by_setting[setting_id].add(str(row["study_id"]))
        data = row.get("result_data") or {}
        participant_count_by_setting[setting_id] += int(data.get("experimental_total") or 0)
        participant_count_by_setting[setting_id] += int(data.get("control_total") or 0)
    return study_ids_by_setting, participant_count_by_setting


def _subtask_specs() -> dict[str, Any]:
    return {
        "subtask2_study_results": _build_subtask2_records,
        "subtask3_analysis_methods": _build_subtask3_records,
        "subtask4_subgroup_analysis": _build_subtask4_records,
        "subtask5_overall_estimates": _build_subtask5_records,
    }


def _subtask_specs_for_dataset(dataset_name: str) -> dict[str, Any]:
    if _subtask2_pairwise_comparison_filter_enabled(dataset_name) or _subtask2_candidate_filter_enabled(dataset_name):
        return {"subtask2_study_results": _build_subtask2_records}
    return _subtask_specs()


def _build_subtask2_records(
    records: list[dict[str, Any]],
    *,
    article_bundle: dict[str, Any],
    subtask2_key_filter: bool = False,
    subtask2_pairwise_comparison_filter: bool = False,
    subtask2_candidate_filter: bool = False,
) -> list[dict[str, Any]]:
    subtask_records: list[dict[str, Any]] = []
    article_ids_by_study_id = article_bundle.get("article_ids_by_study_id") or {}
    audit_registry = _load_subtask2_audit_registry()
    source_support_enabled = subtask2_key_filter or subtask2_pairwise_comparison_filter or subtask2_candidate_filter
    article_text_by_id = _article_text_by_id(article_bundle=article_bundle) if source_support_enabled else {}
    article_table_count_by_id = _article_table_count_by_id(article_bundle=article_bundle) if source_support_enabled else {}
    for record in records:
        gold = record["gold"]
        study_result_rows = gold.get("study_result_rows") or []
        if not study_result_rows:
            continue
        instance = record["instance"]
        if (subtask2_pairwise_comparison_filter or subtask2_candidate_filter) and not _subtask2_setting_has_high_quality_pairwise_comparison(instance.get("analysis_setting") or {}):
            continue
        included_studies = [str(study_id) for study_id in (instance.get("included_studies") or []) if study_id]
        gold_study_ids = sorted({str(row.get("study_id") or "") for row in study_result_rows if row.get("study_id")})
        article_study_links = []
        seen_article_ids: set[str] = set()
        linked_study_ids: set[str] = set()
        for study_id in included_studies:
            for article_id in article_ids_by_study_id.get(study_id, []):
                article_study_links.append({"study_id": study_id, "article_id": article_id})
                seen_article_ids.add(article_id)
                linked_study_ids.add(study_id)
        linked_study_result_rows = [
            row for row in study_result_rows if str(row.get("study_id") or "") in linked_study_ids
        ]
        if not linked_study_result_rows:
            continue
        source_support = _subtask2_source_support(
            rows=linked_study_result_rows,
            article_ids_by_study_id=article_ids_by_study_id,
            article_text_by_id=article_text_by_id,
            article_table_count_by_id=article_table_count_by_id,
            enabled=source_support_enabled,
        )
        if subtask2_key_filter:
            linked_study_result_rows = [
                row
                for row in linked_study_result_rows
                if source_support["row_support"].get(str(row.get("row_id") or ""), {}).get("include_in_primary_eval")
            ]
        if subtask2_pairwise_comparison_filter or subtask2_candidate_filter:
            linked_study_result_rows = [
                row
                for row in linked_study_result_rows
                if _subtask2_row_has_high_quality_pairwise_comparison(row)
                and source_support["row_support"].get(str(row.get("row_id") or ""), {}).get("include_in_primary_eval")
            ]
            source_support = _subtask2_filter_source_support(source_support=source_support, rows=linked_study_result_rows)
            linked_study_ids = {str(row.get("study_id") or "") for row in linked_study_result_rows if row.get("study_id")}
            seen_article_ids = {
                article_id
                for study_id in linked_study_ids
                for article_id in article_ids_by_study_id.get(study_id, [])
            }
            article_study_links = [
                link
                for link in article_study_links
                if str(link.get("study_id") or "") in linked_study_ids
            ]
        if not linked_study_result_rows:
            continue
        analysis_setting = {
            **instance["analysis_setting"],
            "eligible_study_candidates": _subtask2_eligible_study_candidates(
                setting=instance["analysis_setting"],
                rows=linked_study_result_rows,
                source_context=instance.get("source_context") or {},
                article_ids_by_study_id=article_ids_by_study_id,
                article_table_count_by_id=article_table_count_by_id,
                candidate_set_mode=subtask2_candidate_filter,
            ),
        }
        candidate_sets = _subtask2_study_result_candidate_sets(
            setting=instance["analysis_setting"],
            rows=linked_study_result_rows,
            article_ids_by_study_id=article_ids_by_study_id,
            article_table_count_by_id=article_table_count_by_id,
            audit_registry=audit_registry,
        ) if subtask2_candidate_filter else []
        labeled_linked_study_result_rows = _apply_subtask2_review_labels(
            rows=linked_study_result_rows,
            audit_registry=audit_registry,
        )
        excluded_missing_article_rows = [
            row for row in study_result_rows if str(row.get("study_id") or "") not in linked_study_ids
        ]
        missing_study_ids = [study_id for study_id in included_studies if not article_ids_by_study_id.get(study_id)]
        if not linked_study_ids:
            coverage_status = "none"
        elif not missing_study_ids and set(gold_study_ids).issubset(linked_study_ids):
            coverage_status = "full"
        else:
            coverage_status = "partial"
        subtask_records.append(
            {
                "source_id": record["source_id"],
                "instance": {
                    "instance_id": instance["instance_id"],
                    "review_id": instance["review_id"],
                    "analysis_setting": analysis_setting,
                    "included_studies": included_studies,
                    "article_ids": sorted(seen_article_ids),
                    "article_study_links": article_study_links,
                    "article_coverage": {
                        "eligible_study_count": len(included_studies),
                        "gold_study_count": len(gold_study_ids),
                        "linked_study_count": len(linked_study_ids),
                        "linked_article_count": len(seen_article_ids),
                        "linked_gold_row_count": len(linked_study_result_rows),
                        "excluded_missing_article_gold_row_count": len(excluded_missing_article_rows),
                        "missing_study_ids": missing_study_ids,
                        "excluded_missing_article_study_ids": sorted({str(row.get("study_id") or "") for row in excluded_missing_article_rows if row.get("study_id")}),
                        "coverage_status": coverage_status,
                        "full_coverage": coverage_status == "full",
                        "primary_eval_eligible": True,
                        "source_support_filter": _subtask2_source_support_filter_name(
                            key_filter=subtask2_key_filter,
                            pairwise_comparison_filter=subtask2_pairwise_comparison_filter,
                            candidate_filter=subtask2_candidate_filter,
                        ),
                        "source_support_status_counts": source_support["status_counts"],
                    },
                    "source_support": source_support,
                    "source_context": instance.get("source_context") or {},
                    "source_refs": instance.get("source_refs") or {},
                },
                "gold": {
                    "instance_id": gold["instance_id"],
                    "review_id": gold["review_id"],
                    "study_result_rows": labeled_linked_study_result_rows,
                    **({"study_result_candidate_sets": candidate_sets} if subtask2_candidate_filter else {}),
                    "source": gold.get("source") or {},
                },
            }
        )
    return subtask_records


def _subtask2_eligible_study_candidates(
    *,
    setting: dict[str, Any],
    rows: list[dict[str, Any]],
    source_context: dict[str, Any],
    article_ids_by_study_id: dict[str, list[str]],
    article_table_count_by_id: dict[str, int] | None = None,
    candidate_set_mode: bool = False,
) -> list[dict[str, Any]]:
    hints_by_study = _source_context_hints_by_study(source_context)
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for row_index, row in enumerate(rows):
        study_id = str(row.get("study_id") or "")
        if not study_id:
            continue
        grouped[study_id].append((row_index, row))
    candidates: list[dict[str, Any]] = []
    for study_id, indexed_rows in grouped.items():
        article_id = _preferred_subtask2_article_id(
            article_ids=article_ids_by_study_id.get(study_id, []),
            article_table_count_by_id=article_table_count_by_id or {},
        )
        hint_parts = _subtask2_extraction_hint_parts(
            setting=setting,
            hints=hints_by_study.get(study_id) or [],
        )
        if candidate_set_mode:
            setting_id = str((indexed_rows[0][1]).get("setting_id") or setting.get("setting_id") or "")
            candidates.append(
                {
                    "study_id": study_id,
                    "article_id": article_id,
                    "extraction_task_id": _extraction_task_id_for_subtask2(setting_id=setting_id, study_id=study_id),
                    "extraction_hint_parts": hint_parts,
                }
            )
            continue
        extraction_targets = []
        for slot, (_row_index, row) in enumerate(indexed_rows):
            extraction_targets.append(
                {
                    "target_id": _target_id_for_subtask2(setting_id=str(row.get("setting_id") or setting.get("setting_id") or ""), study_id=study_id, slot=slot),
                    "extraction_hint": _target_extraction_hint_from_source_context(hints=hints_by_study.get(study_id) or [], slot=slot),
                    "extraction_hint_parts": _subtask2_extraction_hint_parts(
                        setting=setting,
                        hints=hints_by_study.get(study_id) or [],
                        slot=slot,
                    ),
                }
            )
        candidates.append(
            {
                "study_id": study_id,
                "article_id": article_id,
                "extraction_hint_parts": hint_parts,
                "extraction_targets": extraction_targets,
            }
        )
    return candidates


def _subtask2_study_result_candidate_sets(
    *,
    setting: dict[str, Any],
    rows: list[dict[str, Any]],
    article_ids_by_study_id: dict[str, list[str]],
    article_table_count_by_id: dict[str, int] | None = None,
    audit_registry: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        study_id = str(row.get("study_id") or "")
        if study_id:
            grouped[study_id].append(row)
    candidate_sets: list[dict[str, Any]] = []
    for study_id, study_rows in grouped.items():
        setting_id = str((study_rows[0]).get("setting_id") or setting.get("setting_id") or "")
        article_id = _preferred_subtask2_article_id(
            article_ids=article_ids_by_study_id.get(study_id, []),
            article_table_count_by_id=article_table_count_by_id or {},
        )
        candidate_sets.append(
            {
                "extraction_task_id": _extraction_task_id_for_subtask2(setting_id=setting_id, study_id=study_id),
                "setting_id": setting_id,
                "study_id": study_id,
                "article_id": article_id,
                **_subtask2_candidate_set_review_label(
                    study_rows=study_rows,
                    audit_registry=audit_registry or {},
                ),
                "gold_candidate_results": [
                    _gold_row_as_candidate(
                        row=row,
                        index=index,
                        review_meta=(audit_registry or {}).get(str(row.get("row_id") or "")),
                    )
                    for index, row in enumerate(sorted(study_rows, key=lambda item: str(item.get("row_id") or "")))
                ],
            }
        )
    return sorted(candidate_sets, key=lambda item: str(item.get("extraction_task_id") or ""))


def _gold_row_as_candidate(*, row: dict[str, Any], index: int, review_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    comparison = row.get("comparison") or {}
    outcome = row.get("outcome") or {}
    subgroup = row.get("subgroup") or {}
    return {
        "candidate_id": f"gold-candidate::{row.get('row_id') or index}",
        "source_row_id": row.get("row_id"),
        "match_status": "matched",
        "include_in_estimate": True,
        "study_result_setting": {
            "row_label": subgroup.get("level"),
            "outcome_label": outcome.get("label"),
            "outcome_measure": None,
            "timepoint": outcome.get("timepoint"),
            "statistic_type": None,
            "population_or_subgroup": subgroup.get("level"),
            "experimental_arm_label": comparison.get("experimental_arm"),
            "control_arm_label": comparison.get("control_arm"),
            "table_local_notes": row.get("footnote"),
        },
        "data_type": row.get("data_type"),
        "result_data": row.get("result_data") or {},
        **(review_meta or {}),
        "source": row.get("source") or {},
    }


def _preferred_subtask2_article_id(*, article_ids: list[str], article_table_count_by_id: dict[str, int]) -> str | None:
    if not article_ids:
        return None
    return max(article_ids, key=lambda article_id: (int(article_table_count_by_id.get(article_id) or 0) > 0, article_id))


def _source_context_hints_by_study(source_context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    hints_by_study: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in source_context.get("study_row_footnotes") or []:
        if not isinstance(item, dict):
            continue
        study_id = str(item.get("study_id") or "")
        if study_id:
            hints_by_study[study_id].append(item)
    for hints in hints_by_study.values():
        hints.sort(key=lambda item: _to_optional_int(item.get("row_index")) or 0)
    return hints_by_study


def _subtask2_extraction_hint_parts(*, setting: dict[str, Any], hints: list[dict[str, Any]], slot: int | None = None) -> dict[str, Any]:
    subgroup = setting.get("subgroup") if isinstance(setting.get("subgroup"), dict) else {}
    selected_hints = hints
    if slot is not None:
        selected_hints = [hints[slot]] if slot < len(hints) else []
    return {
        "analysis_name": _clean_optional_text(setting.get("analysis_name")),
        "analysis_group_name": _clean_optional_text(setting.get("analysis_group_name")),
        "setting_subgroup": _clean_optional_text(subgroup.get("level")),
        "study_row_hints": [
            {
                "subgroup": _clean_optional_text(hint.get("subgroup")),
                "footnote": _clean_optional_text(hint.get("footnote")),
                "applicability": _clean_optional_text(hint.get("applicability")),
            }
            for hint in selected_hints
            if isinstance(hint, dict)
            and any(_clean_optional_text(hint.get(key)) for key in ("subgroup", "footnote", "applicability"))
        ],
        "source": "official_analysis_non_numeric_context",
    }


def _target_extraction_hint_from_source_context(*, hints: list[dict[str, Any]], slot: int) -> str | None:
    hint = hints[slot] if slot < len(hints) else None
    if hint is None:
        return None
    values = [hint.get("subgroup"), hint.get("footnote")]
    text = " ; ".join(str(value) for value in values if value)
    return _clean_optional_text(text)


def _target_id_for_subtask2(*, setting_id: str, study_id: str, slot: int) -> str:
    return f"target::{setting_id}::{_target_slug(study_id)}::{slot}"


def _extraction_task_id_for_subtask2(*, setting_id: str, study_id: str) -> str:
    return f"task::{setting_id}::{_target_slug(study_id)}"


def _target_slug(value: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return cleaned or "study"


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _subtask2_key_filter_enabled(dataset_name: str) -> bool:
    return "key-filter" in dataset_name


def _subtask2_pairwise_comparison_filter_enabled(dataset_name: str) -> bool:
    return "pairwise-comparison-filter" in dataset_name


def _subtask2_candidate_filter_enabled(dataset_name: str) -> bool:
    return "candidate-filter" in dataset_name


def _subtask2_source_support_filter_name(*, key_filter: bool, pairwise_comparison_filter: bool, candidate_filter: bool = False) -> str:
    if candidate_filter:
        return "key_gold_direct+pairwise_setting_comparison+candidate_set"
    if pairwise_comparison_filter:
        return "key_gold_direct+pairwise_setting_comparison"
    return "key_gold_direct" if key_filter else "none"


def _subtask2_setting_has_high_quality_pairwise_comparison(setting: dict[str, Any]) -> bool:
    comparison = setting.get("comparison") or {}
    structure = setting.get("comparison_structure") or {}
    return (
        structure.get("type") == "pairwise"
        and bool(_clean_optional_text(comparison.get("experimental")))
        and bool(_clean_optional_text(comparison.get("comparator")))
        and _contains_pairwise_marker(setting.get("analysis_group_name"))
    )


def _subtask2_row_has_high_quality_pairwise_comparison(row: dict[str, Any]) -> bool:
    subgroup = (row.get("subgroup") or {}).get("level")
    return not _contains_pairwise_marker(subgroup)


def _subtask2_filter_source_support(*, source_support: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    keep_ids = {str(row.get("row_id") or "") for row in rows}
    row_support = {
        row_id: support
        for row_id, support in (source_support.get("row_support") or {}).items()
        if row_id in keep_ids
    }
    status_counts: Counter[str] = Counter()
    for support in row_support.values():
        status_counts[str(support.get("status") or "unknown")] += 1
    return {
        **source_support,
        "row_support": row_support,
        "status_counts": dict(sorted(status_counts.items())),
    }


def _contains_pairwise_marker(value: Any) -> bool:
    text = str(value or "")
    return bool(re.search(r"\b(vs\.?|versus|compared\s+with|compared\s+to)\b", text, flags=re.IGNORECASE))


def _article_text_by_id(*, article_bundle: dict[str, Any]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for source_path in (article_bundle.get("source_paths") or {}).values():
        payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
        article_id = str(payload.get("article_id") or "")
        if not article_id:
            continue
        texts[article_id] = _article_search_text(payload)
    return texts


def _article_table_count_by_id(*, article_bundle: dict[str, Any]) -> dict[str, int]:
    table_counts: dict[str, int] = {}
    for source_path in (article_bundle.get("source_paths") or {}).values():
        payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
        article_id = str(payload.get("article_id") or "")
        if not article_id:
            continue
        table_counts[article_id] = len(payload.get("tables") or [])
    return table_counts


def _article_search_text(article: dict[str, Any]) -> str:
    parts: list[str] = []
    metadata = article.get("metadata") or {}
    parts.extend(str(metadata.get(key) or "") for key in ("title", "abstract", "doi", "pmid", "pmc_id"))
    xml_content = article.get("xml_content")
    if isinstance(xml_content, str):
        parts.append(xml_content)
    elif isinstance(xml_content, dict):
        for section in xml_content.get("sections") or []:
            if isinstance(section, dict):
                parts.append(str(section.get("title") or ""))
                parts.append(str(section.get("text") or ""))
    for table in article.get("tables") or []:
        if not isinstance(table, dict):
            continue
        parts.append(str(table.get("caption") or ""))
        raw_xml = table.get("raw_xml")
        if isinstance(raw_xml, str):
            parts.append(raw_xml)
        for row in table.get("rows") or []:
            parts.append(json.dumps(row, ensure_ascii=False))
    return _normalize_search_text("\n".join(parts))


def _subtask2_source_support(
    *,
    rows: list[dict[str, Any]],
    article_ids_by_study_id: dict[str, list[str]],
    article_text_by_id: dict[str, str],
    article_table_count_by_id: dict[str, int],
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"filter": "none", "row_support": {}, "status_counts": {}}
    row_support = {}
    status_counts: Counter[str] = Counter()
    for row in rows:
        study_id = str(row.get("study_id") or "")
        article_ids = list(article_ids_by_study_id.get(study_id) or [])
        article_text = "\n".join(article_text_by_id.get(article_id, "") for article_id in article_ids)
        has_tables = any(int(article_table_count_by_id.get(article_id) or 0) > 0 for article_id in article_ids)
        values = _subtask2_required_gold_values(row)
        matched = [value for value in values if _numeric_value_present(value, article_text)]
        missing = [value for value in values if value not in matched]
        status = "supported_by_current_inputs" if values and not missing else "missing_key_gold_values"
        if not article_text:
            status = "missing_article_text"
        elif not has_tables:
            status = "missing_article_tables"
        status_counts[status] += 1
        row_support[str(row.get("row_id") or "")] = {
            "study_id": study_id,
            "article_ids": article_ids,
            "status": status,
            "include_in_primary_eval": status == "supported_by_current_inputs",
            "required_gold_values": values,
            "matched_gold_values": matched,
            "missing_key_gold_values": missing,
            "has_article_tables": has_tables,
        }
    return {
        "filter": "key_gold_direct",
        "row_support": row_support,
        "status_counts": dict(sorted(status_counts.items())),
    }


def _apply_subtask2_review_labels(*, rows: list[dict[str, Any]], audit_registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    labeled_rows: list[dict[str, Any]] = []
    for row in rows:
        review_meta = audit_registry.get(str(row.get("row_id") or ""), {})
        labeled_rows.append(
            {
                **row,
                **review_meta,
            }
        )
    return labeled_rows


def _subtask2_candidate_set_review_label(*, study_rows: list[dict[str, Any]], audit_registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    labels: list[str] = []
    notes: list[str] = []
    for row in study_rows:
        review_meta = audit_registry.get(str(row.get("row_id") or ""), {})
        label = review_meta.get("review_label")
        note = review_meta.get("audit_note")
        if label:
            labels.append(str(label))
        if note:
            notes.append(str(note))
    payload: dict[str, Any] = {}
    if labels:
        payload["review_label"] = labels[0] if len(set(labels)) == 1 else "mixed_review_labels"
    if notes:
        payload["audit_note"] = " | ".join(dict.fromkeys(notes))
    return payload


def _load_subtask2_audit_registry() -> dict[str, dict[str, Any]]:
    if not SUBTASK2_AUDIT_REGISTRY.exists():
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(SUBTASK2_AUDIT_REGISTRY):
        row_id = str(row.get("row_id") or "")
        review_label = row.get("review_label")
        audit_note = row.get("audit_note")
        if not row_id or not review_label:
            continue
        registry[row_id] = {
            "review_label": str(review_label),
            **({"audit_note": str(audit_note)} if audit_note else {}),
        }
    return registry


def _subtask2_required_gold_values(row: dict[str, Any]) -> list[str]:
    data = row.get("result_data") or {}
    values = []
    for key in sorted(data):
        value = data.get(key)
        if value is None:
            continue
        values.append(_normalize_numeric_for_search(value))
    return list(dict.fromkeys(value for value in values if value))


def _numeric_value_present(value: str, text: str) -> bool:
    if not value or not text:
        return False
    return bool(re.search(rf"(?<![\d.]){re.escape(value)}(?![\d.])", text))


def _normalize_search_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_numeric_for_search(value: Any) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _build_subtask3_records(
    records: list[dict[str, Any]],
    *,
    article_bundle: dict[str, Any],
    subtask2_key_filter: bool = False,
    **_: Any,
) -> list[dict[str, Any]]:
    subtask_records: list[dict[str, Any]] = []
    for record in records:
        gold = record["gold"]
        instance = record["instance"]
        subtask_records.append(
            {
                "source_id": record["source_id"],
                "instance": {
                    "instance_id": instance["instance_id"],
                    "review_id": instance["review_id"],
                    "analysis_setting": instance["analysis_setting"],
                    "included_studies": instance.get("included_studies") or [],
                    "source_context": instance.get("source_context") or {},
                    "source_refs": instance.get("source_refs") or {},
                },
                "gold": {
                    "instance_id": gold["instance_id"],
                    "review_id": gold["review_id"],
                    "analysis_methods": gold.get("analysis_methods") or [],
                    "source": gold.get("source") or {},
                },
            }
        )
    return subtask_records


def _build_subtask4_records(
    records: list[dict[str, Any]],
    *,
    article_bundle: dict[str, Any],
    subtask2_key_filter: bool = False,
    **_: Any,
) -> list[dict[str, Any]]:
    subtask_records: list[dict[str, Any]] = []
    for record in records:
        gold = record["gold"]
        instance = record["instance"]
        subgroup_results = gold.get("subgroup_results") or {"subgroup_estimates": [], "subgroup_difference_tests": []}
        if not ((subgroup_results.get("subgroup_estimates") or []) or (subgroup_results.get("subgroup_difference_tests") or [])):
            continue
        study_result_rows = gold.get("study_result_rows") or []
        if not study_result_rows:
            continue
        subtask_records.append(
            {
                "source_id": record["source_id"],
                "instance": {
                    "instance_id": instance["instance_id"],
                    "review_id": instance["review_id"],
                    "analysis_setting": instance["analysis_setting"],
                    "study_result_rows": study_result_rows,
                    "analysis_methods": gold.get("analysis_methods") or [],
                    "included_studies": instance.get("included_studies") or [],
                    "source_context": instance.get("source_context") or {},
                    "source_refs": instance.get("source_refs") or {},
                },
                "gold": {
                    "instance_id": gold["instance_id"],
                    "review_id": gold["review_id"],
                    "subgroup_results": subgroup_results,
                    "source": gold.get("source") or {},
                },
            }
        )
    return subtask_records


def _build_subtask5_records(
    records: list[dict[str, Any]],
    *,
    article_bundle: dict[str, Any],
    subtask2_key_filter: bool = False,
    **_: Any,
) -> list[dict[str, Any]]:
    subtask_records: list[dict[str, Any]] = []
    for record in records:
        gold = record["gold"]
        overall_estimates = gold.get("overall_estimates") or []
        if not overall_estimates:
            continue
        study_result_rows = gold.get("study_result_rows") or []
        if not study_result_rows:
            continue
        instance = record["instance"]
        subtask_records.append(
            {
                "source_id": record["source_id"],
                "instance": {
                    "instance_id": instance["instance_id"],
                    "review_id": instance["review_id"],
                    "analysis_setting": instance["analysis_setting"],
                    "study_result_rows": study_result_rows,
                    "analysis_methods": gold.get("analysis_methods") or [],
                    "included_studies": instance.get("included_studies") or [],
                    "source_context": instance.get("source_context") or {},
                    "source_refs": instance.get("source_refs") or {},
                },
                "gold": {
                    "instance_id": gold["instance_id"],
                    "review_id": gold["review_id"],
                    "overall_estimates": overall_estimates,
                    "source": gold.get("source") or {},
                },
            }
        )
    return subtask_records


def _has_official_overall_estimate(raw: dict[str, Any]) -> bool:
    return any(str(raw.get(field) or "").strip() for field in ("Mean", "CI start", "CI end", "PI start", "PI end"))


def _to_int(value: Any) -> int:
    return int(float(str(value).strip()))


def _to_optional_int(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _to_int(text)
    except ValueError:
        return None


def _to_float(value: Any) -> float:
    return float(str(value).strip())


def _to_optional_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())
