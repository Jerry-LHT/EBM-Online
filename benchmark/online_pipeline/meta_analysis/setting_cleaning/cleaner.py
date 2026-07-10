"""CLI for direct LLM cleaning of Meta Analysis setting fields."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from benchmark.online_pipeline.meta_analysis.setting_cleaning.cache import (
    comparison_cache_cleaning_metadata,
    comparison_cache_key,
    comparison_cache_row,
    comparison_cache_metadata,
    is_valid_comparison_cache_row,
    setting_has_valid_comparison_cache,
)
from benchmark.online_pipeline.meta_analysis.setting_cleaning.llm import extract_field_with_llm
from benchmark.online_pipeline.meta_analysis.setting_cleaning.sources import (
    assemble_setting,
    build_analysis_family_sources,
    build_field_candidates,
    method_from_family,
    normalize_official_rows,
)
from benchmark.online_pipeline.shared.building import DEFAULT_SEED, RAW_DATA_DIR, stable_key
from benchmark.online_pipeline.shared.jsonl import append_jsonl, read_jsonl, write_jsonl
from benchmark.online_pipeline.shared.report_utils import write_json


MODULE = "meta_analysis"
RAW_ROOT = RAW_DATA_DIR / MODULE
SOURCE_DIR = RAW_ROOT / "source"
INTERMEDIATE_DIR = RAW_ROOT / "intermediate"
OFFICIAL_DIR = SOURCE_DIR / "official_analysis_csv_snapshot"
ARTICLES_DIR = RAW_DATA_DIR / "cleaned_articles"
FIELDS = ("comparison", "outcome", "timepoint")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean meta-analysis setting fields.")
    parser.add_argument("command", choices=("normalize", "candidates", "preview", "full", "audit"))
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--llm-config", default="llm.local.json")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-failures", type=int, default=50)
    parser.add_argument("--max-failure-rate", type=float, default=0.2)
    parser.add_argument("--failure-rate-min-attempts", type=int, default=100)
    args = parser.parse_args()

    if args.command == "normalize":
        paths = write_normalized_sources()
        print(paths["families"])
        return
    if args.command == "candidates":
        paths = write_normalized_sources()
        print(paths["field_candidates"])
        return
    if args.command == "audit":
        print(audit_cleaned_settings()["report_path"])
        return

    suffix = ".preview30" if args.command == "preview" else ""
    limit = args.limit if args.command == "preview" else None
    result = run_cleaning(
        suffix=suffix,
        limit=limit,
        seed=args.seed,
        llm_config=args.llm_config,
        workers=args.workers,
        resume=args.resume,
        max_failures=args.max_failures,
        max_failure_rate=args.max_failure_rate,
        failure_rate_min_attempts=args.failure_rate_min_attempts,
    )
    print(result["settings_path"])


def write_normalized_sources() -> dict[str, str]:
    INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
    normalized = normalize_official_rows(OFFICIAL_DIR)
    families = build_analysis_family_sources(
        overall_rows=normalized["overall"],
        data_rows=normalized["data_rows"],
        subgroup_rows=normalized["subgroup_estimates"],
    )
    candidates = build_field_candidates(families)

    write_jsonl(INTERMEDIATE_DIR / "official_overall_rows.jsonl", normalized["overall"], sort_keys=False)
    write_jsonl(INTERMEDIATE_DIR / "official_data_rows.jsonl", normalized["data_rows"], sort_keys=False)
    write_jsonl(INTERMEDIATE_DIR / "official_subgroup_estimate_rows.jsonl", normalized["subgroup_estimates"], sort_keys=False)
    write_jsonl(INTERMEDIATE_DIR / "analysis_family_sources.jsonl", families, sort_keys=False)
    link_index, linked_families, coverage_report = _build_article_link_coverage(families)
    write_jsonl(INTERMEDIATE_DIR / "study_article_link_index.jsonl", link_index, sort_keys=False)
    write_jsonl(INTERMEDIATE_DIR / "analysis_family_sources.linked.jsonl", linked_families, sort_keys=False)
    write_json(INTERMEDIATE_DIR / "analysis_family_coverage_report.json", coverage_report)
    for field, rows in candidates.items():
        write_jsonl(INTERMEDIATE_DIR / "field_candidates" / f"{field}_candidates.jsonl", rows, sort_keys=False)
    write_json(INTERMEDIATE_DIR / "setting_source_report.json", _source_report(normalized=normalized, families=families))
    return {
        "overall": str(INTERMEDIATE_DIR / "official_overall_rows.jsonl"),
        "data_rows": str(INTERMEDIATE_DIR / "official_data_rows.jsonl"),
        "subgroup_estimates": str(INTERMEDIATE_DIR / "official_subgroup_estimate_rows.jsonl"),
        "families": str(INTERMEDIATE_DIR / "analysis_family_sources.jsonl"),
        "linked_families": str(INTERMEDIATE_DIR / "analysis_family_sources.linked.jsonl"),
        "study_article_link_index": str(INTERMEDIATE_DIR / "study_article_link_index.jsonl"),
        "field_candidates": str(INTERMEDIATE_DIR / "field_candidates"),
    }


def run_cleaning(
    *,
    suffix: str,
    limit: int | None,
    seed: str,
    llm_config: str | Path,
    workers: int,
    resume: bool,
    max_failures: int,
    max_failure_rate: float,
    failure_rate_min_attempts: int,
) -> dict[str, Any]:
    if workers <= 0:
        raise ValueError("workers must be positive")
    write_normalized_sources()
    families = _select_families(read_jsonl(INTERMEDIATE_DIR / "analysis_family_sources.linked.jsonl"), limit=limit, seed=seed)
    candidates_by_field = build_field_candidates(families)
    paths = _output_paths(suffix)
    _initialize_outputs(paths=paths, resume=resume)
    write_jsonl(paths["families"], families, sort_keys=False)
    for field, candidates in candidates_by_field.items():
        write_jsonl(paths["field_candidates"][field], candidates, sort_keys=False)

    candidate_lookup = {
        field: {row["candidate_id"]: row for row in rows}
        for field, rows in candidates_by_field.items()
    }

    comparison_cache = _load_comparison_cache(paths["comparison_cache"], candidate_lookup=candidate_lookup["comparison"]) if resume else {}
    comparison_cache.update(_comparison_cache_from_settings(paths["settings"], candidate_lookup=candidate_lookup["comparison"]) if resume else {})
    if comparison_cache:
        write_jsonl(paths["comparison_cache"], list(comparison_cache.values()), sort_keys=False)
    comparison_cache_lock = threading.Lock()

    completed = _completed_candidate_ids(paths["settings"], candidate_lookup=candidate_lookup["comparison"]) if resume else set()
    pending = [family for family in families if family["candidate_id"] not in completed]
    initial_completed = len(completed)
    total_target = len(families)

    def clean_one(family: dict[str, Any]) -> dict[str, Any]:
        candidate_id = family["candidate_id"]
        comparison_candidate = candidate_lookup["comparison"][candidate_id]
        comparison_key = comparison_cache_key(comparison_candidate)
        with comparison_cache_lock:
            comparison = comparison_cache.get(comparison_key)
        if comparison is None:
            fetched_comparison = extract_field_with_llm(
                field="comparison",
                candidate=comparison_candidate,
                llm_config=llm_config,
            )
            fetched_comparison = comparison_cache_row(comparison_candidate, fetched_comparison)
            with comparison_cache_lock:
                comparison = comparison_cache.get(comparison_key)
                if comparison is None:
                    comparison = fetched_comparison
                    comparison_cache[comparison_key] = comparison
                    append_jsonl(paths["comparison_cache"], [comparison], sort_keys=False)
        fields = {
            "comparison": comparison,
            **{
                field: extract_field_with_llm(
                    field=field,
                    candidate=candidate_lookup[field][candidate_id],
                    llm_config=llm_config,
                )
                for field in ("outcome", "timepoint")
            },
        }
        setting = assemble_setting(
            family=family,
            comparison=fields["comparison"],
            outcome=fields["outcome"],
            timepoint=fields["timepoint"],
            method=method_from_family(family),
        )
        setting["cleaning"] = {
            **(setting.get("cleaning") or {}),
            "method": "llm_direct_fields_v1",
            "field_methods": {field: fields[field].get("method") for field in FIELDS},
            "field_confidence": {field: fields[field].get("confidence") for field in FIELDS},
            "field_warnings": {field: fields[field].get("warnings") or [] for field in FIELDS},
            **comparison_cache_cleaning_metadata(comparison_candidate),
        }
        return setting

    attempted = 0
    failed = 0
    stopped_early = False
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(pending)))) as executor:
        pending_iter = iter(pending)
        futures = {}
        for _ in range(min(workers, len(pending))):
            try:
                family = next(pending_iter)
            except StopIteration:
                break
            futures[executor.submit(clean_one, family)] = family
        while futures:
            for future in as_completed(futures):
                break
            family = futures[future]
            del futures[future]
            attempted += 1
            try:
                setting = future.result()
            except Exception as exc:
                failed += 1
                append_jsonl(
                    paths["failures"],
                    [{"candidate_id": family["candidate_id"], "error_type": type(exc).__name__, "message": str(exc)}],
                    sort_keys=False,
                )
            else:
                append_jsonl(paths["settings"], [setting], sort_keys=False)

            current_completed = initial_completed + (attempted - failed)
            current_cache_keys = len(comparison_cache)
            print(
                f"[progress] completed={current_completed}/{total_target} "
                f"attempted={initial_completed + attempted}/{total_target} "
                f"failed={failed} comparison_cache_keys={current_cache_keys}",
                flush=True,
            )

            if _should_stop_for_failures(
                attempted=attempted,
                failed=failed,
                max_failures=max_failures,
                max_failure_rate=max_failure_rate,
                failure_rate_min_attempts=failure_rate_min_attempts,
            ):
                stopped_early = True
                for pending_future in futures:
                    pending_future.cancel()
                futures.clear()
                break

            try:
                next_family = next(pending_iter)
            except StopIteration:
                continue
            futures[executor.submit(clean_one, next_family)] = next_family

    _prune_resolved_failures(paths=paths, candidate_lookup=candidate_lookup["comparison"])
    settings = _read_optional_jsonl(paths["settings"])
    failures = _read_optional_jsonl(paths["failures"])
    report = _quality_report(families=families, settings=settings, failures=failures)
    report["run_control"] = {
        "stopped_early": stopped_early,
        "attempted_in_this_run": attempted,
        "failed_in_this_run": failed,
        "max_failures": max_failures,
        "max_failure_rate": max_failure_rate,
        "failure_rate_min_attempts": failure_rate_min_attempts,
    }
    write_json(paths["report"], report)
    write_jsonl(paths["raw_material"], _build_raw_material(families=families, settings=settings), sort_keys=False)
    _write_preview_markdown(paths["preview_md"], settings=settings)
    return {"settings_path": str(paths["settings"]), "report": report}


def audit_cleaned_settings(*, suffix: str = "") -> dict[str, Any]:
    families = read_jsonl(INTERMEDIATE_DIR / f"analysis_family_sources.linked{suffix}.jsonl")
    candidates = build_field_candidates(families)["comparison"]
    candidate_lookup = {row["candidate_id"]: row for row in candidates}
    paths = _output_paths(suffix)
    settings = _read_optional_jsonl(paths["settings"])
    invalid_rows = []
    old_key_rows = []
    source_hash_mismatch_rows = []
    known_badcase = None
    for setting in settings:
        candidate_id = str(setting.get("candidate_id") or "")
        cleaning = setting.get("cleaning") or {}
        cache_key = (((cleaning.get("field_cache_keys") or {}).get("comparison")) or "")
        if str(cache_key).startswith("comparison::"):
            old_key_rows.append(candidate_id)
        candidate = candidate_lookup.get(candidate_id)
        if candidate is None or not setting_has_valid_comparison_cache(setting, candidate):
            invalid_rows.append(candidate_id or "<missing>")
            if candidate is not None:
                expected = comparison_cache_metadata(candidate)
                source_hash = ((cleaning.get("field_cache_source_hashes") or {}).get("comparison"))
                if source_hash and source_hash != expected["source_hash"]:
                    source_hash_mismatch_rows.append(candidate_id)
        if candidate_id == "candidate::CD001431::11::2":
            comparison = setting.get("comparison") or {}
            text = " ".join(str(comparison.get(key) or "") for key in ("experimental", "comparator")).lower()
            known_badcase = {
                "candidate_id": candidate_id,
                "comparison": comparison,
                "contains_surgery_or_conservative": "surgery" in text or "conservative" in text,
            }
    missing_candidate_ids = sorted(set(candidate_lookup) - {str(row.get("candidate_id") or "") for row in settings})
    report = {
        "settings_path": str(paths["settings"]),
        "candidate_count": len(candidate_lookup),
        "setting_count": len(settings),
        "missing_count": len(missing_candidate_ids),
        "invalid_v2_count": len(invalid_rows),
        "old_comparison_key_count": len(old_key_rows),
        "source_hash_mismatch_count": len(source_hash_mismatch_rows),
        "invalid_examples": sorted(invalid_rows)[:20],
        "old_key_examples": sorted(old_key_rows)[:20],
        "source_hash_mismatch_examples": sorted(source_hash_mismatch_rows)[:20],
        "missing_examples": missing_candidate_ids[:20],
        "known_badcase_cd001431_11_2": known_badcase,
    }
    report_path = INTERMEDIATE_DIR / f"setting_cleaning_audit{suffix}.json"
    write_json(report_path, report)
    return {"report_path": str(report_path), "report": report}


def _select_families(families: list[dict[str, Any]], *, limit: int | None, seed: str) -> list[dict[str, Any]]:
    if limit is None:
        return families
    ordered = sorted(families, key=lambda row: stable_key(seed=f"{seed}:setting-cleaning", module=MODULE, instance_id=row["candidate_id"]))
    return sorted(ordered[: min(limit, len(ordered))], key=lambda row: row["candidate_id"])


def _output_paths(suffix: str) -> dict[str, Any]:
    field_candidates = {field: INTERMEDIATE_DIR / "field_candidates" / f"{field}_candidates{suffix}.jsonl" for field in FIELDS}
    return {
        "families": INTERMEDIATE_DIR / f"analysis_family_sources{suffix}.jsonl",
        "field_candidates": field_candidates,
        "settings": INTERMEDIATE_DIR / f"setting_cleaned{suffix}.jsonl",
        "raw_material": INTERMEDIATE_DIR / f"setting_raw_material{suffix}.jsonl",
        "comparison_cache": INTERMEDIATE_DIR / "field_cleaning_cache" / f"comparison{suffix}.jsonl",
        "report": INTERMEDIATE_DIR / f"setting_cleaning_report{suffix}.json",
        "preview_md": INTERMEDIATE_DIR / f"setting_cleaning_preview{suffix}.md",
        "failures": INTERMEDIATE_DIR / f"setting_cleaning_failures{suffix}.jsonl",
    }


def _initialize_outputs(*, paths: dict[str, Any], resume: bool) -> None:
    if resume:
        return
    path_values: list[Path] = [
        paths["families"],
        paths["settings"],
        paths["raw_material"],
        paths["comparison_cache"],
        paths["report"],
        paths["preview_md"],
        paths["failures"],
    ]
    path_values.extend(paths["field_candidates"].values())
    for path in path_values:
        if path.exists():
            path.unlink()


def _prune_resolved_failures(*, paths: dict[str, Any], candidate_lookup: dict[str, dict[str, Any]]) -> None:
    failure_path = paths["failures"]
    if not failure_path.exists():
        return
    completed = _completed_candidate_ids(paths["settings"], candidate_lookup=candidate_lookup)
    unresolved = [row for row in read_jsonl(failure_path) if str(row.get("candidate_id") or "") not in completed]
    write_jsonl(failure_path, unresolved, sort_keys=False)


def _should_stop_for_failures(
    *,
    attempted: int,
    failed: int,
    max_failures: int,
    max_failure_rate: float,
    failure_rate_min_attempts: int,
) -> bool:
    if max_failures > 0 and failed >= max_failures:
        return True
    if attempted >= failure_rate_min_attempts and max_failure_rate > 0 and attempted > 0:
        return failed / attempted >= max_failure_rate
    return False


def _load_comparison_cache(path: Path, *, candidate_lookup: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        cache_key = str(row.get("cache_key") or "")
        candidate = candidate_lookup.get(str(row.get("candidate_id") or ""))
        if cache_key and candidate is not None and is_valid_comparison_cache_row(row, candidate):
            cache[cache_key] = row
    return cache


def _comparison_cache_from_settings(path: Path, *, candidate_lookup: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        cache_key = ((row.get("cleaning") or {}).get("field_cache_keys") or {}).get("comparison")
        if not cache_key:
            continue
        candidate = candidate_lookup.get(str(row.get("candidate_id") or ""))
        if candidate is None or not setting_has_valid_comparison_cache(row, candidate):
            continue
        metadata = comparison_cache_metadata(candidate)
        cache[str(cache_key)] = {
            "candidate_id": row.get("candidate_id"),
            "cache_key": str(cache_key),
            "cache_version": metadata["cache_version"],
            "prompt_version": metadata["prompt_version"],
            "source_hash": metadata["source_hash"],
            "cache_input": metadata["cache_input"],
            "confidence": ((row.get("cleaning") or {}).get("field_confidence") or {}).get("comparison"),
            "warnings": ((row.get("cleaning") or {}).get("field_warnings") or {}).get("comparison") or [],
            "method": ((row.get("cleaning") or {}).get("field_methods") or {}).get("comparison") or "llm_comparison_v1",
            "comparison": row.get("comparison") or {"experimental": None, "comparator": None},
            "comparison_structure": row.get("comparison_structure") or {"type": "unclear", "rationale": None},
        }
    return cache


def _source_report(*, normalized: dict[str, list[dict[str, Any]]], families: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall_row_count": len(normalized["overall"]),
        "data_row_count": len(normalized["data_rows"]),
        "subgroup_estimate_row_count": len(normalized["subgroup_estimates"]),
        "family_count": len(families),
        "data_type_counts": dict(sorted(Counter((row.get("method_source") or {}).get("data_type") for row in families).items())),
        "families_with_subgroup_estimate_levels": sum(1 for row in families if (row.get("subgroup_estimate_source") or {}).get("levels")),
        "families_with_study_row_subgroups": sum(1 for row in families if (row.get("study_row_source") or {}).get("subgroup_labels")),
        "families_with_footnotes": sum(1 for row in families if (row.get("study_row_source") or {}).get("footnote_rows")),
        "families_with_explicit_labels": sum(1 for row in families if (row.get("explicit_labels") or {}).get("experimental_group_label") or (row.get("explicit_labels") or {}).get("control_group_label")),
    }


def _build_article_link_coverage(families: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    article_rows = []
    article_study_ids: set[str] = set()
    for path in sorted(ARTICLES_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        study_id = " ".join(str(payload.get("study_id") or "").split())
        if not study_id:
            continue
        article_study_ids.add(study_id)
        article_rows.append(
            {
                "study_id": study_id,
                "article_id": payload.get("article_id"),
                "path": str(path),
                "pmc_id": ((payload.get("metadata") or {}).get("pmc_id")),
                "title": ((payload.get("metadata") or {}).get("title")),
            }
        )

    linked_families = []
    coverage_counts = Counter()
    linked_study_count_dist = Counter()
    for family in families:
        eligible = list((family.get("study_row_source") or {}).get("eligible_study_ids") or [])
        linked = [study_id for study_id in eligible if study_id in article_study_ids]
        missing = [study_id for study_id in eligible if study_id not in article_study_ids]
        family = {
            **family,
            "article_linkage": {
                "eligible_study_count": len(eligible),
                "linked_cleaned_article_count": len(linked),
                "linked_study_ids": linked,
                "missing_study_ids": missing,
                "has_linked_cleaned_article": bool(linked),
            },
        }
        if linked:
            linked_families.append(family)
            coverage_counts.update(["linked_family"])
        else:
            coverage_counts.update(["unlinked_family"])
        linked_study_count_dist.update([len(linked)])

    coverage_report = {
        "family_count": len(families),
        "linked_family_count": coverage_counts.get("linked_family", 0),
        "unlinked_family_count": coverage_counts.get("unlinked_family", 0),
        "linked_family_ratio": round(coverage_counts.get("linked_family", 0) / len(families), 4) if families else 0.0,
        "cleaned_article_count": len(article_rows),
        "unique_cleaned_article_study_id_count": len(article_study_ids),
        "linked_study_count_distribution": dict(sorted(linked_study_count_dist.items())),
    }
    return article_rows, linked_families, coverage_report


def _build_raw_material(*, families: list[dict[str, Any]], settings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family_by_candidate = {row["candidate_id"]: row for row in families}
    material = []
    for setting in sorted(settings, key=lambda row: row["candidate_id"]):
        family = family_by_candidate.get(setting["candidate_id"])
        if not family:
            continue
        material.append(
            {
                "raw_material_id": f"meta-analysis-setting-raw::{setting['review_id']}::{setting['analysis_group']}::{setting['analysis_number']}",
                "candidate_id": setting["candidate_id"],
                "setting_family_id": setting["setting_family_id"],
                "review_id": setting["review_id"],
                "analysis_group": setting["analysis_group"],
                "analysis_number": setting["analysis_number"],
                "source_fields": {
                    "analysis_name": setting.get("analysis_name"),
                    "analysis_group_name": setting.get("analysis_group_name"),
                    "explicit_labels": family.get("explicit_labels") or {},
                },
                "llm_cleaned_setting": {
                    "population_scope": setting.get("population_scope"),
                    "comparison": setting.get("comparison"),
                    "comparison_structure": setting.get("comparison_structure"),
                    "outcome": setting.get("outcome"),
                    "timepoint": setting.get("timepoint"),
                },
                "official_method": setting.get("method") or {},
                "official_study_rows": family.get("study_row_source") or {},
                "official_subgroup_estimates": family.get("subgroup_estimate_source") or {"levels": [], "difference_test": {}},
                "scope_flags": setting.get("scope_flags") or {},
                "setting_quality": setting.get("setting_quality") or {},
                "source_provenance": setting.get("source_provenance") or {},
                "cleaning": setting.get("cleaning") or {},
            }
        )
    return material


def _quality_report(*, families: list[dict[str, Any]], settings: list[dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    warning_counts = Counter()
    source_counts = Counter()
    comparison_structure_counts = Counter()
    comparison_cache_keys = set()
    ready_counts = Counter()
    review_reason_counts = Counter()
    for setting in settings:
        warning_counts.update((setting.get("cleaning") or {}).get("warnings") or [])
        source_counts.update(["with_footnotes" if ((setting.get("source_context") or {}).get("study_row_footnotes")) else "without_footnotes"])
        comparison_structure_counts.update([((setting.get("comparison_structure") or {}).get("type")) or "unclear"])
        cache_key = (((setting.get("cleaning") or {}).get("field_cache_keys") or {}).get("comparison"))
        if cache_key:
            comparison_cache_keys.add(str(cache_key))
        quality = setting.get("setting_quality") or {}
        ready_counts.update(["ready" if quality.get("ready_for_downstream_setting_build") else "needs_review"])
        review_reason_counts.update(quality.get("review_reasons") or [])
    return {
        "candidate_count": len(families),
        "completed_count": len(settings),
        "failure_count": len(failures),
        "warning_counts": dict(sorted(warning_counts.items())),
        "source_context_counts": dict(sorted(source_counts.items())),
        "comparison_structure_counts": dict(sorted(comparison_structure_counts.items())),
        "comparison_cache_key_count": len(comparison_cache_keys),
        "comparison_cache_saved_calls": max(0, len(settings) - len(comparison_cache_keys)),
        "setting_quality_counts": dict(sorted(ready_counts.items())),
        "review_reason_counts": dict(sorted(review_reason_counts.items())),
        "data_type_counts": dict(sorted(Counter(setting.get("data_type") for setting in settings).items())),
    }


def _write_preview_markdown(path: Path, *, settings: list[dict[str, Any]]) -> None:
    lines = ["# Meta Analysis Setting Cleaning Preview", ""]
    for setting in sorted(settings, key=lambda row: row["candidate_id"])[:30]:
        footnote_count = len((setting.get("source_context") or {}).get("study_row_footnotes") or [])
        lines.extend(
            [
                f"## {setting['candidate_id']}",
                "",
                f"- analysis: {setting.get('analysis_group_name')} / {setting.get('analysis_name')}",
                f"- comparison: {(setting.get('comparison') or {}).get('experimental')} vs {(setting.get('comparison') or {}).get('comparator')}",
                f"- outcome: {(setting.get('outcome') or {}).get('outcome_concept')}",
                f"- timepoint: {(setting.get('timepoint') or {}).get('label')}",
                f"- study row footnotes: {footnote_count}",
                f"- warnings: {', '.join((setting.get('cleaning') or {}).get('warnings') or []) or 'none'}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _completed_candidate_ids(path: Path, *, candidate_lookup: dict[str, dict[str, Any]]) -> set[str]:
    if not path.exists():
        return set()
    completed = set()
    for row in read_jsonl(path):
        candidate_id = str(row.get("candidate_id") or "")
        candidate = candidate_lookup.get(candidate_id)
        if candidate is not None and setting_has_valid_comparison_cache(row, candidate):
            completed.add(candidate_id)
    return completed


def _read_optional_jsonl(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path) if path.exists() else []


if __name__ == "__main__":
    main()
