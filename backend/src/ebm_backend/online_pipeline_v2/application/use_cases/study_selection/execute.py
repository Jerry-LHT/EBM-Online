from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.use_cases._shared import (
    finish_artifact,
    require_protocol_version,
)
from ebm_backend.online_pipeline_v2.application.use_cases.study_selection.select_studies import (
    SelectStudies,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactEnvelope,
    DomainValidationError,
    TaskInvocation,
    TaskName,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    StudySelectionArtifact,
    StudySelectionInput,
)


@dataclass(slots=True)
class ExecuteStudySelection:
    select_studies: SelectStudies

    def execute(
        self,
        invocation: TaskInvocation[StudySelectionInput],
    ) -> ArtifactEnvelope[StudySelectionArtifact]:
        inputs = invocation.inputs
        require_protocol_version(invocation, inputs.protocol)
        package_ref = inputs.search.package_ref
        if package_ref is None:
            raise DomainValidationError(
                "Study Selection requires a persisted Search Package"
            )
        if package_ref.review_id != invocation.context.review_id:
            raise DomainValidationError("Search Package review_id does not match")
        if package_ref.protocol_version != invocation.context.protocol_version:
            raise DomainValidationError(
                "Search Package Protocol version does not match"
            )
        completion = self.select_studies.execute(
            inputs.protocol,
            inputs.search,
            invocation.context,
        )
        return finish_artifact(
            invocation,
            TaskName.STUDY_SELECTION,
            completion,
        )
