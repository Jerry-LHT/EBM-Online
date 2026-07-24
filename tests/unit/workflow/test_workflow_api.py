from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.domain.workflow import OnlineEBMWorkflowResult
from ebm_backend.online_pipeline.interfaces.api import routes_workflow
from ebm_backend.online_pipeline.interfaces.api.main import app
from ebm_backend.online_pipeline.interfaces.api.request_schemas import (
    OnlineEBMWorkflowRequest,
)
from ebm_backend.online_pipeline.infrastructure.persistence import (
    WorkflowRunCorruptError,
    WorkflowRunNotFoundError,
)


class _Workflow:
    def __init__(self) -> None:
        self.kwargs = None

    def execute(self, **kwargs):
        self.kwargs = kwargs
        return OnlineEBMWorkflowResult(
            review_id=kwargs["review_id"],
            question_text=kwargs["question_text"],
            status="failed",
            question_pico=QuestionPICO(P=["adults"]),
            grade_status="not_run_due_to_upstream_failure",
        )


def test_complete_workflow_route_is_registered() -> None:
    assert "/workflow" in {route.path for route in app.routes}
    assert "/workflow/runs/{run_id}" in {route.path for route in app.routes}
    assert "/workflow/runs/{run_id}/evidence-package" in {
        route.path for route in app.routes
    }


def test_workflow_request_enforces_retrieval_limits() -> None:
    with pytest.raises(ValidationError):
        OnlineEBMWorkflowRequest(
            review_id="review-1",
            question_text="question",
            max_candidates_per_source=1,
            max_results_per_source=2,
        )

    with pytest.raises(ValidationError):
        OnlineEBMWorkflowRequest(
            review_id="review-1",
            question_text="question",
            max_candidates_per_source=10001,
        )


def test_workflow_api_returns_partial_evidence_chain(monkeypatch) -> None:
    workflow = _Workflow()
    captured = {}

    def build(**kwargs):
        captured.update(kwargs)
        return workflow

    monkeypatch.setattr(
        routes_workflow,
        "get_online_workflow_use_case_for_api",
        build,
    )
    response = routes_workflow.run_online_ebm_workflow(
        OnlineEBMWorkflowRequest(
            review_id=" review-1 ",
            question_text=" question ",
            source_names=["pubmed"],
            max_candidates_per_source=3,
            max_results_per_source=1,
            publication_year_range="2000-2025",
        )
    )

    assert captured["source_names"] == ["pubmed"]
    assert workflow.kwargs["review_id"] == "review-1"
    assert workflow.kwargs["question_text"] == "question"
    assert workflow.kwargs["constraints"].publication_year_range == "2000-2025"
    assert workflow.kwargs["retrieval_config"].max_results_per_source == 1
    assert "max_downstream_studies" not in workflow.kwargs
    assert response["schema_version"] == "evidence-package.v1"
    assert response["status"]["execution_status"] == "failed"
    assert response["status"]["evidence_status"] == "partial"
    assert response["status"]["ready_for_downstream"] is False
    assert response["protocol"]["question_pico"]["P"] == ["adults"]
    assert "grade_status" not in response
    assert "stages" not in response


class _GetWorkflowRun:
    def __init__(self, *, value=None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error

    def execute(self, **kwargs):
        if self.error is not None:
            raise self.error
        return self.value


def test_workflow_run_query_returns_persisted_result(monkeypatch) -> None:
    monkeypatch.setattr(
        routes_workflow,
        "get_workflow_run_use_case_for_api",
        lambda: _GetWorkflowRun(value={"run_id": "run-1", "status": "succeeded"}),
    )

    response = routes_workflow.get_online_ebm_workflow_run("run-1")

    assert response == {"run_id": "run-1", "status": "succeeded"}


def test_workflow_run_evidence_package_projects_persisted_result(monkeypatch) -> None:
    persisted = to_jsonable(
        OnlineEBMWorkflowResult(
            review_id="review-1",
            question_text="question",
            status="failed",
            run_id="run-1",
            question_pico=QuestionPICO(P=["adults"]),
        )
    )
    monkeypatch.setattr(
        routes_workflow,
        "get_workflow_run_use_case_for_api",
        lambda: _GetWorkflowRun(value=persisted),
    )

    response = routes_workflow.get_online_ebm_evidence_package("run-1")

    assert response["schema_version"] == "evidence-package.v1"
    assert response["run_id"] == "run-1"
    assert response["status"]["execution_status"] == "failed"
    assert response["protocol"]["question_pico"]["P"] == ["adults"]


def test_workflow_run_evidence_package_rejects_invalid_persisted_shape(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        routes_workflow,
        "get_workflow_run_use_case_for_api",
        lambda: _GetWorkflowRun(value={"run_id": "run-1"}),
    )

    with pytest.raises(HTTPException) as raised:
        routes_workflow.get_online_ebm_evidence_package("run-1")

    assert raised.value.status_code == 500
    assert raised.value.detail["code"] == "workflow_run_corrupt"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (WorkflowRunNotFoundError("missing"), 404, "workflow_run_not_found"),
        (WorkflowRunCorruptError("broken"), 500, "workflow_run_corrupt"),
        (ValueError("invalid"), 400, "workflow_run_invalid_id"),
        (OSError("disk"), 503, "workflow_persistence_unavailable"),
    ],
)
def test_workflow_run_query_maps_storage_errors(
    monkeypatch,
    error: Exception,
    status: int,
    code: str,
) -> None:
    monkeypatch.setattr(
        routes_workflow,
        "get_workflow_run_use_case_for_api",
        lambda: _GetWorkflowRun(error=error),
    )

    with pytest.raises(HTTPException) as raised:
        routes_workflow.get_online_ebm_workflow_run("run-1")

    assert raised.value.status_code == status
    assert raised.value.detail["code"] == code
