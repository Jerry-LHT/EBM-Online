from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.ports.risk_of_bias.assess import (
    AssessRiskOfBiasPort,
)
from ebm_backend.online_pipeline_v2.domain.common import TaskCompletion, TaskContext
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasArtifact,
    RiskOfBiasInput,
)


@dataclass(slots=True)
class AssessRiskOfBias:
    port: AssessRiskOfBiasPort

    def execute(
        self,
        inputs: RiskOfBiasInput,
        context: TaskContext,
    ) -> TaskCompletion[RiskOfBiasArtifact]:
        return self.port.assess(inputs, context)
