from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from ebm_backend.online_pipeline.interfaces.api.main import app as v1_app
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactStatus,
    ArtifactFile,
    CompletedArtifactRef,
    Provenance,
    TaskContext,
    TaskName,
    TaskWorkResult,
    TaskWorkStatus,
    build_artifact,
)
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft
from ebm_backend.online_pipeline_v2.domain.selection import (
    StudySelectionProtocol,
    study_selection_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchArtifact,
    Record,
    SearchPackageRef,
    SearchRun,
    SearchRunStatus,
    SearchSummary,
)
from ebm_backend.online_pipeline_v2.domain.study_data import (
    StudyResultsProtocol,
    study_results_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskOutputError,
)
from ebm_backend.online_pipeline_v2.interfaces.api import dependencies
from ebm_backend.online_pipeline_v2.interfaces.api.main import app
from ebm_backend.online_pipeline_v2.interfaces.api.schemas import (
    RiskOfBiasRequest,
    StudySelectionRequest,
)


client = TestClient(app)


EXPECTED_TASK_ROUTES = {
    "/v2/tasks/q2protocol",
    "/v2/tasks/evidence-search",
    "/v2/tasks/study-selection",
    "/v2/tasks/study-data-collection",
    "/v2/tasks/risk-of-bias",
    "/v2/tasks/evidence-synthesis",
    "/v2/tasks/grade-summary-of-findings",
    "/v2/tasks/systematic-review-reporting",
}


def _source() -> dict[str, str]:
    return {"source_id": "question-1", "source_type": "user_input"}


def test_v2_exposes_task_boundaries_and_review_runs() -> None:
    paths = {route.path for route in app.routes}

    assert EXPECTED_TASK_ROUTES <= paths
    assert "/workflow" not in paths
    assert "/v2/tasks/protocol-development" not in paths
    assert "/v2/tasks/study-characteristics" not in paths
    assert "/v2/tasks/study-data-collection/characteristics" not in paths
    assert "/v2/tasks/study-data-collection/results" not in paths


def test_health_is_independent_from_v1() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "online-pipeline-v2",
    }
    assert "/workflow" in {route.path for route in v1_app.routes}
    assert "/workflow" not in {route.path for route in app.routes}


def test_valid_task_returns_stable_unavailable_error() -> None:
    response = client.post(
        "/v2/tasks/q2protocol",
        json={
            "review_id": "review-1",
            "protocol_version": "protocol-1",
            "provenance": [_source()],
            "topic_text": "Does the intervention reduce mortality?",
            "topic_kind": "question",
            "standards": {
                "risk_of_bias_tool": "cochrane_rob_1",
            },
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
                "code": "task_executor_unavailable",
                "task": "q2protocol",
                "execution_status": "configuration_error",
                "message": "No executor adapter is configured for this v2 task.",
        }
    }


def test_schema_validation_is_422() -> None:
    response = client.post(
        "/v2/tasks/q2protocol",
        json={
            "review_id": "",
            "protocol_version": "protocol-1",
            "provenance": [],
            "topic_text": "",
            "topic_kind": "question",
        },
    )

    assert response.status_code == 422


def test_cross_artifact_identity_validation_is_400(protocol) -> None:
    response = client.post(
        "/v2/tasks/evidence-search",
        json={
            "review_id": "review-1",
            "protocol_version": "protocol-1",
            "provenance": [_source()],
            "protocol": {
                "artifact_id": "protocol-artifact-1",
                "schema_version": "q2protocol.v2",
                "review_id": "another-review",
                "protocol_version": "protocol-1",
                "task": "q2protocol",
                "status": "completed",
                "data": TypeAdapter(ProtocolDraft).dump_python(
                    protocol,
                    mode="json",
                ),
                "provenance": [_source()],
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_task_input"
    assert "review_id" in response.json()["detail"]["message"]


def test_evidence_search_response_exposes_package_not_inline_records(
    protocol,
    monkeypatch,
) -> None:
    provenance = (Provenance("question-1", "user_input"),)
    run = SearchRun(
        search_run_id="run-1",
        source_name="MEDLINE",
        platform="PubMed",
        query="complete executable query",
        executed_at="2026-07-31T00:00:00Z",
        status=SearchRunStatus.SUCCEEDED,
        result_count=1,
        retrieved_count=1,
        status_reason=None,
        search_narrative="Search development details.",
        provenance=provenance,
    )
    artifact = EvidenceSearchArtifact(
        search_runs=(run,),
        records=(
            Record(
                record_id="pubmed:1",
                source_name="MEDLINE",
                platform="PubMed",
                source_record_id="1",
                source_record_type="bibliographic_record",
                title="A trial",
                search_run_ids=("run-1",),
                provenance=provenance,
            ),
        ),
        summary=SearchSummary(1, 1, 1),
        package_ref=SearchPackageRef(
            package_id="search-package-1",
            review_id="review-1",
            protocol_version="protocol-1",
            schema_version="search-package.v2",
            content_digest="sha256:test",
        ),
    )
    envelope = build_artifact(
        context=TaskContext("review-1", "protocol-1"),
        task=TaskName.EVIDENCE_SEARCH,
        data=artifact,
        provenance=provenance,
        status=ArtifactStatus.COMPLETED,
    )
    monkeypatch.setattr(
        dependencies,
        "get_evidence_search_use_case",
        lambda: type(
            "UseCase",
            (),
            {"execute": lambda self, invocation: envelope},
        )(),
    )

    response = client.post(
        "/v2/tasks/evidence-search",
        json={
            "review_id": "review-1",
            "protocol_version": "protocol-1",
            "provenance": [_source()],
            "protocol": {
                "artifact_id": "protocol-artifact-1",
                "schema_version": "q2protocol.v2",
                "review_id": "review-1",
                "protocol_version": "protocol-1",
                "task": "q2protocol",
                "status": "completed",
                "data": TypeAdapter(ProtocolDraft).dump_python(
                    protocol,
                    mode="json",
                ),
                "provenance": [_source()],
            },
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {"sources", "summary", "package_ref"}
    assert data["summary"]["record_count"] == 1
    assert data["sources"][0]["source_name"] == "MEDLINE"
    assert "records" not in data
    assert "query" not in data["sources"][0]


def test_study_selection_request_uses_selection_protocol_view(protocol) -> None:
    selection_protocol = study_selection_protocol_from_draft(protocol)
    request = StudySelectionRequest.model_validate(
        {
            "review_id": "review-1",
            "protocol_version": "protocol-1",
            "provenance": [_source()],
            "protocol": TypeAdapter(StudySelectionProtocol).dump_python(
                selection_protocol,
                mode="json",
            ),
            "search": {
                "artifact_id": "search-1",
                "schema_version": "evidence-search.v2",
                "review_id": "review-1",
                "protocol_version": "protocol-1",
                "task": "evidence_search",
                "status": "completed",
                "data": {
                    "sources": [
                        {
                            "search_run_id": "run-1",
                            "source_name": "MEDLINE",
                            "platform": "Ovid",
                            "executed_at": "2026-07-28T00:00:00Z",
                            "status": "succeeded",
                            "result_count": 0,
                            "retrieved_count": 0,
                            "status_reason": None,
                        }
                    ],
                    "summary": {
                        "run_count": 1,
                        "source_count": 1,
                        "record_count": 0,
                    },
                    "package_ref": {
                        "package_id": "search-package-1",
                        "review_id": "review-1",
                        "protocol_version": "protocol-1",
                        "schema_version": "search-package.v2",
                        "content_digest": "sha256:test",
                    },
                },
                "provenance": [_source()],
            },
        }
    )

    assert request.protocol.review_question == protocol.review_question


def test_study_selection_request_rejects_q2protocol_envelope(protocol) -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StudySelectionRequest.model_validate(
            {
                "review_id": "review-1",
                "protocol_version": "protocol-1",
                "provenance": [_source()],
                "protocol": {
                    "artifact_id": "protocol-1",
                    "schema_version": "q2protocol.v2",
                    "review_id": "review-1",
                    "protocol_version": "protocol-1",
                    "task": "q2protocol",
                    "status": "completed",
                    "data": TypeAdapter(ProtocolDraft).dump_python(
                        protocol,
                        mode="json",
                    ),
                    "provenance": [_source()],
                },
                "search": {},
            }
        )


def test_risk_of_bias_request_uses_full_protocol_and_study_data(protocol) -> None:
    request = RiskOfBiasRequest.model_validate(
        {
            "review_id": "review-1",
            "protocol_version": "protocol-1",
            "provenance": [_source()],
            "protocol": {
                "artifact_id": "protocol-1",
                "schema_version": "q2protocol.v2",
                "review_id": "review-1",
                "protocol_version": "protocol-1",
                "task": "q2protocol",
                "status": "completed",
                "data": TypeAdapter(ProtocolDraft).dump_python(
                    protocol,
                    mode="json",
                ),
                "provenance": [_source()],
            },
            "selection": {
                "artifact_id": "selection-1",
                "schema_version": "selection-package.v4",
                "review_id": "review-1",
                "protocol_version": "protocol-1",
                "task": "study_selection",
                "status": "completed",
                "data": {
                    "package_ref": {
                        "package_id": "selection-package-1",
                        "review_id": "review-1",
                        "protocol_version": "protocol-1",
                        "schema_version": "selection-package.v4",
                        "content_digest": "sha256:selection",
                    },
                    "summary": {
                        "source_record_count": 1,
                        "duplicate_record_count": 0,
                        "records_screened_count": 1,
                        "title_abstract_excluded_count": 0,
                        "reports_sought_count": 1,
                        "reports_not_retrieved_count": 0,
                        "reports_assessed_count": 1,
                        "study_count": 1,
                        "included_count": 1,
                        "excluded_count": 0,
                        "awaiting_classification_count": 0,
                        "ongoing_count": 0,
                        "unresolved_conflict_count": 0,
                    },
                },
                "provenance": [_source()],
            },
            "study_data_collection": {
                "artifact_id": "study-data-1",
                "schema_version": "study-data-collection-artifact.v3",
                "review_id": "review-1",
                "protocol_version": "protocol-1",
                "task": "study_data_collection",
                "content_digest": "sha256:study-data",
                "files": [
                    {
                        "name": "review-1-study-data-collection.json",
                        "sha256": "sha256:file",
                        "size_bytes": 1,
                    }
                ],
                "counts": {"study_count": 1},
            },
        }
    )

    assert request.protocol.data == protocol
    assert request.study_data_collection.task is TaskName.STUDY_DATA_COLLECTION


def test_openapi_describes_only_task_level_v2_operations() -> None:
    paths = set(client.get("/openapi.json").json()["paths"])

    assert EXPECTED_TASK_ROUTES <= paths
    assert "/workflow" not in paths


def test_study_data_collection_children_are_not_public_routes(protocol) -> None:
    request = _results_request(protocol)

    for path in (
        "/v2/tasks/study-data-collection/characteristics",
        "/v2/tasks/study-data-collection/results",
    ):
        assert client.post(path, json=request).status_code == 404


def _results_request(protocol) -> dict:
    return {
        "review_id": "review-1",
        "protocol_version": "protocol-1",
        "provenance": [_source()],
        "protocol_context": TypeAdapter(StudyResultsProtocol).dump_python(
            study_results_protocol_from_draft(protocol),
            mode="json",
        ),
        "selection_package": {
            "package_id": "selection-1",
            "review_id": "review-1",
            "protocol_version": "protocol-1",
            "schema_version": "selection-package.v4",
            "content_digest": "sha256:selection",
        },
    }
