"""Cross-task tests for the Agent artifact validation convention."""

from __future__ import annotations

from pathlib import Path

import pytest

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution import (
    artifact_schemas as schemas,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskOutputError,
)


_SKILLS_ROOT = (
    Path(__file__).resolve().parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/"
    "agent_execution/skills"
)


def test_skill_schema_snapshots_match_pydantic_contracts() -> None:
    exports = (
        (
            schemas.SOURCE_RESULT_V2,
            _SKILLS_ROOT / "evidence_search/evidence-search/references/"
            "source-result.v2.schema.json",
        ),
        (
            schemas.SELECTION_COLLECTIONS_V2,
            _SKILLS_ROOT / "study_selection/select-studies/references/"
            "selection-collections.v2.schema.json",
        ),
        (
            schemas.STUDY_DATA_COLLECTION_DOCUMENT_V3,
            _SKILLS_ROOT / "study_data_collection/collect-study-data/references/"
            "study-data-collection-document.v3.schema.json",
        ),
        (
            schemas.RISK_OF_BIAS_DOCUMENT_V4,
            _SKILLS_ROOT / "risk_of_bias/risk-of-bias/references/"
            "risk-of-bias-document.v4.schema.json",
        ),
        (
            schemas.EVIDENCE_SYNTHESIS_DOCUMENT_V3,
            _SKILLS_ROOT / "evidence_synthesis/synthesize-evidence/references/"
            "evidence-synthesis-document.v3.schema.json",
        ),
    )

    for contract, path in exports:
        assert path.read_text(encoding="utf-8") == (contract.canonical_schema_json())


def test_nested_search_shape_failure_has_stable_redacted_diagnostic() -> None:
    value = _source_result()
    relation = value["records"][0]["related_records"][0]
    relation["type"] = relation.pop("relation_type")

    with pytest.raises(TaskOutputError) as captured:
        schemas.SOURCE_RESULT_V2.validate_python(
            value,
            artifact="probe source result",
        )

    error = captured.value
    diagnostic = error.diagnostic()
    assert diagnostic["error_code"] == "artifact_schema_invalid"
    assert diagnostic["stage"] == "artifact_schema"
    assert diagnostic["artifact"] == "probe source result"
    assert diagnostic["location"] == "/records/0/related_records/0"
    assert diagnostic["contract_version"] == "source-result.v2"
    assert "RetractionIn" not in str(diagnostic)


def test_source_result_contract_constructs_typed_domain_values() -> None:
    result = schemas.SOURCE_RESULT_V2.validate_python(
        _source_result(),
        artifact="probe source result",
    )

    assert result.search_run.search_run_id == "run-1"
    assert result.records[0].source_record_type == "bibliographic_record"
    assert result.records[0].source_data == {}
    assert result.records[0].related_records[0].relation_type == "RetractionIn"


def test_schema_type_diagnostic_does_not_echo_rejected_value() -> None:
    value = _source_result()
    value["search_run"]["query"] = {"secret": "do-not-persist"}

    with pytest.raises(TaskOutputError) as captured:
        schemas.SOURCE_RESULT_V2.validate_python(
            value,
            artifact="probe source result",
        )

    diagnostic = captured.value.diagnostic()
    assert diagnostic["location"] == "/search_run/query"
    assert "do-not-persist" not in str(diagnostic)
    assert "expected JSON type" in diagnostic["message"]


def test_legacy_unstructured_error_diagnostic_does_not_echo_message() -> None:
    error = TaskOutputError("rejected value was SECRET-PAYLOAD")

    assert error.diagnostic() == {
        "error_code": "task_output_invalid",
        "message": "Task output did not satisfy its deterministic contract.",
    }


def _source_result() -> dict[str, object]:
    provenance = [{"source_id": "source-1", "source_type": "database"}]
    return {
        "schema_version": "source-result.v2",
        "search_run": {
            "search_run_id": "run-1",
            "source_name": "MEDLINE",
            "platform": "PubMed",
            "query": "intervention",
            "executed_at": "2026-07-30T00:00:00Z",
            "status": "succeeded",
            "result_count": 1,
            "retrieved_count": 1,
            "status_reason": None,
            "search_narrative": "Test search.",
            "provenance": provenance,
        },
        "records": [
            {
                "record_id": "record-1",
                "source_name": "MEDLINE",
                "platform": "PubMed",
                "source_record_id": "1",
                "source_record_type": "bibliographic_record",
                "source_data": {},
                "related_records": [
                    {
                        "relation_type": "RetractionIn",
                        "related_source_record_id": "2",
                    }
                ],
                "search_run_ids": ["run-1"],
                "provenance": provenance,
            }
        ],
    }
