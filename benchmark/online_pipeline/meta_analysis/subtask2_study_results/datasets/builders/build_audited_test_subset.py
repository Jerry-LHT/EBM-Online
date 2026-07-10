"""Build an audited Subtask 2 test subset after false-positive review.

This script starts from an existing supported test split and removes only the
gold study-result rows that were manually audited as false-positive
source-support cases.

Rules:
- If an instance loses all gold rows after audited removals, drop the instance.
- If an instance still has at least one gold row, keep the instance and rewrite
  its gold payload to only the retained rows.
- Instance payloads are preserved as-is for provenance. The benchmark method
  still sees the original workflow input. The cleaned benchmark changes only
  the evaluation gold and documents the audited exclusions.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from benchmark.online_pipeline.shared.jsonl import read_jsonl, write_jsonl
from benchmark.online_pipeline.shared.report_utils import write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dataset", required=True)
    parser.add_argument("--source-split", required=True)
    parser.add_argument("--audit-json", required=True)
    parser.add_argument("--output-dataset", required=True)
    parser.add_argument("--output-split", required=True)
    args = parser.parse_args()

    summary = build_audited_subset(
        source_dataset=Path(args.source_dataset),
        source_split=args.source_split,
        audit_json=Path(args.audit_json),
        output_dataset=Path(args.output_dataset),
        output_split=args.output_split,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def build_audited_subset(
    *,
    source_dataset: Path,
    source_split: str,
    audit_json: Path,
    output_dataset: Path,
    output_split: str,
) -> dict[str, Any]:
    split_dir = source_dataset / "splits" / source_split
    instances = read_jsonl(split_dir / "instances.jsonl")
    gold_rows = read_jsonl(split_dir / "gold.jsonl")
    audit = json.loads(audit_json.read_text(encoding="utf-8"))

    remove_by_instance: dict[str, set[str]] = defaultdict(set)
    audit_rows = audit.get("rows") if isinstance(audit.get("rows"), list) else []
    for row in audit_rows:
        if str(row.get("audit_label") or "") != "confirmed_false_positive_source_support":
            continue
        instance_id = str(row.get("instance_id") or "")
        study_id = str(row.get("study_id") or "")
        if instance_id and study_id:
            remove_by_instance[instance_id].add(study_id)

    kept_instances: list[dict[str, Any]] = []
    kept_gold: list[dict[str, Any]] = []
    audit_manifest_rows: list[dict[str, Any]] = []
    dropped_instance_ids: list[str] = []

    gold_by_id = {str(row["instance_id"]): row for row in gold_rows}
    for instance in instances:
        instance_id = str(instance["instance_id"])
        gold = gold_by_id[instance_id]
        rows = gold.get("study_result_rows") or []
        remove_studies = remove_by_instance.get(instance_id, set())
        filtered_rows = [row for row in rows if str(row.get("study_id") or "") not in remove_studies]

        audit_manifest_rows.append(
            {
                "instance_id": instance_id,
                "review_id": instance.get("review_id"),
                "original_gold_row_count": len(rows),
                "removed_gold_row_count": len(rows) - len(filtered_rows),
                "kept_gold_row_count": len(filtered_rows),
                "removed_study_ids": sorted(remove_studies),
                "status": "dropped_instance" if not filtered_rows else ("partial_row_removal" if remove_studies else "unchanged"),
            }
        )

        if not filtered_rows:
            dropped_instance_ids.append(instance_id)
            continue

        kept_instances.append(instance)
        kept_gold.append(
            {
                **gold,
                "study_result_rows": filtered_rows,
            }
        )

    output_split_dir = output_dataset / "splits" / output_split
    output_split_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_split_dir / "instances.jsonl", kept_instances, sort_keys=False)
    write_jsonl(output_split_dir / "gold.jsonl", kept_gold, sort_keys=False)
    write_jsonl(output_dataset / "instances.jsonl", kept_instances, sort_keys=False)
    write_jsonl(output_dataset / "gold.jsonl", kept_gold, sort_keys=False)
    _ensure_shared_symlink(source_dataset=source_dataset, output_dataset=output_dataset)

    summary = {
        "source_dataset": str(source_dataset),
        "source_split": source_split,
        "audit_json": str(audit_json),
        "output_dataset": str(output_dataset),
        "output_split": output_split,
        "input_instance_count": len(instances),
        "output_instance_count": len(kept_instances),
        "dropped_instance_count": len(dropped_instance_ids),
        "input_gold_row_count": sum(len((row.get("study_result_rows") or [])) for row in gold_rows),
        "output_gold_row_count": sum(len((row.get("study_result_rows") or [])) for row in kept_gold),
        "removed_gold_row_count": sum(len((row.get("study_result_rows") or [])) for row in gold_rows)
        - sum(len((row.get("study_result_rows") or [])) for row in kept_gold),
        "dropped_instance_ids": dropped_instance_ids,
    }
    write_json(output_dataset / "audit_clean_summary.json", summary)
    write_json(output_dataset / "audit_clean_manifest.json", {"rows": audit_manifest_rows})
    return summary


def _ensure_shared_symlink(*, source_dataset: Path, output_dataset: Path) -> None:
    source_shared = source_dataset / "shared"
    target_shared = output_dataset / "shared"
    if target_shared.exists() or target_shared.is_symlink():
        return
    relative_source = os.path.relpath(source_shared.resolve(), start=output_dataset.resolve())
    target_shared.symlink_to(relative_source, target_is_directory=True)


if __name__ == "__main__":
    main()
