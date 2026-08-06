from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.ports.study_characteristics.collect import (
    CollectStudyCharacteristicsPort,
)
from ebm_backend.online_pipeline_v2.domain.common import TaskCompletion, TaskContext
from ebm_backend.online_pipeline_v2.domain.selection import StudySelectionArtifact
from ebm_backend.online_pipeline_v2.domain.study_characteristics import (
    StudyCharacteristicsArtifact,
    StudyCharacteristicsProtocolContext,
)


@dataclass(slots=True)
class CollectStudyCharacteristics:
    port: CollectStudyCharacteristicsPort

    def execute(
        self,
        protocol_context: StudyCharacteristicsProtocolContext,
        selection: StudySelectionArtifact,
        context: TaskContext,
    ) -> TaskCompletion[StudyCharacteristicsArtifact]:
        return self.port.collect(
            protocol_context,
            selection,
            context,
        )
