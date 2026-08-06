from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

import pytest

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactStatus,
    Provenance,
    TaskContext,
)
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchArtifact,
    EvidenceSearchPublicArtifact,
    Record,
    SearchRun,
    SearchRunStatus,
    SearchSummary,
    public_search_artifact,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    RecordScreeningDecision,
    RecordReportLink,
    Report,
    ReportEvidenceObservation,
    SelectionConflict,
    Study,
    StudyClassification,
    StudyEligibilityDecision,
    StudyReportLink,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    AgentOutputArtifact,
    AgentProvider,
    AgentRunRequest,
    AgentRunResult,
    AgentSkillSnapshot,
    WebAccessAudit,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskOutputError,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.skill_loader import (
    load_skill,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution import (
    AgentTaskExecutorAdapter,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.packages import (
    FileSearchPackageStore,
    FileSelectionPackageStore,
    SelectionAgentSnapshot,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.study_selection import (
    SelectStudiesTask,
    study_selection_output_schema,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.study_selection import (
    _build_summary,
    _load_search_snapshot,
    _validate_selection_collections,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    SelectionCollections,
)


_SKILL_ROOT = (
    Path(__file__).parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/"
    "agent_execution/skills/study_selection/select-studies"
)
_ACCESS_SKILL_ROOT = (
    _SKILL_ROOT.parents[1] / "shared" / "find-and-read-reports"
)


def _executor(runtime) -> AgentTaskExecutorAdapter:
    return AgentTaskExecutorAdapter(
        runtime,
        (_SKILL_ROOT, _ACCESS_SKILL_ROOT),
    )
_COLLECTION_FILES = {
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


class FakeRuntime:
    provider = AgentProvider.OPENAI

    def __init__(
        self,
        *,
        blocked_roles: tuple[str, ...] = (),
        classifications: Mapping[str, StudyClassification] | None = None,
        report_accessed: bool = True,
    ) -> None:
        self.blocked_roles = blocked_roles
        self.classifications = dict(classifications or {})
        self.report_accessed = report_accessed
        self.requests: list[AgentRunRequest] = []

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        role = "primary-agent"
        blocked = role in self.blocked_roles
        output = (
            {
                "status": "blocked",
                "data": None,
                "issues": [
                    {
                        "code": "review_failed",
                        "message": f"{role} failed.",
                        "severity": "error",
                    }
                ],
            }
            if blocked
            else {
                "status": "completed",
                "data": {
                    "artifact_schema_version": "agent-selection-output.v3",
                    "execution_summary": f"{role} completed selection.",
                    "methodology_authorities": [
                        {
                            "title": "Cochrane Handbook for Systematic Reviews of Interventions, Chapter 4",
                            "version_or_date": "current edition",
                            "locator": "https://training.cochrane.org/handbook/current/chapter-04",
                            "scope": "Study identification and selection in intervention reviews",
                            "applied_principles": [
                                "Use an over-inclusive title and abstract screen.",
                                "Make final eligibility decisions after sufficient report assessment.",
                            ],
                        }
                    ],
                    "search_continuation": {
                        "status": "proceed",
                        "rationale": (
                            "Selection reached an honest conclusion for every "
                            "source Record and known Report."
                        ),
                        "evidence_gaps": [],
                        "suggested_actions": [],
                        "candidate_leads": [],
                    },
                },
                "issues": [],
            }
        )
        return AgentRunResult(
            provider=self.provider,
            model="openai/gpt-5.6-terra",
            run_id=request.run_id,
            session_id=f"session-{role}",
            output=output,
            events=(),
            stderr="",
            duration_seconds=1.0,
            web_access_audit=WebAccessAudit(
                enabled=True,
                potential_contamination=False,
                inspected_value_count=0,
                violations=(),
            ),
            skill_snapshots=(
                AgentSkillSnapshot("select-studies", "a" * 64),
            ),
            output_artifacts=(
                {}
                if blocked
                else _selection_artifacts(
                    role,
                    classification=self.classifications.get(
                        role,
                        StudyClassification.INCLUDED,
                    ),
                    report_accessed=self.report_accessed,
                    empty=(
                        request.input_data["search_package"]["source_record_count"]
                        == 0
                    ),
                )
            ),
        )


def test_selection_output_schema_forbids_provider_specific_extra_fields() -> None:
    schema = study_selection_output_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["_AgentSelectionData"]["additionalProperties"] is False
    _assert_responses_strict_schema(schema)


def _assert_responses_strict_schema(value: object) -> None:
    if isinstance(value, dict):
        assert "default" not in value
        properties = value.get("properties")
        if isinstance(properties, dict):
            assert value.get("additionalProperties") is False
            assert value.get("required") == list(properties)
        for nested in value.values():
            _assert_responses_strict_schema(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_responses_strict_schema(nested)


def test_selection_package_is_v4_immutable_path_opaque_and_has_no_markdown(
    tmp_path: Path,
) -> None:
    store = FileSelectionPackageStore(tmp_path)
    collections = _collections("primary-agent")
    snapshot = SelectionAgentSnapshot(
        role="primary-agent",
        output={"status": "completed"},
        artifacts={"selection/manifest.json": b"{}\n"},
    )

    first = store.persist(
        review_id="review-1",
        protocol_version="protocol-1",
        collections=collections,
        agent_runs=(snapshot,),
    )
    second = store.persist(
        review_id="review-1",
        protocol_version="protocol-1",
        collections=collections,
        agent_runs=(snapshot,),
    )

    assert first.schema_version == "selection-package.v4"
    assert first.package_id != second.package_id
    assert not hasattr(first, "locator")
    manifest = store.validate(first)
    root = store.resolve_manifest(first).parent
    assert set(manifest["collections"]) == set(_COLLECTION_FILES)
    assert json.loads((root / "record-screening.jsonl").read_text())[
        "record_id"
    ] == "record-1"
    assert not tuple(root.rglob("*.md"))


def test_agent_executes_single_review_and_persists_compact_artifact(
    selection_protocol,
    tmp_path: Path,
) -> None:
    search_store, search = _persisted_search(tmp_path)
    runtime = FakeRuntime()
    selection_store = FileSelectionPackageStore(tmp_path / "selection")
    adapter = SelectStudiesTask(
        executor=_executor(runtime),
        search_package_store=search_store,
        selection_package_store=selection_store,
        run_id_factory=lambda role: f"selection-{role}",
    )

    completion = adapter.select(
        selection_protocol,
        search,
        TaskContext("review-1", selection_protocol.version),
    )

    assert completion.status is ArtifactStatus.COMPLETED
    assert completion.data is not None
    assert completion.data.package_ref.schema_version == "selection-package.v4"
    assert completion.data.summary.source_record_count == 1
    assert completion.data.summary.reports_assessed_count == 1
    assert completion.data.summary.included_count == 1
    assert completion.issues == ()
    request = runtime.requests[0]
    assert request.enable_web_search is True
    assert request.enable_workspace_network is True
    assert "agent_role" not in request.input_data
    assert {
        item["name"]
        for item in request.input_data["declared_tools"]
    } == {"package-selection"}
    declared_tools = {
        item["name"]: item
        for item in request.input_data["declared_tools"]
    }
    assert declared_tools["package-selection"]["usage"] == (
        "required_artifact_operation"
    )
    assert request.skill_paths == (
        _SKILL_ROOT.resolve(),
        _ACCESS_SKILL_ROOT.resolve(),
    )
    assert "selection_manifest" in request.output_artifacts
    selection_store.validate(completion.data.package_ref)


def test_completed_zero_record_search_produces_a_valid_empty_selection_package(
    selection_protocol,
    tmp_path: Path,
) -> None:
    search_store, search = _persisted_search(tmp_path, include_record=False)
    runtime = FakeRuntime()
    selection_store = FileSelectionPackageStore(tmp_path / "selection")
    adapter = SelectStudiesTask(
        executor=_executor(runtime),
        search_package_store=search_store,
        selection_package_store=selection_store,
    )

    completion = adapter.select(
        selection_protocol,
        search,
        TaskContext("review-1", selection_protocol.version),
    )

    assert completion.status is ArtifactStatus.COMPLETED
    assert completion.data is not None
    assert completion.data.summary.source_record_count == 0
    assert completion.data.summary.records_screened_count == 0
    assert completion.data.summary.study_count == 0
    assert completion.data.summary.included_count == 0
    manifest = selection_store.validate(completion.data.package_ref)
    assert all(
        item["record_count"] == 0
        for item in manifest["collections"].values()
    )


def test_summary_treats_failed_report_retrieval_as_not_retrieved(
    tmp_path: Path,
) -> None:
    store, search = _persisted_search(tmp_path)
    collections_snapshot = _load_search_snapshot(
        search, store.package_directory(search.package_ref)
    )
    collections = _collections("primary-agent")
    failed_observation = replace(
        collections.report_evidence[0],
        accessed=False,
        evidence_format="failed Report retrieval",
        summary="The sought Report could not be retrieved at this locator.",
    )

    summary = _build_summary(
        collections_snapshot,
        replace(collections, report_evidence=(failed_observation,)),
    )

    assert summary.reports_sought_count == 1
    assert summary.reports_assessed_count == 0
    assert summary.reports_not_retrieved_count == 1


def test_completed_selection_can_retain_inaccessible_awaiting_study(
    selection_protocol,
    tmp_path: Path,
) -> None:
    search_store, search = _persisted_search(tmp_path)
    runtime = FakeRuntime(
        classifications={
            "primary-agent": StudyClassification.AWAITING_CLASSIFICATION,
        },
        report_accessed=False,
    )
    adapter = SelectStudiesTask(
        executor=_executor(runtime),
        search_package_store=search_store,
        selection_package_store=FileSelectionPackageStore(
            tmp_path / "selection"
        ),
    )

    completion = adapter.select(
        selection_protocol,
        search,
        TaskContext("review-1", selection_protocol.version),
    )

    assert completion.status is ArtifactStatus.COMPLETED
    assert completion.data is not None
    assert completion.data.summary.reports_not_retrieved_count == 1
    assert completion.data.summary.awaiting_classification_count == 1
    assert completion.data.search_continuation.status.value == "proceed"


def test_structurally_valid_ungrouped_report_is_preserved(
    tmp_path: Path,
) -> None:
    store, search = _persisted_search(tmp_path)
    collections_snapshot = _load_search_snapshot(
        search, store.package_directory(search.package_ref)
    )
    collections = _collections("primary-agent")
    provenance = collections.reports[0].provenance
    second_report = Report(
        report_id="report-2",
        title="A report with unresolved Study identity",
        report_type="journal_article",
        provenance=provenance,
    )
    second_record_link = RecordReportLink(
        record_id="record-1",
        report_id="report-2",
        rationale="The source Record also identifies this Report.",
        provenance=provenance,
    )
    second_evidence = ReportEvidenceObservation(
        observation_id="observation-2",
        report_id="report-2",
        locator="https://example.test/2",
        evidence_format="failed Report retrieval",
        accessed=False,
        observed_at="2026-07-27T00:00:00Z",
        summary="The Report could not be retrieved.",
        provenance=provenance,
    )
    with_ungrouped_report = replace(
        collections,
        reports=collections.reports + (second_report,),
        record_report_links=(
            collections.record_report_links + (second_record_link,)
        ),
        report_evidence=collections.report_evidence + (second_evidence,),
    )

    _validate_selection_collections(
        with_ungrouped_report,
        collections_snapshot,
    )


def test_backend_accepts_professionally_incomplete_but_referentially_valid_output(
    tmp_path: Path,
) -> None:
    store, search = _persisted_search(tmp_path)
    collections_snapshot = _load_search_snapshot(
        search, store.package_directory(search.package_ref)
    )
    collections = _collections("primary-agent")
    incomplete = replace(
        collections,
        report_evidence=(),
        study_report_links=tuple(
            replace(link, is_primary=False)
            for link in collections.study_report_links
        ),
        study_decisions=(),
    )

    _validate_selection_collections(
        incomplete,
        collections_snapshot,
    )


def test_backend_preserves_long_report_evidence_without_text_length_gate(
    tmp_path: Path,
) -> None:
    store, search = _persisted_search(tmp_path)
    collections_snapshot = _load_search_snapshot(
        search, store.package_directory(search.package_ref)
    )
    collections = _collections("primary-agent")
    long_excerpt = "Directly reported eligibility criterion. " * 300
    observation = collections.report_evidence[0]
    evidence = replace(
        observation,
        summary=long_excerpt,
        provenance=(
            Provenance(
                source_id="report-1",
                source_type="report",
                locator="https://example.test/report-1",
                excerpt=long_excerpt,
            ),
        ),
    )

    _validate_selection_collections(
        replace(collections, report_evidence=(evidence,)),
        collections_snapshot,
    )


def test_backend_rejects_dangling_selection_reference(tmp_path: Path) -> None:
    store, search = _persisted_search(tmp_path)
    collections_snapshot = _load_search_snapshot(
        search, store.package_directory(search.package_ref)
    )
    collections = _collections("primary-agent")
    dangling = replace(
        collections,
        record_report_links=(
            replace(collections.record_report_links[0], report_id="missing-report"),
        ),
    )

    with pytest.raises(TaskOutputError, match="unknown entity"):
        _validate_selection_collections(
            dangling,
            collections_snapshot,
        )


def test_search_artifact_must_match_verified_search_package(
    protocol,
    tmp_path: Path,
) -> None:
    search_store, search = _persisted_search(tmp_path)
    mismatched = replace(
        search,
        sources=(
            replace(search.sources[0], result_count=2),
        ),
    )
    runtime = FakeRuntime()
    adapter = SelectStudiesTask(
        executor=_executor(runtime),
        search_package_store=search_store,
        selection_package_store=FileSelectionPackageStore(
            tmp_path / "selection"
        ),
    )

    with pytest.raises(TaskOutputError, match="runs do not match"):
        adapter.select(
            protocol,
            mismatched,
            TaskContext("review-1", protocol.version),
        )

    assert runtime.requests == []


def test_optional_process_reasons_are_not_fabricated_requirements() -> None:
    provenance = (
        Provenance("source-1", "record", "https://example.test/record"),
    )

    record = RecordScreeningDecision(
        record_id="record-1",
        screening_label="screened",
        advances_to_report_assessment=True,
        provenance=provenance,
    )
    decision = StudyEligibilityDecision(
        study_id="study-1",
        classification=StudyClassification.INCLUDED,
        provenance=provenance,
    )

    assert record.reason is None
    assert decision.reason is None


def test_backend_does_not_judge_unresolved_study_explanation() -> None:
    provenance = (
        Provenance("source-1", "report", "https://example.test/report"),
    )

    decision = StudyEligibilityDecision(
        study_id="study-1",
        classification=StudyClassification.AWAITING_CLASSIFICATION,
        provenance=provenance,
    )

    assert decision.reason is None


def test_package_selection_script_accepts_omitted_optional_reasons(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    collections = _collections("primary-agent")
    for name, filename in _COLLECTION_FILES.items():
        rows = [_jsonable(value) for value in getattr(collections, name)]
        for row in rows:
            if name in {"record_screening", "study_decisions"}:
                row.pop("reason", None)
        (input_dir / filename).write_bytes(_jsonl(rows))

    result = subprocess.run(
        [
            sys.executable,
            str(_SKILL_ROOT / "scripts/package_selection.py"),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_package_selection_script_rejects_full_text_fields(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    for filename in _COLLECTION_FILES.values():
        (input_dir / filename).write_text("", encoding="utf-8")
    (input_dir / "reports.jsonl").write_text(
        json.dumps({"report_id": "r1", "full_text": "not allowed"}) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(_SKILL_ROOT / "scripts/package_selection.py"),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "prohibited full-text field" in result.stderr


def test_select_studies_skill_loads_with_repository_validator() -> None:
    package = load_skill(_SKILL_ROOT)

    assert package.name == "select-studies"
    assert len(package.sha256) == 64


def _persisted_search(
    tmp_path: Path,
    *,
    include_record: bool = True,
) -> tuple[FileSearchPackageStore, EvidenceSearchPublicArtifact]:
    source = Provenance("source-1", "search_source", "https://example.test/1")
    run = SearchRun(
        search_run_id="run-1",
        source_name="PubMed",
        platform="NCBI",
        query="randomized trial",
        executed_at="2026-07-27T00:00:00Z",
        status=SearchRunStatus.SUCCEEDED,
        result_count=int(include_record),
        provenance=(source,),
        retrieved_count=int(include_record),
        status_reason=None,
        search_narrative="Test search.",
    )
    record = Record(
        record_id="record-1",
        source_name="PubMed",
        platform="NCBI",
        source_record_id="1",
        title="A randomized trial",
        abstract="Adults were randomized to intervention or control.",
        search_run_ids=("run-1",),
        provenance=(source,),
    )
    records = (record,) if include_record else ()
    unpersisted = EvidenceSearchArtifact(
        search_runs=(run,),
        records=records,
        summary=SearchSummary(1, 1, len(records)),
    )
    store = FileSearchPackageStore(tmp_path / "search")
    reference = store.persist(
        review_id="review-1",
        protocol_version="protocol-1",
        artifact=unpersisted,
    )
    return store, public_search_artifact(
        EvidenceSearchArtifact(
            search_runs=unpersisted.search_runs,
            records=unpersisted.records,
            summary=unpersisted.summary,
            package_ref=reference,
        )
    )


def _collections(
    agent_role: str,
    *,
    report_id: str = "report-1",
    study_id: str = "study-1",
    conflict_targets: tuple[str, ...] = (),
    classification: StudyClassification = StudyClassification.INCLUDED,
    screening_label: str = "screened",
    report_accessed: bool = True,
) -> SelectionCollections:
    provenance = (Provenance("source-1", "report", "https://example.test/1"),)
    conflicts = (
        (
            SelectionConflict(
                conflict_id=f"conflict-{agent_role}",
                kind="report identity uncertainty",
                target_ids=conflict_targets,
                resolved=False,
                description="Report identity needs confirmation.",
                provenance=provenance,
            ),
        )
        if conflict_targets
        else ()
    )
    return SelectionCollections(
        record_screening=(
            RecordScreeningDecision(
                record_id="record-1",
                screening_label=screening_label,
                advances_to_report_assessment=True,
                reason="Potentially eligible.",
                provenance=provenance,
            ),
        ),
        reports=(
            Report(
                report_id=report_id,
                title="A randomized trial",
                report_type="journal_article",
                external_identifiers=("doi:10.1000/example",),
                locators=("https://example.test/1",),
                provenance=provenance,
            ),
        ),
        report_discoveries=(),
        record_report_links=(
            RecordReportLink(
                record_id="record-1",
                report_id=report_id,
                rationale="The PubMed Record describes this Report.",
                provenance=provenance,
            ),
        ),
        report_evidence=(
            ReportEvidenceObservation(
                observation_id=f"observation-{agent_role}",
                report_id=report_id,
                locator="https://example.test/1",
                evidence_format=(
                    "HTML full report"
                    if report_accessed
                    else "unavailable journal Report"
                ),
                accessed=report_accessed,
                observed_at="2026-07-27T00:00:00Z",
                summary=(
                    "The report describes an eligible randomized trial."
                    if report_accessed
                    else "Reasonable legitimate checking did not yield the Report."
                ),
                provenance=provenance,
            ),
        ),
        studies=(
            Study(
                study_id=study_id,
                display_name="Example 2026",
                provenance=provenance,
            ),
        ),
        study_report_links=(
            StudyReportLink(
                study_id=study_id,
                report_id=report_id,
                is_primary=True,
                rationale="Only complete results report.",
                provenance=provenance,
            ),
        ),
        study_decisions=(
            StudyEligibilityDecision(
                study_id=study_id,
                classification=classification,
                reason=(
                    "The Study meets all Protocol eligibility criteria."
                    if classification is StudyClassification.INCLUDED
                    else (
                        "The Study uses an ineligible design."
                        if classification is StudyClassification.EXCLUDED
                        else (
                            "Eligibility remains uncertain because the complete "
                            "Report was unavailable."
                            if classification
                            is StudyClassification.AWAITING_CLASSIFICATION
                            else "The Study is ongoing."
                        )
                    )
                ),
                primary_exclusion_criterion=(
                    "Types of studies: the design is not randomized."
                    if classification is StudyClassification.EXCLUDED
                    else None
                ),
                follow_up_actions=(
                    ("Reassess when a complete Report becomes available.",)
                    if classification
                    is StudyClassification.AWAITING_CLASSIFICATION
                    else ()
                ),
                provenance=provenance,
            ),
        ),
        conflicts=conflicts,
    )


def _selection_artifacts(
    agent_role: str,
    *,
    classification: StudyClassification = StudyClassification.INCLUDED,
    report_accessed: bool = True,
    empty: bool = False,
) -> dict[str, AgentOutputArtifact]:
    collections = (
        SelectionCollections((), (), (), (), (), (), (), (), ())
        if empty
        else _collections(
            agent_role,
            classification=classification,
            report_accessed=report_accessed,
        )
    )
    artifacts: dict[str, AgentOutputArtifact] = {}
    manifest_collections: dict[str, dict[str, object]] = {}
    for name, filename in _COLLECTION_FILES.items():
        values = getattr(collections, name)
        content = _jsonl([_jsonable(value) for value in values])
        artifact_name = name
        relative = f"outputs/selection/{filename}"
        artifacts[artifact_name] = AgentOutputArtifact(
            artifact_name,
            relative,
            content,
            _digest(content),
        )
        manifest_collections[name] = {
            "path": filename,
            "sha256": _digest(content),
            "record_count": len(values),
        }
    manifest = {
        "schema_version": "agent-selection-output.v3",
        "created_at": "2026-07-27T00:00:00Z",
        "collections": manifest_collections,
    }
    manifest_content = (
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        + b"\n"
    )
    artifacts["selection_manifest"] = AgentOutputArtifact(
        "selection_manifest",
        "outputs/selection/manifest.json",
        manifest_content,
        _digest(manifest_content),
    )
    return artifacts


def _jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _jsonable(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return value.value
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


def _jsonl(values: list[object]) -> bytes:
    lines = [
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        for value in values
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _digest(content: bytes) -> str:
    return f"sha256:{sha256(content).hexdigest()}"
