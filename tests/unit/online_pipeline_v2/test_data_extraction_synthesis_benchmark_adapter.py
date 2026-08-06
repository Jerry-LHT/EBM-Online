"""Current Benchmark boundary tests for unified Study Data Collection."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.online_pipeline_v2.StudyDataCollection.adapter.run_manual import (
    _COLLECTION_SKILL,
    _REPORT_ACCESS_SKILL,
    _selection_summary,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_unified_benchmark_loads_one_parent_and_shared_report_skill() -> None:
    assert _COLLECTION_SKILL.name == "collect-study-data"
    assert (_COLLECTION_SKILL / "SKILL.md").is_file()
    assert _REPORT_ACCESS_SKILL.name == "find-and-read-reports"
    assert (_REPORT_ACCESS_SKILL / "SKILL.md").is_file()


def test_upstream_selection_summary_is_deterministic(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "record-screening.jsonl",
        [
            {
                "record_id": "r1",
                "duplicate_of_record_id": None,
                "screening_label": "excluded at title/abstract",
            },
            {
                "record_id": "r2",
                "duplicate_of_record_id": "r1",
                "screening_label": "duplicate",
            },
        ],
    )
    _write_jsonl(
        tmp_path / "reports.jsonl",
        [{"report_id": "report-1"}, {"report_id": "report-2"}],
    )
    _write_jsonl(
        tmp_path / "report-evidence.jsonl",
        [
            {"report_id": "report-1", "accessed": True},
            {"report_id": "report-2", "accessed": False},
        ],
    )
    _write_jsonl(
        tmp_path / "studies.jsonl",
        [{"study_id": "study-1"}, {"study_id": "study-2"}],
    )
    _write_jsonl(
        tmp_path / "study-decisions.jsonl",
        [
            {"study_id": "study-1", "classification": "included"},
            {"study_id": "study-2", "classification": "awaiting_classification"},
        ],
    )
    _write_jsonl(tmp_path / "conflicts.jsonl", [])

    summary = _selection_summary(tmp_path)

    assert summary.source_record_count == 2
    assert summary.duplicate_record_count == 1
    assert summary.title_abstract_excluded_count == 1
    assert summary.reports_sought_count == 2
    assert summary.reports_assessed_count == 1
    assert summary.reports_not_retrieved_count == 1
    assert summary.included_count == 1
    assert summary.awaiting_classification_count == 1
