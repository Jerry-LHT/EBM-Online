"""Single professional port for Study Data Collection."""

from __future__ import annotations

from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.common import TaskContext, TaskWorkResult
from ebm_backend.online_pipeline_v2.domain.study_data_collection import (
    StudyDataCollectionInput,
)


class CollectStudyDataPort(Protocol):
    def collect(
        self,
        inputs: StudyDataCollectionInput,
        context: TaskContext,
    ) -> TaskWorkResult: ...
