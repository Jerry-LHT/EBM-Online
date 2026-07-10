"""Build a supported Subtask 2 test subset from a filtered dataset.

This script creates a smaller benchmark split that only contains instances whose
gold rows are marked as supported by the current article inputs. Selection is
deterministic and attempts to preserve data-type mix while diversifying reviews.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from benchmark.online_pipeline.shared.jsonl import read_jsonl, write_jsonl
from benchmark.online_pipeline.shared.report_utils import write_json


DEFAULT_SOURCE_DATASET = Path(
    "benchmark/online_pipeline/meta_analysis/subtask2_study_results/datasets/cochrane_meta_v2-key-filter"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dataset", default=str(DEFAULT_SOURCE_DATASET))
    parser.add_argument("--source-split", default="test")
    parser.add_argument(
        "--output-dataset",
        default="benchmark/online_pipeline/meta_analysis/subtask2_study_results/datasets/_tmp_supported_test50",
    )
    parser.add_argument("--output-split", default="test50")
    parser.add_argument("--seed-dataset", default=None)
    parser.add_argument("--seed-split", default=None)
    parser.add_argument("--extra-split", default=None)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    summary = build_supported_subset(
        source_dataset=Path(args.source_dataset),
        source_split=args.source_split,
        output_dataset=Path(args.output_dataset),
        output_split=args.output_split,
        limit=args.limit,
        seed_dataset=Path(args.seed_dataset) if args.seed_dataset else None,
        seed_split=args.seed_split,
        extra_split=args.extra_split,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def build_supported_subset(
    *,
    source_dataset: Path,
    source_split: str,
    output_dataset: Path,
    output_split: str,
    limit: int,
    seed_dataset: Path | None = None,
    seed_split: str | None = None,
    extra_split: str | None = None,
) -> dict[str, Any]:
    split_dir = source_dataset / "splits" / source_split
    instances = read_jsonl(split_dir / "instances.jsonl")
    gold_rows = read_jsonl(split_dir / "gold.jsonl")
    gold_by_id = {str(row["instance_id"]): row for row in gold_rows}

    supported_instances = [
        instance
        for instance in instances
        if _instance_fully_supported(instance=instance, gold=gold_by_id[str(instance["instance_id"])])
    ]
    seed_instances = _load_seed_instances(seed_dataset=seed_dataset, seed_split=seed_split)
    seed_ids = {str(instance["instance_id"]) for instance in seed_instances}
    unsupported_seed_ids = sorted(
        str(instance["instance_id"])
        for instance in seed_instances
        if str(instance["instance_id"]) not in {str(item["instance_id"]) for item in supported_instances}
    )
    if unsupported_seed_ids:
        raise ValueError(f"Seed split contains unsupported instances: {unsupported_seed_ids[:10]}")
    if len(seed_instances) > limit:
        raise ValueError(f"Seed split has {len(seed_instances)} instances, larger than requested limit={limit}")

    extra_limit = limit - len(seed_instances)
    extra_candidates = [instance for instance in supported_instances if str(instance["instance_id"]) not in seed_ids]
    extra_instances = _select_instances(instances=extra_candidates, limit=extra_limit)
    selected_instances = [*seed_instances, *extra_instances]
    selected_ids = {str(instance["instance_id"]) for instance in selected_instances}
    selected_gold = [gold_by_id[instance_id] for instance_id in [str(item["instance_id"]) for item in selected_instances]]
    extra_ids = {str(instance["instance_id"]) for instance in extra_instances}
    extra_gold = [gold_by_id[str(item["instance_id"])] for item in extra_instances]

    output_split_dir = output_dataset / "splits" / output_split
    output_split_dir.mkdir(parents=True, exist_ok=True)

    write_jsonl(output_split_dir / "instances.jsonl", selected_instances, sort_keys=False)
    write_jsonl(output_split_dir / "gold.jsonl", selected_gold, sort_keys=False)
    write_jsonl(output_dataset / "instances.jsonl", selected_instances, sort_keys=False)
    write_jsonl(output_dataset / "gold.jsonl", selected_gold, sort_keys=False)

    if extra_split:
        extra_split_dir = output_dataset / "splits" / extra_split
        extra_split_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(extra_split_dir / "instances.jsonl", extra_instances, sort_keys=False)
        write_jsonl(extra_split_dir / "gold.jsonl", extra_gold, sort_keys=False)

    _ensure_shared_symlink(source_dataset=source_dataset, output_dataset=output_dataset)

    audit_rows = [
        _support_audit_row(
            instance=instance,
            gold=gold_by_id[str(instance["instance_id"])],
            selection_group="seed" if str(instance["instance_id"]) in seed_ids else "extra",
        )
        for instance in selected_instances
    ]
    write_json(output_dataset / "support_audit.json", {"rows": audit_rows})

    summary = {
        "source_dataset": str(source_dataset),
        "source_split": source_split,
        "output_dataset": str(output_dataset),
        "output_split": output_split,
        "requested_limit": limit,
        "supported_instance_count": len(supported_instances),
        "selected_instance_count": len(selected_instances),
        "seed_instance_count": len(seed_instances),
        "extra_instance_count": len(extra_instances),
        "selected_review_count": len({str(item.get("review_id") or "") for item in selected_instances}),
        "selected_data_type_counts": _data_type_counts(selected_instances),
        "extra_data_type_counts": _data_type_counts(extra_instances),
        "selected_instance_ids": [str(item["instance_id"]) for item in selected_instances],
        "extra_instance_ids": [str(item["instance_id"]) for item in extra_instances],
        "selection_policy": {
            "support_rule": "all gold rows must have source_support.row_support status=supported_by_current_inputs and include_in_primary_eval=true",
            "sampling_rule": "optional seed split is preserved first; remaining slots use data-type proportional quotas with review-level round-robin inside each bucket",
        },
    }
    write_json(output_dataset / "subset_summary.json", summary)
    return summary


def _load_seed_instances(*, seed_dataset: Path | None, seed_split: str | None) -> list[dict[str, Any]]:
    if seed_dataset is None:
        return []
    split_name = seed_split or "test"
    path = seed_dataset / "splits" / split_name / "instances.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Seed split not found: {path}")
    return read_jsonl(path)


def _instance_fully_supported(*, instance: dict[str, Any], gold: dict[str, Any]) -> bool:
    row_support = ((instance.get("source_support") or {}).get("row_support") or {})
    rows = gold.get("study_result_rows") or []
    if not rows:
        return False
    for row in rows:
        support = row_support.get(str(row.get("row_id") or "")) or {}
        if str(support.get("status") or "") != "supported_by_current_inputs":
            return False
        if support.get("include_in_primary_eval") is not True:
            return False
    return True


def _support_audit_row(*, instance: dict[str, Any], gold: dict[str, Any], selection_group: str) -> dict[str, Any]:
    row_support = ((instance.get("source_support") or {}).get("row_support") or {})
    rows = []
    for row in gold.get("study_result_rows") or []:
        support = row_support.get(str(row.get("row_id") or "")) or {}
        rows.append(
            {
                "row_id": row.get("row_id"),
                "study_id": row.get("study_id"),
                "required_gold_values": support.get("required_gold_values") or [],
                "matched_gold_values": support.get("matched_gold_values") or [],
                "missing_key_gold_values": support.get("missing_key_gold_values") or [],
                "status": support.get("status"),
                "include_in_primary_eval": support.get("include_in_primary_eval"),
                "has_article_tables": support.get("has_article_tables"),
            }
        )
    return {
        "instance_id": instance.get("instance_id"),
        "review_id": instance.get("review_id"),
        "data_type": _data_type(instance),
        "selection_group": selection_group,
        "audit_decision": "include",
        "audit_reason": "all gold rows have source_support status=supported_by_current_inputs, include_in_primary_eval=true, and no missing key gold values",
        "article_ids": instance.get("article_ids") or [],
        "gold_row_support": rows,
    }


def _select_instances(*, instances: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or len(instances) <= limit:
        return list(instances)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for instance in sorted(instances, key=_instance_sort_key):
        buckets[_data_type(instance)].append(instance)
    quotas = _bucket_quotas(buckets=buckets, limit=limit)
    selected: list[dict[str, Any]] = []
    for bucket_name in sorted(buckets):
        selected.extend(_round_robin_by_review(instances=buckets[bucket_name], limit=quotas[bucket_name]))
    if len(selected) < limit:
        seen = {str(item["instance_id"]) for item in selected}
        leftovers = [instance for instance in sorted(instances, key=_instance_sort_key) if str(instance["instance_id"]) not in seen]
        selected.extend(leftovers[: limit - len(selected)])
    return selected[:limit]


def _bucket_quotas(*, buckets: dict[str, list[dict[str, Any]]], limit: int) -> dict[str, int]:
    total = sum(len(items) for items in buckets.values())
    raw: dict[str, float] = {}
    floors: dict[str, int] = {}
    for name, items in buckets.items():
        share = (len(items) / total) * limit if total else 0.0
        raw[name] = share
        floors[name] = min(len(items), int(math.floor(share)))
    assigned = sum(floors.values())
    remainder = max(0, limit - assigned)
    for name, _ in sorted(
        raw.items(),
        key=lambda item: (item[1] - math.floor(item[1]), len(buckets[item[0]])),
        reverse=True,
    ):
        if remainder <= 0:
            break
        if floors[name] >= len(buckets[name]):
            continue
        floors[name] += 1
        remainder -= 1
    return floors


def _round_robin_by_review(*, instances: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for instance in instances:
        grouped[str(instance.get("review_id") or "")].append(instance)
    ordered_reviews = sorted(grouped)
    for review_id in ordered_reviews:
        grouped[review_id].sort(key=_instance_sort_key)
    selected: list[dict[str, Any]] = []
    while len(selected) < limit:
        advanced = False
        for review_id in ordered_reviews:
            if len(selected) >= limit:
                break
            if not grouped[review_id]:
                continue
            selected.append(grouped[review_id].pop(0))
            advanced = True
        if not advanced:
            break
    return selected


def _data_type(instance: dict[str, Any]) -> str:
    value = (((instance.get("analysis_setting") or {}).get("data_type")) or "unknown")
    return str(value).strip().lower()


def _data_type_counts(instances: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for instance in instances:
        key = _data_type(instance)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _instance_sort_key(instance: dict[str, Any]) -> tuple[str, str]:
    return (str(instance.get("review_id") or ""), str(instance.get("instance_id") or ""))


def _ensure_shared_symlink(*, source_dataset: Path, output_dataset: Path) -> None:
    target = output_dataset / "shared"
    source_shared = source_dataset / "shared"
    if target.is_symlink() or target.exists():
        if target.is_symlink():
            if target.resolve() == source_shared.resolve():
                return
            target.unlink()
        elif target.is_dir():
            if any(target.iterdir()):
                return
            target.rmdir()
        else:
            return
    relative_source = os.path.relpath(source_shared.resolve(), start=output_dataset.resolve())
    target.symlink_to(relative_source, target_is_directory=True)


if __name__ == "__main__":
    main()
