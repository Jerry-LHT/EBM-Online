from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.ports.evidence_search.search_evidence import (
    EvidenceSearchPort,
)
from ebm_backend.online_pipeline_v2.domain.common import TaskCompletion, TaskContext
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft
from ebm_backend.online_pipeline_v2.domain.search import EvidenceSearchArtifact, EvidenceSearchInput


@dataclass(slots=True)
class SearchEvidence:
    port: EvidenceSearchPort

    def execute(
        self,
        protocol: ProtocolDraft,
        context: TaskContext,
        inputs: EvidenceSearchInput | None = None,
    ) -> TaskCompletion[EvidenceSearchArtifact]:
        if inputs is None:
            return self.port.search(protocol, context)
        return self.port.search(protocol, context, inputs)
