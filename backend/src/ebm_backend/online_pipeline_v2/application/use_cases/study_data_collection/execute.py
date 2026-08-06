"""Application boundary for the Results subtask."""

from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.use_cases._shared import (
    require_protocol_version,
)
from ebm_backend.online_pipeline_v2.application.ports.study_data_collection.collect_results import (
    CollectResultsPort,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    DomainValidationError,
    TaskInvocation,
    TaskWorkResult,
)
from ebm_backend.online_pipeline_v2.domain.study_data import StudyResultsInput


@dataclass(slots=True)
class ExecuteStudyResults:
    collect_results: CollectResultsPort

    def execute(
        self,
        invocation: TaskInvocation[StudyResultsInput],
    ) -> TaskWorkResult:
        inputs = invocation.inputs
        require_protocol_version(invocation, inputs.protocol)
        package = inputs.selection_package
        if package.review_id != invocation.context.review_id:
            raise DomainValidationError(
                "Selection Package review_id does not match"
            )
        if package.protocol_version != invocation.context.protocol_version:
            raise DomainValidationError(
                "Selection Package Protocol version does not match"
            )
        return self.collect_results.collect(inputs, invocation.context)
