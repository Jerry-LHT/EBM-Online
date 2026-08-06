from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.common import TaskCompletion, TaskContext
from ebm_backend.online_pipeline_v2.domain.search import EvidenceSearchPublicArtifact
from ebm_backend.online_pipeline_v2.domain.selection import (
    StudySelectionArtifact,
    StudySelectionProtocol,
)


class SelectStudiesPort(Protocol):
    """Task-level boundary for the professional Study Selection executor."""

    def select(
        self,
        protocol: StudySelectionProtocol,
        search: EvidenceSearchPublicArtifact,
        context: TaskContext,
    ) -> TaskCompletion[StudySelectionArtifact]: ...
