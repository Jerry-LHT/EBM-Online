"""Application boundary for the complete Study Data Collection task."""

from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.ports.study_data_collection.collect import (
    CollectStudyDataPort,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    DomainValidationError,
    TaskInvocation,
    TaskWorkResult,
)
from ebm_backend.online_pipeline_v2.domain.study_data_collection import (
    StudyDataCollectionInput,
)


@dataclass(slots=True)
class ExecuteStudyDataCollection:
    collect_study_data: CollectStudyDataPort

    def execute(
        self,
        invocation: TaskInvocation[StudyDataCollectionInput],
    ) -> TaskWorkResult:
        inputs = invocation.inputs
        context = invocation.context
        if inputs.protocol.version != context.protocol_version:
            raise DomainValidationError(
                "Study Data Collection Protocol version does not match"
            )
        selection = inputs.selection.package_ref
        if selection.review_id != context.review_id:
            raise DomainValidationError("Selection Package review_id does not match")
        if selection.protocol_version != context.protocol_version:
            raise DomainValidationError(
                "Selection Package Protocol version does not match"
            )
        return self.collect_study_data.collect(inputs, context)
