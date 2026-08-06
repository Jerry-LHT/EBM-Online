"""Application boundary for final scientific Review composition."""

from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.ports.systematic_review_reporting import (
    ComposeSystematicReviewPort,
)
from ebm_backend.online_pipeline_v2.domain.common import TaskInvocation, TaskWorkResult
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    SystematicReviewReportingInput,
)


@dataclass(slots=True)
class ComposeSystematicReview:
    composer: ComposeSystematicReviewPort

    def execute(
        self,
        invocation: TaskInvocation[SystematicReviewReportingInput],
    ) -> TaskWorkResult:
        inputs = invocation.inputs
        if inputs.protocol.version != invocation.context.protocol_version:
            raise ValueError("Reporting Protocol version does not match invocation")
        if inputs.evidence_package.review_id != invocation.context.review_id:
            raise ValueError("Review evidence package review id does not match")
        if (
            inputs.evidence_package.protocol_version
            != invocation.context.protocol_version
        ):
            raise ValueError("Review evidence package Protocol version does not match")
        return self.composer.compose(inputs, invocation.context)
