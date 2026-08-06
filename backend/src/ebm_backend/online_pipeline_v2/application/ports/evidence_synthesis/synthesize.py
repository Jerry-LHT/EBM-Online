from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.common import (
    TaskContext,
    TaskWorkResult,
)
from ebm_backend.online_pipeline_v2.domain.synthesis import EvidenceSynthesisInput


class SynthesizeEvidencePort(Protocol):
    def synthesize(
        self,
        inputs: EvidenceSynthesisInput,
        context: TaskContext,
    ) -> TaskWorkResult: ...
