from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.common import TaskContext, TaskWorkResult
from ebm_backend.online_pipeline_v2.domain.grade import GradeSummaryOfFindingsInput


class GradeEvidencePort(Protocol):
    def grade(
        self,
        inputs: GradeSummaryOfFindingsInput,
        context: TaskContext,
    ) -> TaskWorkResult: ...
