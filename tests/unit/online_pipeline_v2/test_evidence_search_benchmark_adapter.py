from benchmark.online_pipeline_v2.EvidenceSearch.adapter.markdown import (
    render_evidence_search_markdown,
)
from benchmark.online_pipeline_v2.EvidenceSearch.experiments.repackage_search_v2 import (
    _upgrade_record,
)


def test_evidence_search_markdown_is_deterministic_and_uses_compact_sources() -> None:
    response = {
        "artifact_id": "review-1:evidence_search:v1",
        "status": "partial",
        "data": {
            "sources": [
                {
                    "source_name": "MEDLINE",
                    "platform": "PubMed",
                    "status": "succeeded",
                    "executed_at": "2026-07-27T00:00:00+00:00",
                    "result_count": 3,
                    "retrieved_count": 3,
                    "status_reason": None,
                },
                {
                    "source_name": "CENTRAL",
                    "platform": "Cochrane Library",
                    "status": "unavailable",
                    "executed_at": "2026-07-27T00:00:00+00:00",
                    "result_count": 0,
                    "retrieved_count": 0,
                    "status_reason": "No configured access.",
                },
            ],
            "summary": {
                "run_count": 2,
                "source_count": 2,
                "record_count": 3,
            },
            "package_ref": {
                "package_id": "package-1",
                "schema_version": "search-package.v2",
                "content_digest": "sha256:abc",
            },
        },
        "issues": [
            {
                "code": "source_unavailable",
                "severity": "warning",
                "message": "CENTRAL access is not configured.",
            }
        ],
    }
    instance = {
        "instance_id": "evidence_search_000001",
        "review_question": "Exercise for adults",
    }

    first = render_evidence_search_markdown(instance, response)
    second = render_evidence_search_markdown(instance, response)

    assert first == second
    assert "### 1. MEDLINE" in first
    assert "Executed strategy" not in first
    assert "### 2. CENTRAL" in first
    assert "3" in first
    assert "`package-1`" in first
    assert "`source_unavailable`" in first


def test_evidence_search_markdown_renders_missing_artifact() -> None:
    markdown = render_evidence_search_markdown(
        {
            "instance_id": "evidence_search_000002",
            "review_question": "A question",
        },
        {
            "artifact_id": "review-2:evidence_search:v1",
            "status": "blocked",
            "data": None,
            "issues": [
                {
                    "code": "no_usable_source",
                    "severity": "error",
                    "message": "No source was executable.",
                }
            ],
        },
    )

    assert "`blocked`" in markdown
    assert "No Evidence Search artifact was produced." in markdown
    assert "`no_usable_source`" in markdown


def test_v1_registry_record_migration_preserves_summary_as_source_data() -> None:
    migrated = _upgrade_record(
        {
            "source_name": "ClinicalTrials.gov",
            "platform": "ClinicalTrials.gov",
            "source_record_id": "NCT00000001",
            "abstract": "Registry brief summary.",
            "external_identifiers": ["NCT00000001", "SPONSOR-1"],
        }
    )

    assert migrated["source_record_type"] == "trial_registry_record"
    assert migrated["abstract"] is None
    assert migrated["source_data"] == {
        "brief_summary": "Registry brief summary."
    }
    assert migrated["external_identifiers"] == [
        {"scheme": "nct", "value": "NCT00000001"},
        {"scheme": "other", "value": "SPONSOR-1"},
    ]
