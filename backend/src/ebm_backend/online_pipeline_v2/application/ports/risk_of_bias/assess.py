from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.common import TaskCompletion, TaskContext
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasArtifact,
    RiskOfBiasInput,
)


class AssessRiskOfBiasPort(Protocol):
    def assess(
        self,
        inputs: RiskOfBiasInput,
        context: TaskContext,
    ) -> TaskCompletion[RiskOfBiasArtifact]: ...
