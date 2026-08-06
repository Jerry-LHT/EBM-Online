from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.common import TaskCompletion, TaskContext
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft
from ebm_backend.online_pipeline_v2.domain.search import EvidenceSearchArtifact, EvidenceSearchInput


class EvidenceSearchPort(Protocol):
    """Task-level boundary for the professional Evidence Search executor."""

    def search(
        self,
        protocol: ProtocolDraft,
        context: TaskContext,
        inputs: EvidenceSearchInput | None = None,
    ) -> TaskCompletion[EvidenceSearchArtifact]: ...
