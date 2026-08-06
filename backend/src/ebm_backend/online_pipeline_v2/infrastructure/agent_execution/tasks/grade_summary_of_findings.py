"""Infrastructure execution spec for GRADE with Summary of Findings."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from pydantic import TypeAdapter

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.schema import (
    strict_task_output_schema,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    IssueSeverity,
    TaskContext,
    TaskWorkResult,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.grade import (
    GradeProtocol,
    GradeSummaryOfFindingsInput,
    finalize_grade_artifact,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskAccessMode,
    TaskExecutorPort,
    TaskOutputError,
    TaskRunRequest,
    WebAccessPolicy,
)

from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.grade import (
    GradeAgentOutput,
    grade_agent_output_adapter,
)
from ebm_backend.online_pipeline_v2.infrastructure.grade.evidence_index import (
    synthesis_analysis_ids,
)
from ebm_backend.online_pipeline_v2.application.use_cases.grade_summary_of_findings.models import (
    GradeWorkBinding,
)
from ebm_backend.online_pipeline_v2.application.ports.repositories import (
    GradeArtifactRepository,
    GradeEvidenceRepository,
)


_OUTPUT = grade_agent_output_adapter()
_GRADE_PROTOCOL = TypeAdapter(GradeProtocol)
_PROMPT = (
    "Complete GRADE certainty assessment and Summary of Findings under the "
    "grade-evidence-and-build-sof Skill. Follow the complete staged Protocol "
    "context and immutable GRADE Evidence Package. You may consult current "
    "official methodology only to resolve details the Protocol leaves open. "
    "Do not search for studies, a target review, an existing Summary of "
    "Findings table, remembered completed-review answers, or hidden benchmark "
    "material."
)


def grade_output_schema() -> dict[str, Any]:
    return strict_task_output_schema(_OUTPUT.json_schema())


@dataclass(slots=True)
class GradeEvidenceTask:
    executor: TaskExecutorPort
    evidence_store: GradeEvidenceRepository
    artifact_store: GradeArtifactRepository
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    timeout_seconds: float = 1800.0
    run_id_factory: Callable[[], str] = field(
        default=lambda: f"grade-{uuid4().hex}",
        repr=False,
    )

    def grade(
        self,
        inputs: GradeSummaryOfFindingsInput,
        context: TaskContext,
    ) -> TaskWorkResult:
        snapshot = self.evidence_store.resolve(inputs.evidence_package.package_id)
        if snapshot.package != inputs.evidence_package:
            raise ValueError("GRADE evidence package reference is not authoritative")
        analysis_ids = synthesis_analysis_ids(snapshot.directory)
        binding = _binding(inputs, context)
        run_id, output = self._run(inputs, context, binding, snapshot.directory)
        return self._persist(output, binding, run_id, analysis_ids)

    def _run(
        self,
        inputs: GradeSummaryOfFindingsInput,
        context: TaskContext,
        binding: dict[str, str],
        evidence_directory: Path,
    ) -> tuple[str, GradeAgentOutput]:
        run_id = self.run_id_factory()
        request = TaskRunRequest(
            run_id=run_id,
            prompt=_PROMPT,
            input_data={
                "review_id": context.review_id,
                "protocol_version": context.protocol_version,
                "protocol": _GRADE_PROTOCOL.dump_python(inputs.protocol, mode="json"),
                "evidence_package": {
                    "package_id": inputs.evidence_package.package_id,
                    "schema_version": inputs.evidence_package.schema_version,
                    "path": "inputs/artifacts/grade-evidence-package",
                },
                "binding": binding,
                "declared_tools": (
                    {
                        "name": "sof-effects",
                        "path": "scripts/sof_effects.py",
                        "purpose": "calculate supported absolute effects",
                    },
                ),
            },
            input_artifacts={"grade-evidence-package": evidence_directory},
            output_schema=grade_output_schema(),
            output_artifacts={},
            timeout_seconds=self.timeout_seconds,
            access_mode=TaskAccessMode.WORKSPACE_WRITE,
            enable_workspace_network=True,
            enable_web_search=True,
            web_access_policy=self.web_access_policy,
            task_name="grade_summary_of_findings",
            run_record_digest_output_fields=("artifact",),
        )
        execution = self.executor.execute(
            request,
            output_adapter=_OUTPUT,
            error_context="Agent GRADE output is invalid",
        )
        return run_id, execution.output

    def _persist(
        self,
        output: GradeAgentOutput,
        binding: dict[str, str],
        run_id: str,
        analysis_ids: frozenset[str],
    ) -> TaskWorkResult:
        if output.status is TaskWorkStatus.COMPLETED:
            assert output.artifact is not None
            try:
                artifact = finalize_grade_artifact(
                    output.artifact,
                    known_synthesis_analysis_ids=analysis_ids,
                )
            except (ValueError, TypeError) as exc:
                raise TaskOutputError(f"Agent GRADE artifact is invalid: {exc}") from exc
            completed = self.artifact_store.persist(
                binding=binding,
                artifact=artifact,
                warnings=output.warnings,
            )
            return TaskWorkResult(
                status=TaskWorkStatus.COMPLETED,
                artifact=completed,
                progress={
                    "evidence_profiles": len(artifact.evidence_profiles),
                    "sof_tables": len(artifact.summary_of_findings),
                    "sof_rows": sum(
                        len(table.rows) for table in artifact.summary_of_findings
                    ),
                },
                issues=output.issues,
            )

        issues = output.issues
        if output.status is TaskWorkStatus.BLOCKED and not any(
            issue.severity is IssueSeverity.ERROR for issue in issues
        ):
            issues += (
                ArtifactIssue(
                    code="grade_work_blocked",
                    message=output.blocker or "GRADE work is blocked",
                    severity=IssueSeverity.ERROR,
                ),
            )
        return TaskWorkResult(
            status=output.status,
            work_id=run_id,
            issues=issues,
            blocker=output.blocker,
        )


def _binding(
    inputs: GradeSummaryOfFindingsInput,
    context: TaskContext,
) -> dict[str, str]:
    protocol = _GRADE_PROTOCOL.dump_json(inputs.protocol)
    binding = GradeWorkBinding(
        review_id=context.review_id,
        protocol_version=context.protocol_version,
        protocol_digest=f"sha256:{sha256(protocol).hexdigest()}",
        evidence_package_id=inputs.evidence_package.package_id,
        evidence_package_digest=inputs.evidence_package.content_digest,
    )
    return binding.model_dump(mode="json")
