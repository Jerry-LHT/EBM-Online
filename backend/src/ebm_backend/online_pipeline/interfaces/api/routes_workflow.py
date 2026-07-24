"""Complete Online EBM evidence-chain API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ebm_backend.online_pipeline.application.use_cases.build_evidence_package import (
    BuildEvidencePackage,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.screening import ScreeningEvidenceScope
from ebm_backend.online_pipeline.domain.serialization import from_jsonable, to_jsonable
from ebm_backend.online_pipeline.domain.workflow import OnlineEBMWorkflowResult
from ebm_backend.online_pipeline.application.ports.workflow_persistence import (
    WorkflowRunCorruptError,
    WorkflowRunNotFoundError,
)
from ebm_backend.online_pipeline.interfaces.api.dependencies import (
    get_online_workflow_use_case_for_api,
    get_workflow_run_use_case_for_api,
)
from ebm_backend.online_pipeline.interfaces.api.request_schemas import (
    OnlineEBMWorkflowRequest,
)


router = APIRouter(tags=["workflow"])


@router.post("/workflow")
def run_online_ebm_workflow(
    payload: OnlineEBMWorkflowRequest,
) -> dict[str, object]:
    constraints = WorkflowConstraints(
        study_design="RCT" if payload.rct_only else "",
        publication_year_range=_optional_text(payload.publication_year_range),
    )
    retrieval_config = ModuleRunConfig(
        max_candidates_per_source=payload.max_candidates_per_source,
        max_results_per_source=payload.max_results_per_source,
        constraints=constraints,
    )
    try:
        use_case = get_online_workflow_use_case_for_api(
            source_names=list(payload.source_names),
            evidence_scope=ScreeningEvidenceScope.FULL_TEXT,
        )
    except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "workflow_configuration_unavailable",
                "message": "The Online EBM workflow could not be configured.",
            },
        ) from exc
    result = use_case.execute(
        review_id=payload.review_id.strip(),
        question_text=payload.question_text.strip(),
        constraints=constraints,
        retrieval_config=retrieval_config,
        expand_outcomes=payload.expand_outcomes,
    )
    return to_jsonable(BuildEvidencePackage().execute(result=result))


@router.get("/workflow/runs/{run_id}")
def get_online_ebm_workflow_run(run_id: str) -> dict[str, object]:
    return _load_workflow_run(run_id)


@router.get("/workflow/runs/{run_id}/evidence-package")
def get_online_ebm_evidence_package(run_id: str) -> dict[str, object]:
    persisted = _load_workflow_run(run_id)
    try:
        result = from_jsonable(persisted, OnlineEBMWorkflowResult)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "workflow_run_corrupt",
                "message": "The persisted workflow run could not be read safely.",
            },
        ) from exc
    return to_jsonable(BuildEvidencePackage().execute(result=result))


def _load_workflow_run(run_id: str) -> dict[str, object]:
    try:
        return get_workflow_run_use_case_for_api().execute(run_id=run_id)
    except WorkflowRunNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "workflow_run_not_found",
                "message": "The requested workflow run was not found.",
            },
        ) from exc
    except WorkflowRunCorruptError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "workflow_run_corrupt",
                "message": "The persisted workflow run could not be read safely.",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "workflow_run_invalid_id",
                "message": "The workflow run ID is invalid.",
            },
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "workflow_persistence_unavailable",
                "message": "Workflow persistence is temporarily unavailable.",
            },
        ) from exc


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None
