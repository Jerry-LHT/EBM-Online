"""Application ports for persistent Review Runs."""

from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.grade import GradeEvidencePackageRef
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft
from ebm_backend.online_pipeline_v2.domain.review_run import ReviewRun
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    EmptyReviewContext,
    SystematicReviewEvidencePackageRef,
)


class ReviewRunRepository(Protocol):
    def create(self, run: ReviewRun) -> None: ...
    def load(self, run_id: str) -> ReviewRun: ...
    def save(self, run: ReviewRun) -> None: ...


class ReviewRunStageExecutor(Protocol):
    def advance(self, run: ReviewRun) -> ReviewRun: ...


class GradeEvidencePackageBuilder(Protocol):
    def build(
        self,
        *,
        run: ReviewRun,
        protocol: ProtocolDraft,
    ) -> GradeEvidencePackageRef: ...


class SystematicReviewEvidencePackageBuilder(Protocol):
    def build(
        self,
        *,
        run: ReviewRun,
        protocol: ProtocolDraft,
        empty_review: EmptyReviewContext | None,
    ) -> SystematicReviewEvidencePackageRef: ...


class ReviewRunDispatcher(Protocol):
    def submit(self, run_id: str) -> bool: ...
