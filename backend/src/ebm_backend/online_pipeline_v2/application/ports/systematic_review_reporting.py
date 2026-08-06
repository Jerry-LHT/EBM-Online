"""Application port for scientific Systematic Review composition."""

from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.common import TaskContext, TaskWorkResult
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    SystematicReviewReportingInput,
)


class ComposeSystematicReviewPort(Protocol):
    def compose(
        self,
        inputs: SystematicReviewReportingInput,
        context: TaskContext,
    ) -> TaskWorkResult: ...
