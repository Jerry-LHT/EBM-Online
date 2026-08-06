from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.common import TaskCompletion, TaskContext
from ebm_backend.online_pipeline_v2.domain.selection import StudySelectionArtifact
from ebm_backend.online_pipeline_v2.domain.study_characteristics import (
    StudyCharacteristicsArtifact,
    StudyCharacteristicsProtocolContext,
)


class CollectStudyCharacteristicsPort(Protocol):
    def collect(
        self,
        protocol_context: StudyCharacteristicsProtocolContext,
        selection: StudySelectionArtifact,
        context: TaskContext,
    ) -> TaskCompletion[StudyCharacteristicsArtifact]: ...
