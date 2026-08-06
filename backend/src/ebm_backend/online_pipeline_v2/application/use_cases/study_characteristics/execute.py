from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.use_cases._shared import (
    finish_artifact,
)
from ebm_backend.online_pipeline_v2.application.use_cases.study_characteristics.collect import (
    CollectStudyCharacteristics,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactEnvelope,
    DomainValidationError,
    TaskInvocation,
    TaskName,
)
from ebm_backend.online_pipeline_v2.domain.study_characteristics import (
    StudyCharacteristicsArtifact,
    StudyCharacteristicsInput,
)


@dataclass(slots=True)
class ExecuteStudyCharacteristics:
    collect_characteristics: CollectStudyCharacteristics

    def execute(
        self,
        invocation: TaskInvocation[StudyCharacteristicsInput],
    ) -> ArtifactEnvelope[StudyCharacteristicsArtifact]:
        inputs = invocation.inputs
        if (
            inputs.protocol_context.protocol_version
            != invocation.context.protocol_version
        ):
            raise DomainValidationError(
                "Characteristics Protocol context version does not match"
            )
        package_ref = inputs.selection.package_ref
        if package_ref.review_id != invocation.context.review_id:
            raise DomainValidationError("Selection Package review_id does not match")
        if package_ref.protocol_version != invocation.context.protocol_version:
            raise DomainValidationError(
                "Selection Package Protocol version does not match"
            )
        completion = self.collect_characteristics.execute(
            inputs.protocol_context,
            inputs.selection,
            invocation.context,
        )
        return finish_artifact(
            invocation,
            TaskName.STUDY_DATA_COLLECTION,
            completion,
        )
