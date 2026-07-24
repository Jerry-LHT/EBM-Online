"""FastAPI application entry point for the Online EBM module backend."""

from __future__ import annotations

from fastapi import FastAPI

from ebm_backend.online_pipeline.interfaces.api.routes_modules import router as modules_router
from ebm_backend.online_pipeline.interfaces.api.routes_workflow import (
    router as workflow_router,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Online EBM Pipeline",
        version="1.0.0",
        description=(
            "Module-level APIs for the seven implemented Online EBM stages and "
            "a complete evidence-chain workflow endpoint."
        ),
    )
    app.include_router(modules_router)
    app.include_router(workflow_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
