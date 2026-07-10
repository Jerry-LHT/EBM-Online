from __future__ import annotations

from benchmark.online_pipeline.meta_analysis import builder as meta_builder


def test_subtask2_audit_registry_labels_rows_and_candidate_sets() -> None:
    audit_registry = {
        "row::1": {
            "review_label": "suggested_for_eval",
            "audit_note": "manual note a",
        },
        "row::2": {
            "review_label": "source_data_missing_not_for_eval",
            "audit_note": "manual note b",
        },
    }

    labeled_rows = meta_builder._apply_subtask2_review_labels(  # noqa: SLF001
        rows=[
            {"row_id": "row::1", "study_id": "Study A"},
            {"row_id": "row::x", "study_id": "Study X"},
        ],
        audit_registry=audit_registry,
    )

    assert labeled_rows[0]["review_label"] == "suggested_for_eval"
    assert labeled_rows[0]["audit_note"] == "manual note a"
    assert "review_label" not in labeled_rows[1]

    candidate_meta = meta_builder._subtask2_candidate_set_review_label(  # noqa: SLF001
        study_rows=[
            {"row_id": "row::1"},
            {"row_id": "row::2"},
        ],
        audit_registry=audit_registry,
    )

    assert candidate_meta["review_label"] == "mixed_review_labels"
    assert candidate_meta["audit_note"] == "manual note a | manual note b"
