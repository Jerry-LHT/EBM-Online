"""Application orchestration for the Study Selection professional task."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.schema import (
    strict_task_output_schema,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    ArtifactStatus,
    DomainValidationError,
    IssueSeverity,
    Provenance,
    TaskCompletion,
    TaskContext,
)
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchArtifact,
    EvidenceSearchPublicArtifact,
    Record,
    SearchRun,
    SearchSummary,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    Report,
    SelectionCollections,
    SelectionPackageRef,
    SearchContinuationDecision,
    SearchContinuationStatus,
    SelectionSummary,
    Study,
    StudyClassification,
    StudyEligibilityDecision,
    StudyReportLink,
    StudySelectionArtifact,
    StudySelectionProtocol,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.artifact_schemas import (
    SELECTION_COLLECTIONS_V2,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskAccessMode,
    TaskExecutorPort,
    TaskOutputError,
    TaskRunRequest,
    TaskRunResult,
    WebAccessPolicy,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.output_bundle import (
    ArtifactEncoding,
    OutputBundleSpec,
    OutputMemberSpec,
    load_output_bundle,
)
from ebm_backend.online_pipeline_v2.application.ports.repositories import (
    SearchPackageRepository,
    SelectionPackageRepository,
    SelectionAgentSnapshot,
)


_PROTOCOL_ADAPTER = TypeAdapter(StudySelectionProtocol)
_RECORDS_ADAPTER = TypeAdapter(tuple[Record, ...])
_RUNS_ADAPTER = TypeAdapter(tuple[SearchRun, ...])
_PROMPT = (
    "Complete the Study Selection task described by the Skill. You are the "
    "professional task executor. Work from the verified Search Package and "
    "produce the task artifact described by the runtime's declared output "
    "contract. Choose the tools and working method that fit the evidence and "
    "workload. Actually investigate every "
    "Report advanced beyond coarse screening; a bibliographic abstract alone "
    "is neither full Report access nor a retrieval attempt. Reuse supplied "
    "locators before discovering additional lawful representations. Do not use benchmark data "
    "or a completed review's decisions. Consult the current directly applicable "
    "official or primary methodology authority for Study Selection before "
    "screening, use it to determine the professional workflow and evidence "
    "thresholds, and record the authority, version or publication date, locator, "
    "scope, and applied principles in the final structured output. The Protocol "
    "remains authoritative for this review's eligibility criteria."
)


class _MethodologyAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    version_or_date: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    applied_principles: tuple[str, ...] = Field(min_length=1)


class _AgentSelectionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_schema_version: str = Field(
        pattern=r"^agent-selection-output\.v3$"
    )
    execution_summary: str = Field(min_length=1)
    methodology_authorities: tuple[_MethodologyAuthority, ...] = ()
    methodology_basis_status: Literal["verified", "llm_fallback"] | None = None
    fallback_model: str | None = None
    fallback_note: str | None = None
    search_continuation: SearchContinuationDecision = Field(
        default_factory=lambda: SearchContinuationDecision(
            status=SearchContinuationStatus.PROCEED,
            rationale="No additional search was requested.",
        )
    )

    @model_validator(mode="after")
    def validate_methodology_basis(self) -> "_AgentSelectionData":
        if self.methodology_basis_status == "verified" and not self.methodology_authorities:
            raise ValueError("verified selection methodology requires an authority")
        if self.methodology_basis_status == "llm_fallback":
            if not self.fallback_model or not self.fallback_note:
                raise ValueError("selection methodology fallback requires model and note")
        elif self.fallback_model is not None or self.fallback_note is not None:
            raise ValueError("fallback metadata requires llm_fallback methodology")
        return self


class _AgentSelectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ArtifactStatus
    data: _AgentSelectionData | None
    issues: tuple[ArtifactIssue, ...] = ()


_OUTPUT_ADAPTER = TypeAdapter(_AgentSelectionOutput)
_SELECTION_COLLECTIONS = {
    "record_screening": "record-screening.jsonl",
    "reports": "reports.jsonl",
    "report_discoveries": "report-discoveries.jsonl",
    "record_report_links": "record-report-links.jsonl",
    "report_evidence": "report-evidence.jsonl",
    "studies": "studies.jsonl",
    "study_report_links": "study-report-links.jsonl",
    "study_decisions": "study-decisions.jsonl",
    "conflicts": "conflicts.jsonl",
}
_SELECTION_OUTPUT_BUNDLE = OutputBundleSpec(
    label="selection",
    schema_version="agent-selection-output.v3",
    manifest_name="selection_manifest",
    manifest_relative_path="outputs/selection/manifest.json",
    members=tuple(
        OutputMemberSpec(
            name=name,
            relative_path=f"outputs/selection/{filename}",
            manifest_path=filename,
            encoding=ArtifactEncoding.JSONL_OBJECTS,
        )
        for name, filename in _SELECTION_COLLECTIONS.items()
    ),
)


def study_selection_output_schema() -> dict[str, Any]:
    schema = deepcopy(_OUTPUT_ADAPTER.json_schema())
    return strict_task_output_schema(schema)


def _load_selection_collections(
    result: TaskRunResult,
) -> SelectionCollections:
    bundle = load_output_bundle(result, _SELECTION_OUTPUT_BUNDLE)
    parsed = SELECTION_COLLECTIONS_V2.validate_python(
        {
            name: bundle.jsonl_objects(name)
            for name in _SELECTION_COLLECTIONS
        },
        artifact="Agent selection collections",
    )
    return SelectionCollections(
        record_screening=parsed.record_screening,
        reports=parsed.reports,
        report_discoveries=parsed.report_discoveries,
        record_report_links=parsed.record_report_links,
        report_evidence=parsed.report_evidence,
        studies=parsed.studies,
        study_report_links=parsed.study_report_links,
        study_decisions=parsed.study_decisions,
        conflicts=parsed.conflicts,
    )


@dataclass(frozen=True, slots=True)
class _AgentRun:
    role: str
    result: TaskRunResult
    output: _AgentSelectionOutput
    collections: SelectionCollections


@dataclass(slots=True)
class SelectStudiesTask:
    executor: TaskExecutorPort
    search_package_store: SearchPackageRepository
    selection_package_store: SelectionPackageRepository
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    timeout_seconds: float = 1800.0
    run_id_factory: Callable[[str], str] = field(
        default=lambda role: f"study-selection-{role}-{uuid4().hex}",
        repr=False,
    )

    def select(
        self,
        protocol: StudySelectionProtocol,
        search: EvidenceSearchPublicArtifact,
        context: TaskContext,
    ) -> TaskCompletion[StudySelectionArtifact]:
        package_ref = search.package_ref
        search_directory = self.search_package_store.package_directory(package_ref)
        search_collections = _load_search_snapshot(search, search_directory)

        selected = self._execute_review(
            role="primary-agent",
            prompt=_PROMPT,
            protocol=protocol,
            search=search,
            context=context,
            search_directory=search_directory,
        )
        if selected.output.status is ArtifactStatus.BLOCKED:
            return _blocked_completion(selected.output, selected.result)

        package = self.selection_package_store.persist(
            review_id=context.review_id,
            protocol_version=context.protocol_version,
            collections=selected.collections,
            agent_runs=(_snapshot(selected),),
        )
        summary = _build_summary(search_collections, selected.collections)
        artifact = StudySelectionArtifact(
            package_ref=package,
            summary=summary,
            search_continuation=selected.output.data.search_continuation,
        )
        return TaskCompletion(
            status=selected.output.status,
            data=artifact,
            issues=selected.output.issues,
            additional_provenance=_runtime_provenance(
                (selected,),
                package,
            ),
        )

    def _execute_review(
        self,
        *,
        role: str,
        prompt: str,
        protocol: StudySelectionProtocol,
        search: EvidenceSearchPublicArtifact,
        context: TaskContext,
        search_directory: Path,
    ) -> _AgentRun:
        request = self._request(
            role=role,
            prompt=prompt,
            protocol=protocol,
            search=search,
            context=context,
            search_directory=search_directory,
        )
        execution = self.executor.execute(
            request,
            output_adapter=_OUTPUT_ADAPTER,
            error_context="invalid Study Selection output",
        )
        result = execution.result
        output = execution.output
        if output.status is ArtifactStatus.BLOCKED:
            return _AgentRun(role, result, output, _empty_collections())
        if output.data is None:
            raise TaskOutputError("non-blocked selection output requires data")
        collections = _load_selection_collections(result)
        _validate_selection_collections(
            collections,
            _load_search_snapshot(search, search_directory),
        )
        return _AgentRun(role, result, output, collections)

    def _request(
        self,
        *,
        role: str,
        prompt: str,
        protocol: StudySelectionProtocol,
        search: EvidenceSearchPublicArtifact,
        context: TaskContext,
        search_directory: Path,
    ) -> TaskRunRequest:
        input_artifacts = {"search-package": search_directory}
        input_data: dict[str, object] = {
            "review_id": context.review_id,
            "protocol_version": context.protocol_version,
            "protocol": _PROTOCOL_ADAPTER.dump_python(protocol, mode="json"),
            "search_package": {
                "artifact_path": "inputs/artifacts/search-package",
                "package_id": (
                    search.package_ref.package_id
                    if search.package_ref
                    else None
                ),
                "content_digest": (
                    search.package_ref.content_digest if search.package_ref else None
                ),
                "source_record_count": search.summary.record_count,
            },
            "declared_tools": (
                {
                    "name": "package-selection",
                    "kind": "skill_script",
                    "usage": "required_artifact_operation",
                    "purpose": (
                        "Validate JSONL collections and create the canonical "
                        "Agent selection manifest."
                    ),
                    "available": True,
                },
            ),
        }
        return TaskRunRequest(
            run_id=self.run_id_factory(role),
            prompt=prompt,
            input_data=input_data,
            input_artifacts=input_artifacts,
            output_schema=study_selection_output_schema(),
            output_artifacts=_SELECTION_OUTPUT_BUNDLE.requested_artifacts(),
            timeout_seconds=self.timeout_seconds,
            access_mode=TaskAccessMode.WORKSPACE_WRITE,
            enable_workspace_network=True,
            enable_web_search=True,
            web_access_policy=self.web_access_policy,
            task_name="study_selection",
        )


def _validate_selection_collections(
    data: SelectionCollections,
    search: EvidenceSearchArtifact,
) -> None:
    record_ids = {record.record_id for record in search.records}
    screening = {item.record_id: item for item in data.record_screening}
    if len(screening) != len(data.record_screening):
        raise TaskOutputError("Record screening IDs must be unique")
    if not set(screening).issubset(record_ids):
        raise TaskOutputError("Record screening references an unknown Record")
    for item in data.record_screening:
        if item.duplicate_of_record_id is not None:
            target = screening.get(item.duplicate_of_record_id)
            if target is None:
                raise TaskOutputError("duplicate Record references an unknown Record")

    report_ids = _unique_ids(
        (report.report_id for report in data.reports),
        "Report",
    )
    for link in data.record_report_links:
        if link.record_id not in record_ids or link.report_id not in report_ids:
            raise TaskOutputError("Record-Report link references an unknown entity")
    for link in data.report_discoveries:
        if link.report_id not in report_ids:
            raise TaskOutputError("Report discovery references an unknown Report")

    for observation in data.report_evidence:
        if observation.report_id not in report_ids:
            raise TaskOutputError("Report evidence references an unknown Report")

    study_ids = _unique_ids(
        (study.study_id for study in data.studies),
        "Study",
    )
    decision_ids = [item.study_id for item in data.study_decisions]
    if len(decision_ids) != len(set(decision_ids)):
        raise TaskOutputError("Study decision IDs must be unique")
    if not set(decision_ids).issubset(study_ids):
        raise TaskOutputError("Study decision references an unknown Study")

    for link in data.study_report_links:
        if link.study_id not in study_ids or link.report_id not in report_ids:
            raise TaskOutputError("Study-Report link references an unknown entity")
    _unique_ids(
        (item.observation_id for item in data.report_evidence),
        "Report evidence observation",
    )
    _unique_ids(
        (item.conflict_id for item in data.conflicts),
        "Selection conflict",
    )


def _load_search_snapshot(
    search: EvidenceSearchPublicArtifact,
    search_directory: Path,
) -> EvidenceSearchArtifact:
    manifest_path = search_directory / "manifest.json"
    records_path = search_directory / "records.jsonl"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package_runs = _RUNS_ADAPTER.validate_python(
            tuple(
                json.loads(line)
                for line in (
                    search_directory / "search_runs.jsonl"
                ).read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        )
        package_records = _RECORDS_ADAPTER.validate_python(
            tuple(
                json.loads(line)
                for line in records_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise TaskOutputError(
            f"Search Package cannot be materialized for Study Selection: {exc}"
        ) from exc
    expected_summary = {
        "run_count": search.summary.run_count,
        "source_count": search.summary.source_count,
        "record_count": search.summary.record_count,
    }
    if manifest.get("summary") != expected_summary:
        raise TaskOutputError(
            "Search Package summary does not match the supplied Search Artifact"
        )
    public_sources = {
        source.search_run_id: source for source in search.sources
    }
    if set(public_sources) != {run.search_run_id for run in package_runs}:
        raise TaskOutputError(
            "Search Package runs do not match the supplied Search Artifact"
        )
    for run in package_runs:
        source = public_sources[run.search_run_id]
        if (
            source.source_name != run.source_name
            or source.platform != run.platform
            or source.executed_at != run.executed_at
            or source.status is not run.status
            or source.result_count != run.result_count
            or source.retrieved_count != run.retrieved_count
            or source.status_reason != run.status_reason
        ):
            raise TaskOutputError(
                "Search Package runs do not match the supplied Search Artifact"
            )
    try:
        return EvidenceSearchArtifact(
            search_runs=package_runs,
            records=package_records,
            summary=SearchSummary(**expected_summary),
            package_ref=search.package_ref,
        )
    except (TypeError, DomainValidationError) as exc:
        raise TaskOutputError(
            f"Search Package violates the domain contract: {exc}"
        ) from exc


def _build_summary(
    search: EvidenceSearchArtifact,
    data: SelectionCollections,
) -> SelectionSummary:
    duplicate_count = sum(
        item.duplicate_of_record_id is not None
        for item in data.record_screening
    )
    accessed_reports = {
        observation.report_id
        for observation in data.report_evidence
        if observation.accessed
    }
    counts = {
        classification: sum(
            item.classification is classification
            for item in data.study_decisions
        )
        for classification in StudyClassification
    }
    return SelectionSummary(
        source_record_count=search.summary.record_count,
        duplicate_record_count=duplicate_count,
        records_screened_count=sum(
            item.duplicate_of_record_id is None
            for item in data.record_screening
        ),
        title_abstract_excluded_count=sum(
            item.duplicate_of_record_id is None
            and item.advances_to_report_assessment is False
            for item in data.record_screening
        ),
        reports_sought_count=len(data.reports),
        reports_not_retrieved_count=len(data.reports) - len(accessed_reports),
        reports_assessed_count=len(accessed_reports),
        study_count=len(data.studies),
        included_count=counts[StudyClassification.INCLUDED],
        excluded_count=counts[StudyClassification.EXCLUDED],
        awaiting_classification_count=counts[
            StudyClassification.AWAITING_CLASSIFICATION
        ],
        ongoing_count=counts[StudyClassification.ONGOING],
        unresolved_conflict_count=sum(
            not conflict.resolved
            for conflict in data.conflicts
        ),
    )


def _snapshot(review: _AgentRun) -> SelectionAgentSnapshot:
    return SelectionAgentSnapshot(
        role=review.role,
        output=review.output,
        artifacts={
            (
                str(Path(*Path(artifact.relative_path).parts[1:]))
                if Path(artifact.relative_path).parts
                and Path(artifact.relative_path).parts[0] == "outputs"
                else artifact.relative_path
            ): artifact.content
            for artifact in review.result.output_artifacts.values()
        },
    )


def _unique_ids(values: object, label: str) -> set[str]:
    items = tuple(values)
    if any(not value.strip() for value in items):
        raise TaskOutputError(f"{label} identifiers must not be blank")
    if len(set(items)) != len(items):
        raise TaskOutputError(f"{label} identifiers must be unique")
    return set(items)


def _empty_collections() -> SelectionCollections:
    return SelectionCollections((), (), (), (), (), (), (), (), ())


def _runtime_provenance(
    reviews: tuple[_AgentRun, ...],
    package_ref: SelectionPackageRef,
) -> tuple[Provenance, ...]:
    values = [
        Provenance(
            source_id=item.result.run_id,
            source_type="agent_run",
            locator=f"{item.result.provider.value}:{item.result.model}",
            excerpt=item.role,
        )
        for item in reviews
    ]
    values.append(
        Provenance(
            source_id=package_ref.content_digest,
            source_type="selection_package",
            locator=f"selection-package:{package_ref.package_id}",
        )
    )
    return tuple(values)


def _blocked_completion(
    output: _AgentSelectionOutput,
    result: TaskRunResult,
) -> TaskCompletion[StudySelectionArtifact]:
    issues = output.issues or (
        ArtifactIssue(
            code="study_selection_blocked",
            message="The Study Selection Agent could not produce a usable selection.",
            severity=IssueSeverity.ERROR,
        ),
    )
    return TaskCompletion(
        status=ArtifactStatus.BLOCKED,
        data=None,
        issues=issues,
        additional_provenance=(
            Provenance(
                source_id=result.run_id,
                source_type="agent_run",
                locator=f"{result.provider.value}:{result.model}",
            ),
        ),
    )
