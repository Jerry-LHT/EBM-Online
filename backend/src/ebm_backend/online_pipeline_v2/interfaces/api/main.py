"""Independent FastAPI application for Online EBM Pipeline v2."""

from fastapi import FastAPI

from ebm_backend.online_pipeline_v2.interfaces.api.routes import router
from ebm_backend.online_pipeline_v2.interfaces.api.review_runs import (
    router as review_runs_router,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Online EBM Pipeline V2",
        version="2.0.0",
        description=(
            "Skill-driven task APIs and persistent Review Run orchestration "
            "for Online EBM Pipeline v2, including final SR/Data Package "
            "publication."
        ),
    )
    app.include_router(router)
    app.include_router(review_runs_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "online-pipeline-v2"}

    return app


app = create_app()
