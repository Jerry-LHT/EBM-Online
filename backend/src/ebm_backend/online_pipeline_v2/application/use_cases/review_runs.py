"""Create, advance, inspect, and resume persistent Review Runs."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable
from uuid import uuid4

from ebm_backend.online_pipeline_v2.application.ports.review_runs import (
    ReviewRunRepository,
    ReviewRunStageExecutor,
)
from ebm_backend.online_pipeline_v2.domain.review_run import (
    CreateReviewRun,
    ReviewRun,
    ReviewRunStatus,
    ReviewStage,
    utc_now,
)


class ReviewRunService:
    def __init__(
        self,
        *,
        repository: ReviewRunRepository,
        executor: ReviewRunStageExecutor,
        run_id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._run_id_factory = run_id_factory

    def create(self, request: CreateReviewRun) -> ReviewRun:
        now = utc_now()
        run = ReviewRun(
            run_id=self._run_id_factory(),
            request=request,
            status=ReviewRunStatus.QUEUED,
            stage=ReviewStage.Q2PROTOCOL,
            created_at=now,
            updated_at=now,
        ).event(code="run_created", message="Review Run was queued.")
        self._repository.create(run)
        return run

    def get(self, run_id: str) -> ReviewRun:
        return self._repository.load(run_id)

    def resume(self, run_id: str) -> ReviewRun:
        run = self._repository.load(run_id)
        if run.status is ReviewRunStatus.COMPLETED:
            return run
        if run.status in {ReviewRunStatus.QUEUED, ReviewRunStatus.RUNNING}:
            return run
        resumed = replace(run, diagnostic=None).event(
            code="run_resumed",
            message="Review Run was explicitly resumed.",
            status=ReviewRunStatus.QUEUED,
        )
        self._repository.save(resumed)
        return resumed

    def run(self, run_id: str) -> ReviewRun:
        run = self._repository.load(run_id)
        if run.status not in {
            ReviewRunStatus.QUEUED,
            ReviewRunStatus.INTERRUPTED,
        }:
            return run
        run = run.event(
            code="run_started",
            message="Background execution started.",
            status=ReviewRunStatus.RUNNING,
        )
        self._repository.save(run)
        try:
            for _ in range(16):
                if run.status is not ReviewRunStatus.RUNNING:
                    break
                previous = (run.stage, len(run.events))
                run = self._executor.advance(run)
                self._repository.save(run)
                current = (run.stage, len(run.events))
                if current == previous:
                    raise RuntimeError("Review Run executor made no progress")
            else:
                raise RuntimeError("Review Run exceeded its transition limit")
        except Exception as exc:
            run = replace(
                run,
                diagnostic={
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:2000],
                    "stage": run.stage.value,
                },
            ).event(
                code="stage_failed",
                message=f"{type(exc).__name__}: {str(exc)[:1000]}",
                status=ReviewRunStatus.FAILED,
            )
            self._repository.save(run)
        return run
