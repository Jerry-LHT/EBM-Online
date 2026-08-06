"""Application orchestration for Study-level Characteristics."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

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
from ebm_backend.online_pipeline_v2.domain.selection import (
    Report,
    Study,
    StudyClassification,
    StudyEligibilityDecision,
    StudyReportLink,
    StudySelectionArtifact,
)
from ebm_backend.online_pipeline_v2.domain.study_characteristics import (
    CharacteristicsCollections,
    CharacteristicsReportEvidenceObservation,
    DiscoveredReportLink,
    DiscoveredReportRelationshipStatus,
    StudyCharacteristicsArtifact,
    StudyCharacteristicsMethodologyAuthority,
    StudyCharacteristicsProtocolContext,
    StudyCharacteristicsRecord,
    StudyCharacteristicsSummary,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.artifact_schemas import (
    CHARACTERISTICS_COLLECTIONS_V5,
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
    CharacteristicsReviewSnapshot,
    SelectionPackageRepository,
    CharacteristicsPackageRepository,
)


_STUDY_ADAPTER = TypeAdapter(Study)
_REPORT_ADAPTER = TypeAdapter(Report)
_LINK_ADAPTER = TypeAdapter(StudyReportLink)
_DECISION_ADAPTER = TypeAdapter(StudyEligibilityDecision)
_CHARACTERISTICS_FILES = {
    "studies": ("studies.jsonl", True),
    "discovered_reports": ("discovered-reports.jsonl", True),
    "discovered_report_links": ("discovered-report-links.jsonl", True),
    "report_evidence": ("report-evidence.jsonl", True),
    "issues": ("issues.jsonl", True),
}
_CHARACTERISTICS_OUTPUT_BUNDLE = OutputBundleSpec(
    label="characteristics",
    schema_version="agent-study-characteristics-output.v6",
    manifest_name="characteristics_manifest",
    manifest_relative_path="outputs/characteristics/manifest.json",
    members=tuple(
        OutputMemberSpec(
            name=name,
            relative_path=f"outputs/characteristics/{filename}",
            manifest_path=filename,
            encoding=(
                ArtifactEncoding.JSONL_OBJECTS
                if is_jsonl
                else ArtifactEncoding.JSON_OBJECT
            ),
        )
        for name, (filename, is_jsonl) in _CHARACTERISTICS_FILES.items()
    ),
    exact_collections=True,
)
_PROHIBITED_ARTIFACT_KEYS = {
    "full_text",
    "fulltext",
    "raw_full_text",
    "document_content",
}
_PROMPT = (
    "Complete the Study Characteristics task under the Skill for the entire "
    "included Study set. Process each Study and all linked Reports, while "
    "allowing Study records to remain partial when characteristics are not "
    "reported or access fails. Inspect legitimate "
    "public evidence, create every required output artifact, and return only "
    "the compact structured completion object. Do not use benchmark data, a "
    "completed review, or model memory as evidence. Consult the directly "
    "applicable official or primary methodology authority and record its "
    "title, version or date, locator, scope, and applied principles."
)
class _AgentCharacteristicsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_schema_version: str = Field(
        pattern=r"^agent-study-characteristics-output\.v6$"
    )
    processed_study_ids: tuple[str, ...] = ()
    unprocessed_study_ids: tuple[str, ...] = ()
    methodology_authorities: tuple[StudyCharacteristicsMethodologyAuthority, ...] = ()
    methodology_basis_status: Literal["verified", "llm_fallback"] | None = None
    fallback_model: str | None = None
    fallback_note: str | None = None

    @model_validator(mode="after")
    def validate_methodology_basis(self) -> "_AgentCharacteristicsData":
        if self.methodology_basis_status == "verified" and not self.methodology_authorities:
            raise ValueError("verified characteristics methodology requires an authority")
        if self.methodology_basis_status == "llm_fallback":
            if not self.fallback_model or not self.fallback_note:
                raise ValueError("characteristics methodology fallback requires model and note")
        elif self.fallback_model is not None or self.fallback_note is not None:
            raise ValueError("fallback metadata requires llm_fallback methodology")
        return self


class _AgentCharacteristicsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ArtifactStatus
    data: _AgentCharacteristicsData | None
    issues: tuple[ArtifactIssue, ...] = ()
    execution_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_completion_contract(self) -> "_AgentCharacteristicsOutput":
        if self.status is ArtifactStatus.BLOCKED:
            if self.data is not None:
                raise ValueError("blocked completion must not contain data")
            if not any(
                issue.severity is IssueSeverity.ERROR for issue in self.issues
            ):
                raise ValueError(
                    "blocked completion requires at least one error issue"
                )
        else:
            if self.data is None:
                raise ValueError("non-blocked completion requires data")
            if self.issues:
                raise ValueError(
                    "non-blocked completion must record issues only in issues.jsonl"
                )
            if set(self.data.processed_study_ids) & set(
                self.data.unprocessed_study_ids
            ):
                raise ValueError("processed and unprocessed Study IDs must be disjoint")
            if len(set(self.data.processed_study_ids)) != len(
                self.data.processed_study_ids
            ):
                raise ValueError("processed Study IDs must be unique")
            if len(set(self.data.unprocessed_study_ids)) != len(
                self.data.unprocessed_study_ids
            ):
                raise ValueError("unprocessed Study IDs must be unique")
            if self.status is ArtifactStatus.COMPLETED and self.data.unprocessed_study_ids:
                raise ValueError("completed review must not declare unprocessed Studies")
        return self


_OUTPUT_ADAPTER = TypeAdapter(_AgentCharacteristicsOutput)


def study_characteristics_output_schema() -> dict[str, Any]:
    return strict_task_output_schema(_OUTPUT_ADAPTER.json_schema())


def _load_characteristics_collections(
    result: TaskRunResult,
    *,
    expected_studies: tuple[_IncludedStudy, ...],
    expected_agent_role: str,
) -> CharacteristicsCollections:
    bundle = load_output_bundle(result, _CHARACTERISTICS_OUTPUT_BUNDLE)
    raw_collections: dict[str, object] = {}
    for name, (_, is_jsonl) in _CHARACTERISTICS_FILES.items():
        raw_values = (
            bundle.jsonl_objects(name)
            if is_jsonl
            else (bundle.json_object(name),)
        )
        for raw_value in raw_values:
            _reject_prohibited_artifact_fields(raw_value)
        raw_collections[name] = raw_values if is_jsonl else raw_values[0]

    parsed = CHARACTERISTICS_COLLECTIONS_V5.validate_python(
        raw_collections,
        artifact="Agent characteristics collections",
    )
    loaded = CharacteristicsCollections(
        studies=parsed.studies,
        discovered_reports=parsed.discovered_reports,
        discovered_report_links=parsed.discovered_report_links,
        report_evidence=parsed.report_evidence,
        issues=parsed.issues,
    )
    _validate_characteristics_collections(
        loaded,
        expected_studies=expected_studies,
        expected_agent_role=expected_agent_role,
    )
    return loaded


def _validate_characteristics_collections(
    data: CharacteristicsCollections,
    *,
    expected_studies: tuple[_IncludedStudy, ...],
    expected_agent_role: str,
) -> None:
    expected_by_study = {item.study.study_id: item for item in expected_studies}
    if len({item.study_id for item in data.studies}) != len(data.studies):
        raise TaskOutputError("Study Characteristics studies must have unique study_ids")
    if not set(item.study_id for item in data.studies) <= set(expected_by_study):
        raise TaskOutputError("Study Characteristics output targets an unknown Study")
    produced_study_ids = {item.study_id for item in data.studies}
    expected_ids = {
        report.report_id
        for item in expected_studies
        if item.study.study_id in produced_study_ids
        for report in item.reports
    }
    discovered = {item.report_id: item for item in data.discovered_reports}
    if len(discovered) != len(data.discovered_reports):
        raise TaskOutputError("discovered Reports must have unique report_ids")
    if expected_ids.intersection(discovered):
        raise TaskOutputError(
            "discovered Reports must not repeat Reports in the Study manifest"
        )
    links_by_report: dict[str, list[DiscoveredReportLink]] = {}
    for link in data.discovered_report_links:
        if link.study_id not in expected_by_study:
            raise TaskOutputError(
                "discovered Report link targets another Study"
            )
        if link.report_id not in discovered:
            raise TaskOutputError(
                "discovered Report link references an unknown Report"
            )
        links_by_report.setdefault(link.report_id, []).append(link)
    if set(links_by_report) != set(discovered) or any(
        len(links) != 1 for links in links_by_report.values()
    ):
        raise TaskOutputError(
            "every discovered Report requires exactly one Study handoff link"
        )
    confirmed_ids = {
        report_id
        for report_id, links in links_by_report.items()
        if links[0].relationship_status is DiscoveredReportRelationshipStatus.CONFIRMED
    }
    for study in data.studies:
        known = {report.report_id for report in expected_by_study[study.study_id].reports}
        confirmed = {rid for rid in confirmed_ids if any(l.study_id == study.study_id and l.report_id == rid for l in data.discovered_report_links)}
        if set(study.report_ids) != known | confirmed:
            raise TaskOutputError("Study Characteristics output must preserve known and confirmed Reports")
    evidence_by_report: dict[
        str, list[CharacteristicsReportEvidenceObservation]
    ] = {}
    for observation in data.report_evidence:
        if observation.report_id not in expected_ids | set(discovered):
            raise TaskOutputError(
                "Report evidence references a Report outside the Characteristics artifact"
            )
        if observation.agent_role != expected_agent_role:
            raise TaskOutputError(
                "Report evidence agent_role does not match the Agent run role"
            )
        evidence_by_report.setdefault(observation.report_id, []).append(
            observation
        )
    if set(evidence_by_report) != expected_ids | set(discovered):
        raise TaskOutputError(
            "every known or discovered Report requires an access observation"
        )
    _reject_prohibited_artifact_fields(_jsonable(data))


def _reject_prohibited_artifact_fields(value: object) -> None:
    if isinstance(value, dict):
        prohibited = {
            str(key).lower() for key in value
        } & _PROHIBITED_ARTIFACT_KEYS
        if prohibited:
            raise TaskOutputError(
                "characteristics artifacts contain prohibited fields: "
                f"{sorted(prohibited)}"
            )
        for child in value.values():
            _reject_prohibited_artifact_fields(child)
    elif isinstance(value, tuple | list):
        for child in value:
            _reject_prohibited_artifact_fields(child)


@dataclass(frozen=True, slots=True)
class _ReviewRun:
    role: str
    result: TaskRunResult
    output: _AgentCharacteristicsOutput
    collections: CharacteristicsCollections | None


@dataclass(frozen=True, slots=True)
class _IncludedStudy:
    study: Study
    reports: tuple[Report, ...]
    links: tuple[StudyReportLink, ...]


@dataclass(slots=True)
class CollectStudyCharacteristicsTask:
    executor: TaskExecutorPort
    selection_package_store: SelectionPackageRepository
    characteristics_package_store: CharacteristicsPackageRepository
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    timeout_seconds: float = 1800.0
    run_id_factory: Callable[[str], str] = field(
        default=lambda role: f"study-characteristics-{role}-{uuid4().hex}",
        repr=False,
    )

    def collect(
        self,
        protocol_context: StudyCharacteristicsProtocolContext,
        selection: StudySelectionArtifact,
        context: TaskContext,
    ) -> TaskCompletion[StudyCharacteristicsArtifact]:
        included = _load_included_studies(self.selection_package_store, selection)
        serialized_protocol_context = _jsonable(protocol_context)
        all_records: list[StudyCharacteristicsRecord] = []
        all_discovered_reports: list[Report] = []
        all_discovered_links: list[DiscoveredReportLink] = []
        all_evidence: list[CharacteristicsReportEvidenceObservation] = []
        all_authorities: list[StudyCharacteristicsMethodologyAuthority] = []
        all_issues: list[ArtifactIssue] = []
        snapshots: list[CharacteristicsReviewSnapshot] = []

        with TemporaryDirectory(prefix="study-characteristics-inputs-") as raw:
            root = Path(raw)
            protocol_path = root / "protocol-context.json"
            protocol_path.write_text(
                json.dumps(
                    serialized_protocol_context,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest_path = root / "review-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    _review_manifest(included),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            review = self._execute_review(
                studies=included,
                role="reviewer-1",
                prompt=_PROMPT,
                context=context,
                protocol_path=protocol_path,
                manifest_path=manifest_path,
            )
            if review.collections is not None:
                all_issues.extend(review.collections.issues)
                all_records.extend(review.collections.studies)
                all_discovered_reports.extend(review.collections.discovered_reports)
                all_discovered_links.extend(review.collections.discovered_report_links)
                all_evidence.extend(review.collections.report_evidence)
                all_authorities.extend(review.output.data.methodology_authorities)
            else:
                all_issues.extend(review.output.issues)
            snapshots.append(_snapshot(review))

        included_count = len(included)
        completed = sum(item.status is ArtifactStatus.COMPLETED for item in all_records)
        partial = sum(item.status is ArtifactStatus.PARTIAL for item in all_records)
        blocked = included_count - len(all_records)
        summary = StudyCharacteristicsSummary(
            included_study_count=included_count,
            completed_study_count=completed,
            partial_study_count=partial,
            blocked_study_count=blocked,
            report_count=(
                sum(len(item.reports) for item in included)
                + len(all_discovered_reports)
            ),
            issue_count=len(all_issues),
        )
        package_ref = self.characteristics_package_store.persist(
            review_id=context.review_id,
            protocol_version=context.protocol_version,
            studies=all_records,
            discovered_reports=all_discovered_reports,
            discovered_report_links=all_discovered_links,
            report_evidence=all_evidence,
            issues=all_issues,
            review_runs=snapshots,
            methodology_authorities=all_authorities,
        )
        artifact = StudyCharacteristicsArtifact(
            package_ref=package_ref,
            summary=summary,
        )
        status = (
            ArtifactStatus.BLOCKED
            if review.collections is None
            else (
                ArtifactStatus.PARTIAL
                if review.output.status is ArtifactStatus.PARTIAL or blocked
                else ArtifactStatus.COMPLETED
            )
        )
        if status is ArtifactStatus.BLOCKED:
            return TaskCompletion(
                status=status,
                data=None,
                issues=tuple(
                    all_issues
                    or [
                        ArtifactIssue(
                            code="characteristics_blocked",
                            message="No included Study yielded a usable record.",
                            severity=IssueSeverity.ERROR,
                        )
                    ]
                ),
                additional_provenance=_runtime_provenance(snapshots, package_ref),
            )
        return TaskCompletion(
            status=status,
            data=artifact,
            issues=tuple(all_issues),
            additional_provenance=_runtime_provenance(snapshots, package_ref),
        )

    def _execute_review(
        self,
        *,
        studies: tuple[_IncludedStudy, ...],
        role: str,
        prompt: str,
        context: TaskContext,
        protocol_path: Path,
        manifest_path: Path,
    ) -> _ReviewRun:
        request = self._request(
            studies=studies,
            role=role,
            prompt=prompt,
            context=context,
            protocol_path=protocol_path,
            manifest_path=manifest_path,
        )
        execution = self.executor.execute(
            request,
            output_adapter=_OUTPUT_ADAPTER,
            error_context="invalid Study Characteristics output",
        )
        result = execution.result
        output = execution.output
        if output.status is ArtifactStatus.BLOCKED:
            return _ReviewRun(role, result, output, None)
        if output.data is None:
            raise TaskOutputError(
                "non-blocked Study Characteristics output requires data"
            )
        try:
            collections = _load_characteristics_collections(
                result,
                expected_studies=studies,
                expected_agent_role=role,
            )
        except TaskOutputError:
            raise
        expected_ids = {item.study.study_id for item in studies}
        produced_ids = {item.study_id for item in collections.studies}
        if produced_ids != set(output.data.processed_study_ids):
            raise TaskOutputError(
                "Agent processed_study_ids do not match studies.jsonl"
            )
        if expected_ids != produced_ids | set(output.data.unprocessed_study_ids):
            raise TaskOutputError(
                "Agent completion must account for every included Study"
            )
        for authority in output.data.methodology_authorities:
            if authority.agent_role != role:
                raise TaskOutputError(
                    "Agent methodology authority role does not match the run"
                )
        return _ReviewRun(
            role,
            result,
            output,
            collections,
        )

    def _request(
        self,
        *,
        studies: tuple[_IncludedStudy, ...],
        role: str,
        prompt: str,
        context: TaskContext,
        protocol_path: Path,
        manifest_path: Path,
    ) -> TaskRunRequest:
        input_artifacts = {
            "protocol-context": protocol_path,
            "review-manifest": manifest_path,
        }
        input_data: dict[str, object] = {
            "review_id": context.review_id,
            "protocol_version": context.protocol_version,
            "agent_role": role,
            "protocol_context": "inputs/artifacts/protocol-context",
            "review_manifest": "inputs/artifacts/review-manifest",
            "source_retrieval_tools": [],
            "declared_tools": [
                {
                    "name": "package-characteristics",
                    "kind": "skill_script",
                    "purpose": (
                        "Validate JSON output files and create the canonical "
                        "Study Characteristics manifest."
                    ),
                    "available": True,
                }
            ],
            "constraints": {
                "source_retrieval_tools_provided": False,
                "agent_must_locate_report_evidence_itself": True,
                "must_record_consulted_methodology_authority": True,
            },
        }
        return TaskRunRequest(
            run_id=self.run_id_factory(
                f"review-{role}"
            ),
            prompt=prompt,
            input_data=input_data,
            input_artifacts=input_artifacts,
            output_schema=study_characteristics_output_schema(),
            output_artifacts=_CHARACTERISTICS_OUTPUT_BUNDLE.requested_artifacts(),
            timeout_seconds=self.timeout_seconds,
            access_mode=TaskAccessMode.WORKSPACE_WRITE,
            enable_workspace_network=True,
            enable_web_search=True,
            web_access_policy=self.web_access_policy,
            task_name="study_characteristics",
        )


def _load_included_studies(
    store: SelectionPackageRepository,
    selection: StudySelectionArtifact,
) -> tuple[_IncludedStudy, ...]:
    manifest_path = store.resolve_manifest(selection.package_ref)
    manifest = store.validate(selection.package_ref)
    root = manifest_path.parent

    def collection(name: str) -> tuple[dict[str, object], ...]:
        item = manifest["collections"][name]
        path = (root / str(item["path"])).resolve()
        return tuple(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    try:
        studies = tuple(
            _STUDY_ADAPTER.validate_python(item) for item in collection("studies")
        )
        reports = tuple(
            _REPORT_ADAPTER.validate_python(item) for item in collection("reports")
        )
        links = tuple(
            _LINK_ADAPTER.validate_python(item)
            for item in collection("study_report_links")
        )
        decisions = tuple(
            _DECISION_ADAPTER.validate_python(item)
            for item in collection("study_decisions")
        )
    except (ValidationError, TypeError, DomainValidationError) as exc:
        raise TaskOutputError(
            f"Selection Package collections violate the domain contract: {exc}"
        ) from exc
    included_ids = {
        item.study_id
        for item in decisions
        if item.classification is StudyClassification.INCLUDED
    }
    reports_by_id = {item.report_id: item for item in reports}
    studies_by_id = {item.study_id: item for item in studies}
    output: list[_IncludedStudy] = []
    for study_id in sorted(included_ids):
        study_links = tuple(item for item in links if item.study_id == study_id)
        if not study_links:
            raise TaskOutputError(
                f"included Study {study_id} has no Study-Report links"
            )
        linked_reports: list[Report] = []
        for link in study_links:
            report = reports_by_id.get(link.report_id)
            if report is None:
                raise TaskOutputError(
                    f"Study-Report link references unknown Report {link.report_id}"
                )
            linked_reports.append(report)
        study = studies_by_id.get(study_id)
        if study is None:
            raise TaskOutputError(f"included decision references unknown Study {study_id}")
        output.append(_IncludedStudy(study, tuple(linked_reports), study_links))
    return tuple(output)


def _review_manifest(studies: tuple[_IncludedStudy, ...]) -> dict[str, object]:
    return {
        "studies": [
            {
                "study": _jsonable(item.study),
                "reports": [_jsonable(report) for report in item.reports],
                "study_report_links": [_jsonable(link) for link in item.links],
            }
            for item in studies
        ],
        "constraints": {
            "review_wide_single_agent_run": True,
            "study_is_extraction_unit": True,
            "agent_may_choose_order_and_tool_calls": True,
            "full_text_is_not_provided": True,
            "report_role_is_authoritative_for_linkage": True,
        },
    }


def _snapshot(review: _ReviewRun) -> CharacteristicsReviewSnapshot:
    return CharacteristicsReviewSnapshot(
        role=review.role,
        run_id=review.result.run_id,
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


def _runtime_provenance(
    snapshots: list[CharacteristicsReviewSnapshot],
    package_ref: object,
) -> tuple[Provenance, ...]:
    values = [
        Provenance(
            source_id=item.run_id,
            source_type="agent_run",
            locator=item.role,
        )
        for item in snapshots
    ]
    values.append(
        Provenance(
            source_id=getattr(package_ref, "content_digest"),
            source_type="study_characteristics_package",
            locator=f"study-characteristics-package:{getattr(package_ref, 'package_id')}",
        )
    )
    return tuple(values)


def _jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _jsonable(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return value.value
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _opaque_component(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:24]
