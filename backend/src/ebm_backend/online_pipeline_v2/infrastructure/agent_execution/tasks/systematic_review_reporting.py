"""Infrastructure execution spec for final Systematic Review composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Callable
from uuid import uuid4

from pydantic import TypeAdapter

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    ArtifactStatus,
    IssueSeverity,
    TaskContext,
    TaskWorkResult,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    SystematicReviewReportingInput,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskAccessMode,
    TaskExecutorPort,
    TaskRunRequest,
    WebAccessPolicy,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.schema import (
    strict_task_output_schema,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.systematic_review import (
    SystematicReviewAgentOutput,
    systematic_review_agent_output_adapter,
)


_OUTPUT = systematic_review_agent_output_adapter()
_PROTOCOL = TypeAdapter(ProtocolDraft)
_PROMPT = (
    "Compose the complete scientific Systematic Review draft under the "
    "compose-systematic-review Skill. Treat the staged evidence package as the "
    "closed scientific evidence set. Consult the Web only for current official "
    "or primary reporting and interpretation methodology. Do not retrieve new "
    "Studies, Reports, external reviews, completed-review answers, or hidden "
    "benchmark material."
)


def systematic_review_output_schema() -> dict[str, Any]:
    return strict_task_output_schema(_OUTPUT.json_schema())


@dataclass(slots=True)
class ComposeSystematicReviewTask:
    executor: TaskExecutorPort
    evidence_store: Any
    artifact_store: Any
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    timeout_seconds: float = 1800.0
    run_id_factory: Callable[[], str] = field(
        default=lambda: f"systematic-review-{uuid4().hex}",
        repr=False,
    )

    def compose(
        self,
        inputs: SystematicReviewReportingInput,
        context: TaskContext,
    ) -> TaskWorkResult:
        evidence = self.evidence_store.resolve(inputs.evidence_package.package_id)
        if evidence.package != inputs.evidence_package:
            raise ValueError("Systematic Review evidence reference is not authoritative")
        run_id = self.run_id_factory()
        binding = _binding(inputs, context)
        request = TaskRunRequest(
            run_id=run_id,
            prompt=_PROMPT,
            input_data={
                "review_id": context.review_id,
                "protocol_version": context.protocol_version,
                "protocol": _PROTOCOL.dump_python(inputs.protocol, mode="json"),
                "evidence_package": {
                    "package_id": inputs.evidence_package.package_id,
                    "schema_version": inputs.evidence_package.schema_version,
                    "review_path": inputs.evidence_package.review_path.value,
                    "path": "inputs/artifacts/systematic-review-evidence-package",
                },
                "binding": binding,
                "declared_tools": (),
            },
            input_artifacts={
                "systematic-review-evidence-package": evidence.directory,
            },
            output_schema=systematic_review_output_schema(),
            output_artifacts={},
            timeout_seconds=self.timeout_seconds,
            access_mode=TaskAccessMode.WORKSPACE_WRITE,
            enable_workspace_network=True,
            enable_web_search=True,
            web_access_policy=self.web_access_policy,
            task_name="systematic_review_reporting",
            run_record_digest_output_fields=("artifact",),
        )
        execution = self.executor.execute(
            request,
            output_adapter=_OUTPUT,
            error_context="Agent Systematic Review output is invalid",
        )
        return self._result(execution.output, binding, run_id, evidence)

    def _result(
        self,
        output: SystematicReviewAgentOutput,
        binding: dict[str, str],
        run_id: str,
        evidence,
    ) -> TaskWorkResult:
        if output.status is ArtifactStatus.COMPLETED:
            assert output.artifact is not None
            completed = self.artifact_store.persist(
                binding=binding,
                draft=output.artifact,
                evidence=evidence,
                warnings=output.warnings,
            )
            return TaskWorkResult(
                status=TaskWorkStatus.COMPLETED,
                artifact=completed,
                progress={"review_sections": len(output.artifact.sections)},
                issues=output.issues,
            )
        status = (
            TaskWorkStatus.BLOCKED
            if output.status is ArtifactStatus.BLOCKED
            else TaskWorkStatus.INCOMPLETE
        )
        issues = output.issues
        if status is TaskWorkStatus.BLOCKED and not any(
            item.severity is IssueSeverity.ERROR for item in issues
        ):
            issues += (
                ArtifactIssue(
                    code="systematic_review_blocked",
                    message=output.blocker or "Systematic Review composition is blocked",
                    severity=IssueSeverity.ERROR,
                ),
            )
        return TaskWorkResult(
            status=status,
            work_id=run_id,
            issues=issues,
            blocker=output.blocker,
        )


def _binding(
    inputs: SystematicReviewReportingInput,
    context: TaskContext,
) -> dict[str, str]:
    protocol = _PROTOCOL.dump_json(inputs.protocol)
    return {
        "review_id": context.review_id,
        "protocol_version": context.protocol_version,
        "protocol_digest": f"sha256:{sha256(protocol).hexdigest()}",
        "evidence_package_id": inputs.evidence_package.package_id,
        "evidence_package_digest": inputs.evidence_package.content_digest,
    }

