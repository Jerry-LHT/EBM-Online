from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.common import (
    TaskContext,
    TaskWorkResult,
)
from ebm_backend.online_pipeline_v2.domain.study_data import StudyResultsInput


class CollectResultsPort(Protocol):
    def collect(
        self,
        inputs: StudyResultsInput,
        context: TaskContext,
    ) -> TaskWorkResult: ...
