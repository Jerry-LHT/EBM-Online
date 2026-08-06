"""Application orchestration for the Evidence Search professional task."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from typing import Any, Callable, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

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
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchArtifact,
    EvidenceSearchInput,
    EvidenceSearchMode,
    SearchRunStatus,
    SearchSummary,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.artifact_schemas import (
    SEARCH_COLLECTIONS_V1,
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
)


_PROMPT = (
    "Complete the Evidence Search task described by the Skill. You are the "
    "task executor, not merely a planner. Follow every source and platform in "
    "the supplied Protocol by either executing it legitimately or recording "
    "why it was not executed. Develop the final source-specific strategies in "
    "this task. Treat any Protocol strategies only as optional planned "
    "baselines: check, revise, translate, or replace them when professionally "
    "necessary, and preserve the final strategy actually executed. Choose the "
    "best legitimate execution path from native capabilities and declared "
    "scripts; script availability must not determine or narrow the sources. "
    "Do not attempt a source without compatible access, required prior "
    "evidence, or explicit authorization for external communication. Inspect "
    "actual observations and create the required Search artifact files. "
    "Never perform screening, deduplication, Report collation, or Study "
    "identification, and never substitute a completed review's answers for "
    "execution of the supplied Protocol."
)


class _AgentSearchData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_schema_version: str = Field(pattern="^agent-search-output\\.v1$")
    execution_summary: str = Field(min_length=1)


class _AgentEvidenceSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ArtifactStatus
    data: _AgentSearchData | None
    issues: tuple[ArtifactIssue, ...]


_OUTPUT_ADAPTER = TypeAdapter(_AgentEvidenceSearchOutput)
_PROTOCOL_ADAPTER = TypeAdapter(ProtocolDraft)
DEFAULT_PUBMED_TOOL_EMAIL = "ebm-online-pipeline@example.com"
_SEARCH_OUTPUT_BUNDLE = OutputBundleSpec(
    label="search",
    schema_version="agent-search-output.v1",
    manifest_name="search_manifest",
    manifest_relative_path="outputs/search/manifest.json",
    members=(
        OutputMemberSpec(
            name="search_runs",
            relative_path="outputs/search/search-runs.jsonl",
            manifest_path="search-runs.jsonl",
            encoding=ArtifactEncoding.JSONL_OBJECTS,
        ),
        OutputMemberSpec(
            name="search_records",
            relative_path="outputs/search/records.jsonl",
            manifest_path="records.jsonl",
            encoding=ArtifactEncoding.JSONL_OBJECTS,
            manifest_name="records",
        ),
    ),
)


def evidence_search_output_schema() -> dict[str, Any]:
    schema = deepcopy(_OUTPUT_ADAPTER.json_schema())
    return strict_task_output_schema(schema)


@dataclass(slots=True)
class SearchEvidenceTask:
    """Let the Agent execute Evidence Search through its staged Skill tools."""

    executor: TaskExecutorPort
    package_store: SearchPackageRepository
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    timeout_seconds: float = 1800.0
    run_id_factory: Callable[[], str] = field(
        default=lambda: f"evidence-search-{uuid4().hex}",
        repr=False,
    )

    def search(
        self,
        protocol: ProtocolDraft,
        context: TaskContext,
        inputs: EvidenceSearchInput | None = None,
    ) -> TaskCompletion[EvidenceSearchArtifact]:
        inputs = inputs or EvidenceSearchInput(protocol=protocol)
        supplementary = inputs.mode is EvidenceSearchMode.SUPPLEMENTARY
        prompt = _PROMPT + (
            " This is a supplementary search round. Execute only legitimate "
            "follow-up searches needed to address the supplied gaps and leads; "
            "do not repeat the entire initial search plan."
            if supplementary
            else ""
        )
        request = TaskRunRequest(
            run_id=self.run_id_factory(),
            prompt=prompt,
            input_data={
                "review_id": context.review_id,
                "protocol_version": context.protocol_version,
                "protocol": _PROTOCOL_ADAPTER.dump_python(
                    protocol,
                    mode="json",
                ),
                "search_mode": inputs.mode.value,
                "supplementary_context": (
                    {
                        "parent_package_id": inputs.parent_package_ref.package_id,
                        "supplementary_reason": inputs.supplementary_reason,
                        "evidence_gaps": list(inputs.evidence_gaps),
                        "candidate_leads": list(inputs.candidate_leads),
                    }
                    if supplementary
                    else None
                ),
                "declared_tools": [
                    {
                        "name": "provider-native-web",
                        "kind": "native",
                        "purpose": (
                            "Search an actual named Protocol source or inspect "
                            "official vocabulary and platform syntax."
                        ),
                        "available": True,
                    },
                    {
                        "name": "workspace-network",
                        "kind": "native",
                        "purpose": (
                            "Use workspace shell and network access when it is "
                            "a legitimate execution path for the named source."
                        ),
                        "available": True,
                    },
                    {
                        "name": "pubmed-eutilities",
                        "kind": "skill_script",
                        "purpose": (
                            "Optionally execute and bulk-export PubMed queries "
                            "as bibliographic Records without full text."
                        ),
                        "available": bool(
                            os.getenv("PUBMED_TOOL_EMAIL", DEFAULT_PUBMED_TOOL_EMAIL).strip()
                        ),
                    },
                    {
                        "name": "source-status",
                        "kind": "skill_script",
                        "purpose": (
                            "Record a failed source, or a planned source not "
                            "executed because access, prerequisite evidence, "
                            "or external-action authorization is unavailable."
                        ),
                        "available": True,
                    },
                    {
                        "name": "nlm-mesh-lookup",
                        "kind": "skill_script",
                        "purpose": (
                            "Optionally inspect official NLM MeSH descriptors "
                            "and entry terms while developing a PubMed query."
                        ),
                        "available": True,
                    },
                    {
                        "name": "package-search",
                        "kind": "skill_script",
                        "purpose": (
                            "Validate and package source observations into "
                            "the required Agent output artifacts."
                        ),
                        "available": True,
                    },
                ],
            },
            output_schema=evidence_search_output_schema(),
            output_artifacts=_SEARCH_OUTPUT_BUNDLE.requested_artifacts(),
            timeout_seconds=self.timeout_seconds,
            access_mode=TaskAccessMode.WORKSPACE_WRITE,
            enable_workspace_network=True,
            enable_web_search=True,
            web_access_policy=self.web_access_policy,
            task_name="evidence_search",
        )
        execution = self.executor.execute(
            request,
            output_adapter=_OUTPUT_ADAPTER,
            error_context="Agent Evidence Search output is invalid",
        )
        result = execution.result
        agent_output = execution.output
        if agent_output.status is ArtifactStatus.BLOCKED:
            return _blocked_completion(agent_output, result)
        if agent_output.data is None:
            raise TaskOutputError("non-blocked Evidence Search output requires data")

        artifact = _load_search_artifact(result)
        if not supplementary:
            _validate_source_coverage(protocol, artifact)
        if supplementary:
            parent = self.package_store.load(inputs.parent_package_ref)
            artifact = _merge_search_artifacts(parent, artifact)
        _validate_nonblocked_search(artifact)
        package_ref = self.package_store.persist(
            review_id=context.review_id,
            protocol_version=context.protocol_version,
            artifact=artifact,
        )
        persisted = EvidenceSearchArtifact(
            search_runs=artifact.search_runs,
            records=artifact.records,
            summary=artifact.summary,
            package_ref=package_ref,
        )
        return TaskCompletion(
            status=agent_output.status,
            data=persisted,
            issues=agent_output.issues,
            additional_provenance=_provenance(result)
            + (
                Provenance(
                    source_id=package_ref.content_digest,
                    source_type="search_package",
                    locator=f"search-package:{package_ref.package_id}",
                ),
            ),
        )


def _validate_source_coverage(
    protocol: ProtocolDraft,
    artifact: EvidenceSearchArtifact,
) -> None:
    expected = {
        source.source_name for source in protocol.methods.search.structured_sources
    } | {source.source_name for source in protocol.methods.search.other_sources}
    actual = [run.source_name for run in artifact.search_runs]
    if len(set(actual)) != len(actual):
        raise TaskOutputError(
            "Agent artifacts contain duplicate Protocol search sources"
        )
    if set(actual) != expected:
        raise TaskOutputError(
            "Agent Search Runs do not match Protocol sources: "
            f"missing={sorted(expected - set(actual))}, "
            f"unexpected={sorted(set(actual) - expected)}"
        )


def _merge_search_artifacts(
    parent: EvidenceSearchArtifact,
    supplementary: EvidenceSearchArtifact,
) -> EvidenceSearchArtifact:
    """Create a new immutable package containing both search rounds."""
    run_ids = {run.search_run_id for run in parent.search_runs}
    if run_ids.intersection(run.search_run_id for run in supplementary.search_runs):
        raise DomainValidationError("supplementary Search Run ids collide with parent")
    record_ids = {record.record_id for record in parent.records}
    if record_ids.intersection(record.record_id for record in supplementary.records):
        raise DomainValidationError("supplementary Record ids collide with parent")
    runs = parent.search_runs + supplementary.search_runs
    records = parent.records + supplementary.records
    return EvidenceSearchArtifact(
        search_runs=runs,
        records=records,
        summary=SearchSummary(
            run_count=len(runs),
            source_count=len({run.source_name for run in runs}),
            record_count=len(records),
        ),
    )


def _load_search_artifact(result: TaskRunResult) -> EvidenceSearchArtifact:
    bundle = load_output_bundle(result, _SEARCH_OUTPUT_BUNDLE)
    summary_value = bundle.manifest.get("summary")
    if not isinstance(summary_value, dict):
        raise TaskOutputError("Agent search manifest requires summary")
    collections = SEARCH_COLLECTIONS_V1.validate_python(
        {
            "search_runs": bundle.jsonl_objects("search_runs"),
            "records": bundle.jsonl_objects("search_records"),
        },
        artifact="Agent search collections",
    )
    try:
        return EvidenceSearchArtifact(
            search_runs=collections.search_runs,
            records=collections.records,
            summary=SearchSummary(**summary_value),
        )
    except (ValidationError, TypeError, DomainValidationError) as exc:
        raise TaskOutputError(
            f"Agent search artifacts violate the domain contract: {exc}"
        ) from exc


def _validate_nonblocked_search(artifact: EvidenceSearchArtifact) -> None:
    usable = [
        run
        for run in artifact.search_runs
        if run.status
        in {
            SearchRunStatus.SUCCEEDED,
            SearchRunStatus.PARTIAL,
        }
    ]
    if not usable:
        raise TaskOutputError(
            "a non-blocked search requires at least one usable Search Run"
        )


def _blocked_completion(
    output: _AgentEvidenceSearchOutput,
    result: TaskRunResult,
) -> TaskCompletion[EvidenceSearchArtifact]:
    if output.data is not None:
        raise TaskOutputError("blocked Evidence Search output requires null data")
    issues = output.issues
    if not any(issue.severity is IssueSeverity.ERROR for issue in issues):
        issues = issues + (
            ArtifactIssue(
                code="agent_evidence_search_blocked",
                message="The Agent could not produce a usable Search Package.",
                severity=IssueSeverity.ERROR,
            ),
        )
    return TaskCompletion(
        status=ArtifactStatus.BLOCKED,
        data=None,
        issues=issues,
        additional_provenance=_provenance(result),
    )


def _provenance(result: TaskRunResult) -> tuple[Provenance, ...]:
    values: list[Provenance] = [
        Provenance(
            source_id=result.model,
            source_type="agent_runtime_model",
            locator=result.session_id or result.run_id,
        ),
        Provenance(
            source_id=result.run_id,
            source_type="agent_web_access_audit",
            locator="enabled" if result.web_access_audit.enabled else "disabled",
            excerpt=json.dumps(
                {
                    "potential_contamination": (
                        result.web_access_audit.potential_contamination
                    ),
                    "inspected_value_count": (
                        result.web_access_audit.inspected_value_count
                    ),
                    "violation_count": len(result.web_access_audit.violations),
                },
                sort_keys=True,
            ),
        ),
    ]
    values.extend(
        Provenance(
            source_id=snapshot.sha256,
            source_type="agent_skill",
            locator=snapshot.name,
        )
        for snapshot in result.skill_snapshots
    )
    return tuple(values)
