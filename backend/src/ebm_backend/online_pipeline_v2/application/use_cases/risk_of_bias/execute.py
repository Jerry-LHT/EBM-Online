from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.use_cases._shared import (
    finish_artifact,
)
from ebm_backend.online_pipeline_v2.application.use_cases.risk_of_bias.assess import (
    AssessRiskOfBias,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactEnvelope,
    DomainValidationError,
    TaskInvocation,
    TaskName,
)
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasArtifact,
    RiskOfBiasInput,
)


@dataclass(slots=True)
class ExecuteRiskOfBias:
    assess_risk_of_bias: AssessRiskOfBias

    def execute(
        self,
        invocation: TaskInvocation[RiskOfBiasInput],
    ) -> ArtifactEnvelope[RiskOfBiasArtifact]:
        inputs = invocation.inputs
        if inputs.protocol.version != invocation.context.protocol_version:
            raise DomainValidationError(
                "Risk of Bias Protocol version does not match"
            )
        package_ref = inputs.selection.package_ref
        if package_ref.review_id != invocation.context.review_id:
            raise DomainValidationError("Selection Package review_id does not match")
        if package_ref.protocol_version != invocation.context.protocol_version:
            raise DomainValidationError(
                "Selection Package Protocol version does not match"
            )
        collection = inputs.study_data_collection
        if collection.review_id != invocation.context.review_id:
            raise DomainValidationError(
                "Study Data Collection review_id does not match"
            )
        if collection.protocol_version != invocation.context.protocol_version:
            raise DomainValidationError(
                "Study Data Collection Protocol version does not match"
            )
        if collection.task is not TaskName.STUDY_DATA_COLLECTION:
            raise DomainValidationError(
                "Risk of Bias requires a Study Data Collection artifact"
            )
        completion = self.assess_risk_of_bias.execute(
            inputs,
            invocation.context,
        )
        return finish_artifact(
            invocation,
            TaskName.RISK_OF_BIAS,
            completion,
        )
