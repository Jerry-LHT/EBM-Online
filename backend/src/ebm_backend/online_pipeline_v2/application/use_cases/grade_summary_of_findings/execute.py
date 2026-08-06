"""Application boundary for GRADE with Summary of Findings."""

from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.ports.grade_summary_of_findings.grade_evidence import (
    GradeEvidencePort,
)
from ebm_backend.online_pipeline_v2.domain.common import TaskInvocation, TaskWorkResult
from ebm_backend.online_pipeline_v2.domain.grade import GradeSummaryOfFindingsInput


@dataclass(slots=True)
class ExecuteGradeSummaryOfFindings:
    grade_evidence: GradeEvidencePort

    def execute(
        self,
        invocation: TaskInvocation[GradeSummaryOfFindingsInput],
    ) -> TaskWorkResult:
        inputs = invocation.inputs
        if inputs.protocol.version != invocation.context.protocol_version:
            raise ValueError("GRADE Protocol version does not match invocation")
        package = inputs.evidence_package
        if package.review_id != invocation.context.review_id:
            raise ValueError("GRADE evidence package review_id does not match")
        if package.protocol_version != invocation.context.protocol_version:
            raise ValueError("GRADE evidence package Protocol version does not match")
        return self.grade_evidence.grade(inputs, invocation.context)
