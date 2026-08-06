"""Application boundary for Evidence Synthesis."""

from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.use_cases._shared import (
    require_protocol_version,
)
from ebm_backend.online_pipeline_v2.application.ports.evidence_synthesis.synthesize import (
    SynthesizeEvidencePort,
)
from ebm_backend.online_pipeline_v2.domain.common import TaskInvocation, TaskWorkResult
from ebm_backend.online_pipeline_v2.domain.synthesis import EvidenceSynthesisInput


@dataclass(slots=True)
class ExecuteEvidenceSynthesis:
    synthesize_evidence: SynthesizeEvidencePort

    def execute(
        self,
        invocation: TaskInvocation[EvidenceSynthesisInput],
    ) -> TaskWorkResult:
        require_protocol_version(invocation, invocation.inputs.protocol)
        return self.synthesize_evidence.synthesize(
            invocation.inputs,
            invocation.context,
        )
