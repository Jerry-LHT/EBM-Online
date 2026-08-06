"""HTTP API for persistent Review Runs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ebm_backend.online_pipeline_v2.infrastructure.persistence.filesystem import (
    jsonable,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.review_runs import (
    ReviewRunNotFound,
)
from ebm_backend.online_pipeline_v2.interfaces.api.dependencies import (
    get_review_run_dispatcher,
    get_review_run_service,
)
from ebm_backend.online_pipeline_v2.interfaces.api.schemas import (
    CreateReviewRunRequest,
)


router = APIRouter(prefix="/v2/review-runs", tags=["v2 review runs"])


@router.post("", status_code=202)
def create_review_run(request: CreateReviewRunRequest) -> JSONResponse:
    run = get_review_run_service().create(request.to_domain())
    get_review_run_dispatcher().submit(run.run_id)
    return JSONResponse(status_code=202, content=jsonable(run))


@router.get("/{run_id}")
def get_review_run(run_id: str) -> object:
    try:
        return jsonable(get_review_run_service().get(run_id))
    except ReviewRunNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "review_run_not_found", "run_id": run_id},
        ) from exc


@router.post("/{run_id}/resume", status_code=202)
def resume_review_run(run_id: str) -> JSONResponse:
    try:
        run = get_review_run_service().resume(run_id)
    except ReviewRunNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "review_run_not_found", "run_id": run_id},
        ) from exc
    get_review_run_dispatcher().submit(run.run_id)
    return JSONResponse(status_code=202, content=jsonable(run))


@router.get("/{run_id}/artifacts")
def get_review_run_artifacts(run_id: str) -> object:
    try:
        run = get_review_run_service().get(run_id)
    except ReviewRunNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "review_run_not_found", "run_id": run_id},
        ) from exc
    return {
        "run_id": run.run_id,
        "review_id": run.request.review_id,
        "protocol_version": run.request.protocol_version,
        "artifacts": run.artifacts,
    }
