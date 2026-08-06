from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.use_cases._shared import (
    finish_artifact,
    require_protocol_version,
)
from ebm_backend.online_pipeline_v2.application.use_cases.evidence_search.search_evidence import (
    SearchEvidence,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactEnvelope,
    TaskInvocation,
    TaskName,
)
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchArtifact,
    EvidenceSearchInput,
)


@dataclass(slots=True)
class ExecuteEvidenceSearch:
    search_evidence: SearchEvidence

    def execute(
        self,
        invocation: TaskInvocation[EvidenceSearchInput],
    ) -> ArtifactEnvelope[EvidenceSearchArtifact]:
        require_protocol_version(invocation, invocation.inputs.protocol)
        inputs = invocation.inputs
        completion = self.search_evidence.execute(
            inputs.protocol,
            invocation.context,
            inputs if inputs.mode.value != "initial" else None,
        )
        return finish_artifact(
            invocation,
            TaskName.EVIDENCE_SEARCH,
            completion,
        )
