"""Single-Agent execution of adaptive, result-linked Risk of Bias."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ebm_backend.online_pipeline_v2.application.ports.repositories import (
    RiskOfBiasPackageRepository,
    SelectionPackageRepository,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    ArtifactStatus,
    IssueSeverity,
    Provenance,
    TaskCompletion,
    TaskContext,
)
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasArtifact,
    RiskOfBiasBinding,
    RiskOfBiasDocumentV4,
    RiskOfBiasInput,
    RiskOfBiasReviewProcess,
    RiskOfBiasSummary,
)
from ebm_backend.online_pipeline_v2.domain.study_data_collection import (
    StudyDataCollectionProtocol,
    study_data_collection_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskAccessMode,
    TaskExecutorPort,
    TaskOutputError,
    TaskRunRequest,
    TaskRunResult,
    WebAccessPolicy,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.schema import (
    strict_task_output_schema,
)


_PROTOCOL_ADAPTER = TypeAdapter(ProtocolDraft)
_STUDY_DATA_PROTOCOL_ADAPTER = TypeAdapter(StudyDataCollectionProtocol)
_PROMPT = (
    "Complete the Risk of Bias task under the risk-of-bias Skill in "
    "one Agent execution. Treat the Protocol as the methodological constraint; "
    "retrieve and inspect the applicable official authority yourself. Select "
    "Protocol-relevant targets from the supplied authoritative Study Data "
    "Collection document and bind every assessment to its Study Result ids. "
    "When no method-applicable Result exists, do not invent a target; account "
    "for the Included Study in explicit unassessed coverage. "
    "Start from persisted upstream Report locators and discoveries, supplement "
    "them only when the current evidence need remains unmet, and use any lawful "
    "native reading path needed for study evidence. Return only "
    "the structured task output; do not use Benchmark Gold, a completed target "
    "review, runtime diagnostics, or model memory as scientific evidence."
)


class _AgentRiskOfBiasOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ArtifactStatus
    data: RiskOfBiasDocumentV4 | None
    issues: tuple[ArtifactIssue, ...] = ()
    execution_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_completion_contract(self) -> "_AgentRiskOfBiasOutput":
        if self.status is ArtifactStatus.BLOCKED:
            if self.data is not None:
                raise ValueError("blocked completion must not contain data")
            if not any(
                issue.severity is IssueSeverity.ERROR for issue in self.issues
            ):
                raise ValueError("blocked completion requires an error issue")
        elif self.data is None:
            raise ValueError("non-blocked completion requires data")
        if self.status is ArtifactStatus.PARTIAL and not self.issues:
            raise ValueError("partial completion requires an issue")
        return self


_OUTPUT_ADAPTER = TypeAdapter(_AgentRiskOfBiasOutput)


def risk_of_bias_output_schema() -> dict[str, Any]:
    return strict_task_output_schema(_OUTPUT_ADAPTER.json_schema())


@dataclass(slots=True)
class AssessRiskOfBiasTask:
    executor: TaskExecutorPort
    selection_package_store: SelectionPackageRepository
    study_data_collection_store: Any
    risk_of_bias_package_store: RiskOfBiasPackageRepository
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    timeout_seconds: float = 1800.0
    run_id_factory: Callable[[], str] = field(
        default=lambda: f"risk-of-bias-{uuid4().hex}",
        repr=False,
    )

    def assess(
        self,
        inputs: RiskOfBiasInput,
        context: TaskContext,
    ) -> TaskCompletion[RiskOfBiasArtifact]:
        selection_ref = inputs.selection.package_ref
        self.selection_package_store.validate(selection_ref)
        selection_root = self.selection_package_store.resolve_manifest(
            selection_ref
        ).parent
        collection = self.study_data_collection_store.resolve(
            inputs.study_data_collection
        )
        binding = _validated_binding(
            inputs,
            context,
            study_data_document=collection.document,
        )
        request = TaskRunRequest(
            run_id=self.run_id_factory(),
            prompt=_PROMPT,
            input_data={
                "review_id": context.review_id,
                "protocol_version": context.protocol_version,
                "review_mode": "single_agent",
                "protocol": _PROTOCOL_ADAPTER.dump_python(
                    inputs.protocol,
                    mode="json",
                ),
                "planned_standard": inputs.protocol.methods.risk_of_bias.tool,
                "selection_package": {
                    "path": "inputs/artifacts/selection-package",
                    "package_id": selection_ref.package_id,
                    "content_digest": selection_ref.content_digest,
                },
                "study_data_collection": {
                    "path": "inputs/artifacts/study-data-collection",
                    "artifact_id": collection.artifact.artifact_id,
                    "content_digest": collection.artifact.content_digest,
                    "authoritative_document": collection.document_path.name,
                },
                "binding": binding.model_dump(mode="json"),
                "declared_tools": [],
            },
            input_artifacts={
                "selection-package": selection_root,
                "study-data-collection": collection.public_directory,
            },
            output_schema=risk_of_bias_output_schema(),
            timeout_seconds=self.timeout_seconds,
            access_mode=TaskAccessMode.WORKSPACE_WRITE,
            enable_workspace_network=True,
            enable_web_search=True,
            web_access_policy=self.web_access_policy,
            task_name="risk_of_bias",
        )
        execution = self.executor.execute(
            request,
            output_adapter=_OUTPUT_ADAPTER,
            error_context="invalid Risk of Bias Agent output",
        )
        output = execution.output
        result = execution.result
        if output.status is ArtifactStatus.BLOCKED:
            return TaskCompletion(
                status=ArtifactStatus.BLOCKED,
                data=None,
                issues=output.issues,
                additional_provenance=_runtime_provenance(result),
            )
        assert output.data is not None
        document = output.data
        if document.binding != binding:
            raise TaskOutputError("Risk of Bias document binding does not match input")
        _validate_protocol_constraint(
            document,
            inputs.protocol.methods.risk_of_bias.tool,
        )
        _validate_agent_references(
            document,
            selection_root=selection_root,
            study_data_document=collection.document,
        )
        review_process = RiskOfBiasReviewProcess(agent_run_id=result.run_id)
        package_ref = self.risk_of_bias_package_store.persist(
            review_id=context.review_id,
            protocol_version=context.protocol_version,
            document=document,
            issues=output.issues,
            review_process=review_process,
        )
        summary = RiskOfBiasSummary(
            method_use_count=len(document.method_uses),
            target_count=len(document.targets),
            assessment_count=len(document.assessments),
            evidence_observation_count=len(document.evidence_observations),
            unassessed_result_count=len(document.coverage.unassessed_results),
            issue_count=len(output.issues),
        )
        artifact = RiskOfBiasArtifact(
            package_ref=package_ref,
            document=document,
            summary=summary,
            review_process=review_process,
        )
        return TaskCompletion(
            status=output.status,
            data=artifact,
            issues=output.issues,
            additional_provenance=_runtime_provenance(result),
        )


def _validated_binding(
    inputs: RiskOfBiasInput,
    context: TaskContext,
    *,
    study_data_document: Mapping[str, Any],
) -> RiskOfBiasBinding:
    protocol_bytes = _PROTOCOL_ADAPTER.dump_json(inputs.protocol)
    study_data_protocol = study_data_collection_protocol_from_draft(inputs.protocol)
    projection_bytes = _STUDY_DATA_PROTOCOL_ADAPTER.dump_json(study_data_protocol)
    complete_protocol_digest = f"sha256:{sha256(protocol_bytes).hexdigest()}"
    projection_digest = f"sha256:{sha256(projection_bytes).hexdigest()}"
    selection = inputs.selection.package_ref
    collection = inputs.study_data_collection
    expected_collection_binding = {
        "review_id": context.review_id,
        "protocol_version": context.protocol_version,
        "protocol_digest": projection_digest,
        "selection_package_id": selection.package_id,
        "selection_package_digest": selection.content_digest,
    }
    if study_data_document.get("binding") != expected_collection_binding:
        raise TaskOutputError(
            "Study Data Collection binding does not match the deterministic "
            "Protocol projection and Selection Package"
        )
    return RiskOfBiasBinding(
        review_id=context.review_id,
        protocol_version=context.protocol_version,
        complete_protocol_digest=complete_protocol_digest,
        study_data_protocol_projection_digest=projection_digest,
        selection_package_id=selection.package_id,
        selection_package_digest=selection.content_digest,
        study_data_collection_artifact_id=collection.artifact_id,
        study_data_collection_digest=collection.content_digest,
    )


def _validate_protocol_constraint(
    document: RiskOfBiasDocumentV4,
    planned_standard: str,
) -> None:
    for method in document.method_uses:
        if method.planned_standard != planned_standard:
            raise TaskOutputError(
                "Risk of Bias planned standard does not match the Protocol"
            )


def _validate_agent_references(
    document: RiskOfBiasDocumentV4,
    *,
    selection_root: Path,
    study_data_document: Mapping[str, Any],
) -> None:
    decisions = _read_jsonl(selection_root / "study-decisions.jsonl")
    included = {
        str(item["study_id"])
        for item in decisions
        if item.get("classification") == "included"
    }
    upstream_reports: dict[str, set[str]] = {study_id: set() for study_id in included}
    for link in _read_jsonl(selection_root / "study-report-links.jsonl"):
        study_id = str(link.get("study_id", ""))
        if study_id in upstream_reports:
            upstream_reports[study_id].add(str(link.get("report_id", "")))
    results_by_study: dict[str, set[str]] = {}
    for study in study_data_document.get("studies", []):
        study_id = str(study.get("study_id", ""))
        results_by_study[study_id] = {
            str(result.get("result_id", "")) for result in study.get("results", [])
        }
        upstream_reports.setdefault(study_id, set()).update(
            str(item.get("report_id", ""))
            for item in study.get("report_coverage", [])
        )
    if not set(results_by_study).issubset(included):
        raise TaskOutputError("Study Data Collection contains a non-Included Study")
    for target in document.targets:
        if target.study_id not in included:
            raise TaskOutputError("Risk of Bias target references a non-Included Study")
        known_results = results_by_study.get(target.study_id, set())
        if not set(target.study_result_ids).issubset(known_results):
            raise TaskOutputError(
                "Risk of Bias target references an unknown Study Result"
            )
    for observation in document.evidence_observations:
        if observation.study_id not in included:
            raise TaskOutputError(
                "Risk of Bias evidence references a non-Included Study"
            )
        if (
            observation.upstream_report_id is not None
            and observation.upstream_report_id
            not in upstream_reports.get(observation.study_id, set())
        ):
            raise TaskOutputError(
                "Risk of Bias evidence references an unknown upstream Report"
            )
    for missing in document.coverage.unassessed_results:
        if missing.study_id not in included:
            raise TaskOutputError(
                "Risk of Bias coverage references a non-Included Study"
            )
        if (
            missing.study_result_id is not None
            and missing.study_result_id
            not in results_by_study.get(missing.study_id, set())
        ):
            raise TaskOutputError(
                "Risk of Bias coverage references an unknown Study Result"
            )
    covered_studies = {
        target.study_id for target in document.targets
    } | {
        missing.study_id for missing in document.coverage.unassessed_results
    }
    if covered_studies != included:
        raise TaskOutputError(
            "Risk of Bias coverage must account for every Included Study"
        )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TaskOutputError(f"{path.name} must contain JSON objects")
            values.append(value)
    return values


def _runtime_provenance(result: TaskRunResult) -> tuple[Provenance, ...]:
    return (
        Provenance(
            source_id=result.run_id,
            source_type="agent_run",
            locator=result.session_id,
        ),
    )
