from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.ports.study_selection.select_studies import (
    SelectStudiesPort,
)
from ebm_backend.online_pipeline_v2.domain.common import TaskCompletion, TaskContext
from ebm_backend.online_pipeline_v2.domain.search import EvidenceSearchPublicArtifact
from ebm_backend.online_pipeline_v2.domain.selection import (
    StudySelectionArtifact,
    StudySelectionProtocol,
)


@dataclass(slots=True)
class SelectStudies:
    port: SelectStudiesPort

    def execute(
        self,
        protocol: StudySelectionProtocol,
        search: EvidenceSearchPublicArtifact,
        context: TaskContext,
    ) -> TaskCompletion[StudySelectionArtifact]:
        return self.port.select(protocol, search, context)
