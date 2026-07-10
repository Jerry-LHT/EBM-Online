from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.online_pipeline import builders
from benchmark.online_pipeline.grade import builder as grade_builder
from benchmark.online_pipeline.grade.evaluation_io import load_domain_dataset


def test_grade_freeze_reuses_existing_raw_snapshot_without_upstream(tmp_path, monkeypatch):
    raw_root = tmp_path / "grade"
    legacy_root = raw_root / "source" / "legacy_grade_benchmark_v2"
    split_root = raw_root / "source" / "legacy_release_splits"
    (legacy_root / "intermediate").mkdir(parents=True)
    split_root.mkdir(parents=True)
    for name in ("04_sof_rows_cleaned.jsonl", "05_sof_gold_domains.jsonl"):
        (legacy_root / "intermediate" / name).write_text("{}\n", encoding="utf-8")
    for name in ("review_dev.txt", "review_test.txt"):
        (split_root / name).write_text("CD000001\n", encoding="utf-8")

    monkeypatch.setattr(grade_builder, "UPSTREAM_GRADE_ROOT", tmp_path / "missing_upstream")
    summary = grade_builder.freeze_raw_snapshot(raw_root=raw_root)

    assert summary["raw_data_snapshot_reused"] is True
    assert summary["upstream_missing"] is True
    manifest = json.loads((raw_root / "source_manifest.json").read_text(encoding="utf-8"))
    assert manifest["raw_data_snapshot_reused"] is True


def test_default_sources_use_new_grade_version():
    assert builders._resolve_source(module="grade", source="builtin_smoke") == "grade_v4"  # noqa: SLF001
    assert grade_builder.SOURCE_V3 == "grade_v4"
    assert grade_builder.LEGACY_SOURCE_V3 == "grade_v3"


def test_grade_v4_rejects_legacy_alignment_version(tmp_path):
    raw_root = tmp_path / "grade"
    alignment_dir = raw_root / "intermediate" / "alignment_v3"
    alignment_dir.mkdir(parents=True)
    (alignment_dir / "alignment_results.jsonl").write_text("", encoding="utf-8")
    (alignment_dir / "alignment_summary.json").write_text(
        json.dumps(
            {
                "builder_version": "online-pipeline-builder-v3-grade-alignment",
                "matched_row_count": 0,
                "input_row_count": 0,
                "workflow_row_universe_count": 0,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="requires 'online-pipeline-builder-v4-grade-alignment'"):
        grade_builder.load_source_v3(raw_root=raw_root, source=grade_builder.SOURCE_V3)

    assert grade_builder._alignment_version_is_current(  # noqa: SLF001
        raw_root=raw_root,
        alignment_name="alignment_v3",
        source=grade_builder.LEGACY_SOURCE_V3,
    )


def test_grade_alignment_prediction_cache_requires_task_hash(tmp_path):
    task = {
        "task_id": "row-setting::sample::setting",
        "task_type": "row_setting",
        "payload": {"candidate": "old"},
    }
    changed_task = {
        **task,
        "payload": {"candidate": "new"},
    }
    prediction = {
        "task_id": task["task_id"],
        "llm_status": "ok",
        **grade_builder._task_cache_metadata(task),  # noqa: SLF001
    }
    path = tmp_path / "predictions.jsonl"
    path.write_text(json.dumps(prediction) + "\n", encoding="utf-8")

    reused = grade_builder._load_existing_predictions(  # noqa: SLF001
        path,
        key_fields=("task_id",),
        allowed_keys={task["task_id"]},
        expected_task_metadata={task["task_id"]: grade_builder._task_cache_metadata(task)},  # noqa: SLF001
        reusable_statuses={"ok"},
    )
    rejected = grade_builder._load_existing_predictions(  # noqa: SLF001
        path,
        key_fields=("task_id",),
        allowed_keys={changed_task["task_id"]},
        expected_task_metadata={changed_task["task_id"]: grade_builder._task_cache_metadata(changed_task)},  # noqa: SLF001
        reusable_statuses={"ok"},
    )

    assert set(reused) == {task["task_id"]}
    assert rejected == {}


def test_grade_v4_requires_live_alignment_when_missing(tmp_path):
    with pytest.raises(RuntimeError, match="requires a live LLM alignment"):
        grade_builder.build_dataset_v3(
            dataset_name=grade_builder.SOURCE_V3,
            source=grade_builder.SOURCE_V3,
            raw_root=tmp_path / "grade",
        )


def test_grade_v4_dataset_loader_rejects_non_llm_alignment(tmp_path):
    dataset_dir = tmp_path / "risk_of_bias" / "datasets" / grade_builder.SOURCE_V3
    split_dir = dataset_dir / "splits" / "smoke"
    split_dir.mkdir(parents=True)
    (split_dir / "instances.jsonl").write_text("", encoding="utf-8")
    (split_dir / "gold.jsonl").write_text("", encoding="utf-8")
    (dataset_dir / "source_manifest.json").write_text(
        json.dumps({"source": grade_builder.SOURCE_V3, "builder_version": grade_builder.BUILDER_VERSION_V3}),
        encoding="utf-8",
    )
    (dataset_dir / "dataset_analysis.json").write_text(
        json.dumps({"builder_version": grade_builder.ALIGNMENT_BUILDER_VERSION_V3, "mode": "dry_run"}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="mode='llm'"):
        load_domain_dataset(split_dir)
