from __future__ import annotations

from hashlib import sha256
import importlib.util
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
    EvidenceSearchInput,
    EvidenceSearchMode,
    Record,
    RecordRelation,
    SearchRun,
    SearchRunStatus,
    SearchSummary,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    AgentAccessMode,
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
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.evidence_search import (
    SearchEvidenceTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.packages import (
    FileSearchPackageStore,
)


_SKILL_ROOT = (
    Path(__file__).parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/"
    "agent_execution/skills/evidence_search/evidence-search"
)


def _executor(runtime) -> AgentTaskExecutorAdapter:
    return AgentTaskExecutorAdapter(runtime, (_SKILL_ROOT,))


class FakeRuntime:
    provider = AgentProvider.OPENAI

    def __init__(
        self,
        output: Mapping[str, Any],
        output_artifacts: Mapping[str, AgentOutputArtifact] | None = None,
    ) -> None:
        self.output = output
        self.output_artifacts = output_artifacts or {}
        self.requests: list[AgentRunRequest] = []

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        return AgentRunResult(
            provider=self.provider,
            model="openai/gpt-5.6-terra",
            run_id=request.run_id,
            session_id="session-search",
            output=self.output,
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
                AgentSkillSnapshot(
                    name="evidence-search",
                    sha256="b" * 64,
                ),
            ),
            output_artifacts=self.output_artifacts,
        )


def _agent_output(status: str = "completed") -> dict[str, object]:
    if status == "blocked":
        return {
            "status": status,
            "data": None,
            "issues": [
                {
                    "code": "search_blocked",
                    "message": "No source produced a usable Search Run.",
                    "severity": "error",
                }
            ],
        }
    return {
        "status": status,
        "data": {
            "artifact_schema_version": "agent-search-output.v1",
            "execution_summary": "MEDLINE ran; registry access unavailable.",
        },
        "issues": [
            {
                "code": (
                    "search_work_unfinished"
                    if status == "partial"
                    else "registry_unavailable"
                ),
                "message": (
                    "Required professional review remains unfinished."
                    if status == "partial"
                    else "No registry execution tool is configured."
                ),
                "severity": "warning",
            }
        ],
    }


def _artifact_files(
    *,
    include_registry: bool = True,
    medline_status: str = "succeeded",
    registry_status: str = "unavailable",
):
    provenance = [
        {
            "source_id": "test-source",
            "source_type": "search_source:test",
            "locator": "https://example.test/search",
            "excerpt": None,
        }
    ]
    medline_usable = medline_status in {"succeeded", "partial"}
    runs = [
        {
            "search_run_id": "run-medline",
            "source_name": "MEDLINE",
            "platform": "Test platform",
            "query": "(intervention) AND (randomized)",
            "executed_at": "2026-07-26T00:00:00+00:00",
            "status": medline_status,
            "result_count": 1 if medline_usable else 0,
            "retrieved_count": 1 if medline_usable else 0,
            "status_reason": (
                None
                if medline_status == "succeeded"
                else f"MEDLINE source ended as {medline_status}."
            ),
            "search_narrative": "Test search.",
            "provenance": provenance,
        }
    ]
    if include_registry:
        runs.append(
            {
                "search_run_id": "run-registry",
                "source_name": "ClinicalTrials.gov",
                "platform": "ClinicalTrials.gov",
                "query": "intervention | adults",
                "executed_at": "2026-07-26T00:00:00+00:00",
                "status": registry_status,
                "result_count": 0,
                "retrieved_count": 0,
                "status_reason": (
                    None
                    if registry_status == "succeeded"
                    else f"Registry source ended as {registry_status}."
                ),
                "search_narrative": "Source unavailable.",
                "provenance": provenance,
            }
        )
    records = (
        [
            {
                "record_id": "test:1",
                "source_name": "MEDLINE",
                "platform": "Test platform",
                "source_record_id": "1",
                "source_record_type": "bibliographic_record",
                "source_data": {},
                "title": "A trial",
                "citation": "Journal; 2026",
                "abstract": None,
                "external_identifiers": [],
                "publication_types": ["Randomized Controlled Trial"],
                "related_records": [
                    {
                        "relation_type": "ErratumIn",
                        "related_source_record_id": "2",
                        "citation": "Correction notice",
                        "note": None,
                    }
                ],
                "locators": [],
                "search_run_ids": ["run-medline"],
                "provenance": provenance,
            }
        ]
        if medline_usable
        else []
    )
    runs_bytes = _jsonl(runs)
    records_bytes = _jsonl(records)
    manifest = {
        "schema_version": "agent-search-output.v1",
        "created_at": "2026-07-26T00:00:00+00:00",
        "summary": {
            "run_count": len(runs),
            "source_count": len(runs),
            "record_count": len(records),
        },
        "collections": {
            "search_runs": {
                "path": "search-runs.jsonl",
                "sha256": _digest(runs_bytes),
                "record_count": len(runs),
            },
            "records": {
                "path": "records.jsonl",
                "sha256": _digest(records_bytes),
                "record_count": len(records),
            },
        },
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    return {
        "search_manifest": AgentOutputArtifact(
            "search_manifest",
            "outputs/search/manifest.json",
            manifest_bytes,
            _digest(manifest_bytes),
        ),
        "search_runs": AgentOutputArtifact(
            "search_runs",
            "outputs/search/search-runs.jsonl",
            runs_bytes,
            _digest(runs_bytes),
        ),
        "search_records": AgentOutputArtifact(
            "search_records",
            "outputs/search/records.jsonl",
            records_bytes,
            _digest(records_bytes),
        ),
    }


def test_agent_executes_task_and_backend_validates_and_persists_artifacts(
    protocol,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PUBMED_TOOL_EMAIL", "tester@example.com")
    runtime = FakeRuntime(_agent_output(), _artifact_files())
    store = FileSearchPackageStore(tmp_path / "packages")
    adapter = SearchEvidenceTask(
        executor=_executor(runtime),
        package_store=store,
        run_id_factory=lambda: "search-test",
    )

    completion = adapter.search(
        protocol,
        TaskContext("review-1", protocol.version),
    )
    request = runtime.requests[0]

    assert completion.status is ArtifactStatus.COMPLETED
    assert completion.data is not None
    assert completion.data.summary == SearchSummary(2, 2, 1)
    assert completion.data.records[0].publication_types == (
        "Randomized Controlled Trial",
    )
    assert completion.data.records[0].related_records[0].relation_type == "ErratumIn"
    assert completion.data.package_ref is not None
    assert store.validate(completion.data.package_ref)["summary"]["record_count"] == 1
    assert request.access_mode is AgentAccessMode.WORKSPACE_WRITE
    assert request.enable_workspace_network is True
    assert request.enable_web_search is True
    assert request.skill_paths[0].name == "evidence-search"
    assert request.output_artifacts["search_records"].endswith("records.jsonl")
    assert "planned baselines" in request.prompt
    assert "why it was not executed" in request.prompt
    assert "explicit authorization for external communication" in request.prompt
    assert "script availability must not determine" in request.prompt
    declared = request.input_data["declared_tools"]
    assert [item["name"] for item in declared[:3]] == [
        "provider-native-web",
        "workspace-network",
        "pubmed-eutilities",
    ]
    assert declared[2]["available"] is True
    assert "Optionally" in declared[2]["purpose"]
    assert "prerequisite evidence" in declared[3]["purpose"]
    assert "external-action authorization" in declared[3]["purpose"]


def test_agent_task_status_is_not_inferred_from_search_run_statuses(
    protocol,
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime(
        _agent_output("partial"),
        _artifact_files(registry_status="succeeded"),
    )
    adapter = SearchEvidenceTask(
        executor=_executor(runtime),
        package_store=FileSearchPackageStore(tmp_path),
    )

    completion = adapter.search(
        protocol,
        TaskContext("review-1", protocol.version),
    )

    assert completion.status is ArtifactStatus.PARTIAL
    assert all(
        run.status is SearchRunStatus.SUCCEEDED for run in completion.data.search_runs
    )


def test_nonblocked_initial_search_requires_a_usable_search_run(
    protocol,
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime(
        _agent_output("completed"),
        _artifact_files(medline_status="failed"),
    )
    adapter = SearchEvidenceTask(
        executor=_executor(runtime),
        package_store=FileSearchPackageStore(tmp_path),
    )

    with pytest.raises(TaskOutputError, match="at least one usable Search Run"):
        adapter.search(protocol, TaskContext("review-1", protocol.version))


def test_initial_search_with_no_usable_source_can_return_blocked(
    protocol,
    tmp_path: Path,
) -> None:
    adapter = SearchEvidenceTask(
        executor=_executor(FakeRuntime(_agent_output("blocked"), {})),
        package_store=FileSearchPackageStore(tmp_path),
    )

    completion = adapter.search(
        protocol,
        TaskContext("review-1", protocol.version),
    )

    assert completion.status is ArtifactStatus.BLOCKED
    assert completion.data is None
    assert completion.issues[0].code == "search_blocked"


def test_completed_supplementary_round_can_preserve_only_failed_observations(
    protocol,
    tmp_path: Path,
) -> None:
    source = Provenance("parent-source", "search_source", "test://parent")
    parent = EvidenceSearchArtifact(
        search_runs=(
            SearchRun(
                search_run_id="parent-run",
                source_name="Parent source",
                platform="Parent platform",
                query="parent query",
                executed_at="2026-08-01T00:00:00Z",
                status=SearchRunStatus.SUCCEEDED,
                result_count=0,
                retrieved_count=0,
                status_reason=None,
                search_narrative="The parent search completed with no Records.",
                provenance=(source,),
            ),
        ),
        records=(),
        summary=SearchSummary(1, 1, 0),
    )
    store = FileSearchPackageStore(tmp_path / "packages")
    parent_ref = store.persist(
        review_id="review-1",
        protocol_version=protocol.version,
        artifact=parent,
    )
    runtime = FakeRuntime(
        _agent_output("completed"),
        _artifact_files(include_registry=False, medline_status="failed"),
    )
    adapter = SearchEvidenceTask(
        executor=_executor(runtime),
        package_store=store,
    )

    completion = adapter.search(
        protocol,
        TaskContext("review-1", protocol.version),
        EvidenceSearchInput(
            protocol=protocol,
            mode=EvidenceSearchMode.SUPPLEMENTARY,
            parent_package_ref=parent_ref,
            supplementary_reason="A concrete follow-up search was attempted.",
        ),
    )

    assert completion.status is ArtifactStatus.COMPLETED
    assert completion.data.summary == SearchSummary(2, 2, 0)
    assert tuple(run.status for run in completion.data.search_runs) == (
        SearchRunStatus.SUCCEEDED,
        SearchRunStatus.FAILED,
    )


def test_agent_artifacts_must_cover_every_protocol_source(
    protocol,
    tmp_path: Path,
) -> None:
    adapter = SearchEvidenceTask(
        executor=_executor(
            FakeRuntime(
                _agent_output(),
                _artifact_files(include_registry=False),
            )
        ),
        package_store=FileSearchPackageStore(tmp_path),
    )

    with pytest.raises(TaskOutputError, match="missing"):
        adapter.search(protocol, TaskContext("review-1", protocol.version))


def test_nonblocked_agent_requires_canonical_artifacts(
    protocol,
    tmp_path: Path,
) -> None:
    adapter = SearchEvidenceTask(
        executor=_executor(FakeRuntime(_agent_output())),
        package_store=FileSearchPackageStore(tmp_path),
    )

    with pytest.raises(
        TaskOutputError,
        match="required search artifacts",
    ) as captured:
        adapter.search(protocol, TaskContext("review-1", protocol.version))

    assert captured.value.diagnostic() == {
        "error_code": "artifact_bundle_invalid",
        "message": (
            "Agent did not create required search artifacts: "
            "['search_manifest', 'search_records', 'search_runs']"
        ),
        "stage": "bundle_integrity",
        "artifact": "search:output bundle",
        "location": "/artifacts",
        "contract_version": "agent-search-output.v1",
    }


def test_search_package_detects_tampering(tmp_path: Path) -> None:
    source = Provenance("source-1", "test", "test://source")
    run = SearchRun(
        search_run_id="run-1",
        source_name="PubMed",
        platform="NCBI",
        query="query",
        executed_at="2026-07-26T00:00:00Z",
        status=SearchRunStatus.SUCCEEDED,
        result_count=0,
        provenance=(source,),
        retrieved_count=0,
        status_reason=None,
        search_narrative="Test search.",
    )
    artifact = EvidenceSearchArtifact(
        search_runs=(run,),
        records=(),
        summary=SearchSummary(1, 1, 0),
    )
    store = FileSearchPackageStore(tmp_path)
    reference = store.persist(
        review_id="review-1",
        protocol_version="protocol-1",
        artifact=artifact,
    )

    manifest_path = store.resolve_manifest(reference)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs_path = manifest_path.parent / manifest["collections"]["search_runs"]["path"]
    runs_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="digest mismatch"):
        store.validate(reference)


def test_search_package_retries_create_distinct_immutable_references(
    tmp_path: Path,
) -> None:
    source = Provenance("source-1", "test", "test://source")
    run = SearchRun(
        search_run_id="run-1",
        source_name="PubMed",
        platform="NCBI",
        query="query",
        executed_at="2026-07-26T00:00:00Z",
        status=SearchRunStatus.SUCCEEDED,
        result_count=0,
        provenance=(source,),
        retrieved_count=0,
        status_reason=None,
        search_narrative="Test search.",
    )
    artifact = EvidenceSearchArtifact(
        search_runs=(run,),
        records=(),
        summary=SearchSummary(1, 1, 0),
    )
    store = FileSearchPackageStore(tmp_path)
    first = store.persist(
        review_id="review-1",
        protocol_version="protocol-1",
        artifact=artifact,
    )
    second = store.persist(
        review_id="review-1",
        protocol_version="protocol-1",
        artifact=artifact,
    )

    assert first.package_id != second.package_id
    assert store.resolve_manifest(first).parent != store.resolve_manifest(second).parent
    store.validate(first)
    store.validate(second)


def test_search_package_load_round_trips_domain_artifact(tmp_path: Path) -> None:
    source = Provenance("source-1", "test", "test://source")
    run = SearchRun(
        search_run_id="run-1",
        source_name="PubMed",
        platform="NCBI",
        query="query",
        executed_at="2026-07-26T00:00:00Z",
        status=SearchRunStatus.SUCCEEDED,
        result_count=0,
        provenance=(source,),
        retrieved_count=0,
        status_reason=None,
        search_narrative="Test search.",
    )
    artifact = EvidenceSearchArtifact(
        search_runs=(run,), records=(), summary=SearchSummary(1, 1, 0)
    )
    store = FileSearchPackageStore(tmp_path)
    reference = store.persist(
        review_id="review-1", protocol_version="protocol-1", artifact=artifact
    )

    loaded = store.load(reference)
    assert loaded.search_runs == artifact.search_runs
    assert loaded.records == artifact.records
    assert loaded.summary == artifact.summary


def test_search_package_preserves_publication_types_and_related_records(
    tmp_path: Path,
) -> None:
    source = Provenance("pubmed", "search_source:PubMed", "https://pubmed.test")
    run = SearchRun(
        search_run_id="run-1",
        source_name="MEDLINE",
        platform="PubMed",
        query="intervention[Title/Abstract]",
        executed_at="2026-07-26T00:00:00Z",
        status=SearchRunStatus.SUCCEEDED,
        result_count=1,
        provenance=(source,),
        retrieved_count=1,
        status_reason=None,
        search_narrative="Test search.",
    )
    record = Record(
        record_id="pubmed:123",
        source_name="MEDLINE",
        platform="PubMed",
        source_record_id="123",
        publication_types=("Retracted Publication",),
        related_records=(
            RecordRelation(
                relation_type="RetractionIn",
                related_source_record_id="999",
                citation="Retraction notice. Test Journal. 2027.",
            ),
        ),
        search_run_ids=("run-1",),
        provenance=(source,),
    )
    artifact = EvidenceSearchArtifact(
        search_runs=(run,),
        records=(record,),
        summary=SearchSummary(1, 1, 1),
    )
    store = FileSearchPackageStore(tmp_path)
    reference = store.persist(
        review_id="review-1",
        protocol_version="protocol-1",
        artifact=artifact,
    )

    records_path = store.resolve_manifest(reference).parent / "records.jsonl"
    persisted = json.loads(records_path.read_text(encoding="utf-8"))

    assert persisted["publication_types"] == ["Retracted Publication"]
    assert persisted["related_records"][0]["relation_type"] == "RetractionIn"
    assert persisted["related_records"][0]["related_source_record_id"] == "999"
    store.validate(reference)


def test_pubmed_skill_tool_parses_metadata_without_full_text() -> None:
    module = _load_script("pubmed_search.py")
    search_xml = b"<eSearchResult><Count>1</Count><IdList/></eSearchResult>"
    page_xml = (
        b"<eSearchResult><Count>1</Count><IdList><Id>123</Id></IdList></eSearchResult>"
    )
    fetch_xml = b"""\
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>123</PMID>
      <Article>
        <ArticleTitle>A randomized trial</ArticleTitle>
        <Abstract><AbstractText>Trial abstract.</AbstractText></Abstract>
        <PublicationTypeList>
          <PublicationType>Randomized Controlled Trial</PublicationType>
          <PublicationType>Retracted Publication</PublicationType>
        </PublicationTypeList>
        <Journal><Title>Test Journal</Title><JournalIssue>
          <PubDate><Year>2026</Year></PubDate>
        </JournalIssue></Journal>
      </Article>
      <CommentsCorrectionsList>
        <CommentsCorrections RefType="RetractionIn">
          <RefSource>Retraction notice. Test Journal. 2027.</RefSource>
          <PMID>999</PMID>
          <Note>Retracted by the publisher.</Note>
        </CommentsCorrections>
      </CommentsCorrectionsList>
    </MedlineCitation>
    <PubmedData><ArticleIdList>
      <ArticleId IdType="pubmed">123</ArticleId>
      <ArticleId IdType="doi">10.1000/test</ArticleId>
    </ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""
    responses = iter((search_xml, page_xml, fetch_xml))
    client = module.PubMedClient(email="tester@example.com", api_key=None)
    client._request = lambda endpoint, params: next(responses)

    result = client.search(
        query="intervention[Title/Abstract]",
        run_id="run-1",
        source_name="MEDLINE",
        platform="PubMed",
        page_size=500,
        max_records=10_000,
    )

    assert result["search_run"]["result_count"] == 1
    assert len(result["records"]) == 1
    record = result["records"][0]
    assert record["source_record_id"] == "123"
    assert record["source_record_type"] == "bibliographic_record"
    assert record["source_data"] == {}
    assert record["abstract"] == "Trial abstract."
    assert {item["scheme"] for item in record["external_identifiers"]} == {
        "pmid",
        "doi",
    }
    assert record["publication_types"] == [
        "Randomized Controlled Trial",
        "Retracted Publication",
    ]
    assert record["related_records"] == [
        {
            "relation_type": "RetractionIn",
            "related_source_record_id": "999",
            "citation": "Retraction notice. Test Journal. 2027.",
            "note": "Retracted by the publisher.",
        }
    ]
    assert "full_text" not in record


def test_pubmed_skill_tool_preserves_book_article_records() -> None:
    module = _load_script("pubmed_search.py")
    search_xml = b"<eSearchResult><Count>1</Count><IdList/></eSearchResult>"
    page_xml = (
        b"<eSearchResult><Count>1</Count><IdList><Id>456</Id></IdList></eSearchResult>"
    )
    fetch_xml = b"""\
<PubmedArticleSet>
  <PubmedBookArticle>
    <BookDocument>
      <PMID Version="1">456</PMID>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1000/book-chapter</ArticleId>
      </ArticleIdList>
      <Book>
        <Publisher><PublisherName>Test Publisher</PublisherName></Publisher>
        <BookTitle>Evidence Methods</BookTitle>
        <PubDate><Year>2025</Year></PubDate>
        <Volume>2</Volume>
        <Edition>Second edition</Edition>
      </Book>
      <LocationLabel>Chapter 4</LocationLabel>
      <ArticleTitle>Searching for studies</ArticleTitle>
      <Pagination><StartPage>10</StartPage><EndPage>20</EndPage></Pagination>
      <PublicationType UI="D016454">Review</PublicationType>
      <Abstract><AbstractText>Book chapter abstract.</AbstractText></Abstract>
    </BookDocument>
    <PubmedBookData>
      <PublicationStatus>ppublish</PublicationStatus>
      <ArticleIdList>
        <ArticleId IdType="pubmed">456</ArticleId>
      </ArticleIdList>
    </PubmedBookData>
  </PubmedBookArticle>
</PubmedArticleSet>
"""
    responses = iter((search_xml, page_xml, fetch_xml))
    client = module.PubMedClient(email="tester@example.com", api_key=None)
    client._request = lambda endpoint, params: next(responses)

    result = client.search(
        query="evidence methods",
        run_id="run-book",
        source_name="MEDLINE",
        platform="PubMed",
        page_size=500,
        max_records=10_000,
    )

    assert result["search_run"]["status"] == "succeeded"
    assert result["search_run"]["status_reason"] is None
    assert result["tool_observation"]["incomplete_export"] is False
    record = result["records"][0]
    assert record["source_record_id"] == "456"
    assert record["source_record_type"] == "pubmed_book_article"
    assert record["title"] == "Searching for studies"
    assert record["abstract"] == "Book chapter abstract."
    assert record["publication_types"] == ["Review"]
    assert record["source_data"] == {
        "pubmed_record_kind": "pubmed_book_article",
        "book_title": "Evidence Methods",
        "location_labels": ["Chapter 4"],
    }
    assert "Evidence Methods; 2025; volume 2" in record["citation"]
    assert {item["scheme"] for item in record["external_identifiers"]} == {
        "pmid",
        "doi",
    }


def test_pubmed_skill_tool_does_not_mislabel_incomplete_export_as_ceiling() -> None:
    module = _load_script("pubmed_search.py")
    search_xml = b"<eSearchResult><Count>2</Count><IdList/></eSearchResult>"
    page_xml = (
        b"<eSearchResult><Count>2</Count><IdList><Id>123</Id></IdList></eSearchResult>"
    )
    fetch_xml = b"""\
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>123</PMID>
      <Article>
        <ArticleTitle>One returned record</ArticleTitle>
        <Journal><Title>Test Journal</Title><JournalIssue>
          <PubDate><Year>2026</Year></PubDate>
        </JournalIssue></Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""
    responses = iter((search_xml, page_xml, fetch_xml))
    client = module.PubMedClient(email="tester@example.com", api_key=None)
    client._request = lambda endpoint, params: next(responses)

    result = client.search(
        query="intervention",
        run_id="run-incomplete",
        source_name="MEDLINE",
        platform="PubMed",
        page_size=500,
        max_records=10_000,
    )

    reason = result["search_run"]["status_reason"]
    assert result["search_run"]["status"] == "partial"
    assert "complete paged E-utilities export" in reason
    assert "safety ceiling" not in reason
    assert result["tool_observation"]["limited_by_safety_ceiling"] is False
    assert result["tool_observation"]["incomplete_export"] is True


def test_pubmed_skill_tool_reports_real_safety_ceiling() -> None:
    module = _load_script("pubmed_search.py")
    search_xml = b"<eSearchResult><Count>2</Count><IdList/></eSearchResult>"
    page_xml = (
        b"<eSearchResult><Count>2</Count><IdList><Id>123</Id></IdList></eSearchResult>"
    )
    fetch_xml = b"""\
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>123</PMID>
      <Article>
        <ArticleTitle>One ceiling-limited record</ArticleTitle>
        <Journal><Title>Test Journal</Title><JournalIssue>
          <PubDate><Year>2026</Year></PubDate>
        </JournalIssue></Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""
    responses = iter((search_xml, page_xml, fetch_xml))
    client = module.PubMedClient(email="tester@example.com", api_key=None)
    client._request = lambda endpoint, params: next(responses)

    result = client.search(
        query="intervention",
        run_id="run-ceiling",
        source_name="MEDLINE",
        platform="PubMed",
        page_size=500,
        max_records=1,
    )

    reason = result["search_run"]["status_reason"]
    assert result["search_run"]["status"] == "partial"
    assert (
        reason == "Retrieved the configured safety ceiling of 1 from 2 source results."
    )
    assert result["tool_observation"]["limited_by_safety_ceiling"] is True
    assert result["tool_observation"]["incomplete_export"] is False


def test_package_tool_rejects_record_source_that_differs_from_run() -> None:
    module = _load_script("package_search.py")
    runs = [
        {
            "search_run_id": "run-1",
            "source_name": "MEDLINE",
            "platform": "PubMed",
        }
    ]
    records = [
        {
            "record_id": "record-1",
            "source_name": "Embase",
            "platform": "Embase.com",
            "source_record_id": "123",
            "search_run_ids": ["run-1"],
            "provenance": [{"source_id": "123"}],
        }
    ]

    with pytest.raises(ValueError, match="source and platform"):
        module._validate_identity(runs, records)


def test_skill_scripts_build_canonical_artifacts(tmp_path: Path) -> None:
    queries = tmp_path / "queries"
    sources = tmp_path / "sources"
    output = tmp_path / "output"
    queries.mkdir()
    (queries / "registry.txt").write_text("intervention", encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(_SKILL_ROOT / "scripts/source_status.py"),
            "--query-file",
            str(queries / "registry.txt"),
            "--output",
            str(sources / "registry.json"),
            "--run-id",
            "registry-run",
            "--source-name",
            "ClinicalTrials.gov",
            "--platform",
            "ClinicalTrials.gov",
            "--status",
            "unavailable",
            "--reason",
            "No authorized tool.",
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(_SKILL_ROOT / "scripts/package_search.py"),
            "--sources-dir",
            str(sources),
            "--output-dir",
            str(output),
        ],
        check=True,
    )

    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["schema_version"] == "agent-search-output.v1"
    assert manifest["summary"] == {
        "run_count": 1,
        "source_count": 1,
        "record_count": 0,
    }
    run = json.loads((output / "search-runs.jsonl").read_text())
    assert run["status"] == "unavailable"
    assert run["query"] == "intervention"
    assert run["result_count"] == 0
    assert run["provenance"][0]["excerpt"] == "No authorized tool."
    assert (output / "search-runs.jsonl").is_file()
    assert (output / "records.jsonl").is_file()


def test_package_search_rejects_nested_shape_drift_before_manifest(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    output = tmp_path / "output"
    sources.mkdir()
    (sources / "pubmed.json").write_text(
        json.dumps(
            {
                "schema_version": "source-result.v2",
                "search_run": {
                    "search_run_id": "run-1",
                    "source_name": "MEDLINE",
                    "platform": "PubMed",
                    "query": "intervention",
                    "executed_at": "2026-07-30T00:00:00Z",
                    "status": "succeeded",
                    "result_count": 1,
                    "retrieved_count": 1,
                    "status_reason": None,
                    "search_narrative": "Test search.",
                    "provenance": [
                        {
                            "source_id": "source-1",
                            "source_type": "database",
                        }
                    ],
                },
                "records": [
                    {
                        "record_id": "record-1",
                        "source_name": "MEDLINE",
                        "platform": "PubMed",
                        "source_record_id": "1",
                        "related_records": [{"type": "RetractionIn"}],
                        "search_run_ids": ["run-1"],
                        "provenance": [
                            {
                                "source_id": "source-1",
                                "source_type": "database",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(_SKILL_ROOT / "scripts/package_search.py"),
            "--sources-dir",
            str(sources),
            "--output-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "/records/0/related_records/0" in result.stderr
    assert not (output / "manifest.json").exists()


def test_source_status_records_missing_prior_evidence_without_records(
    tmp_path: Path,
) -> None:
    procedure = tmp_path / "reference-lists.txt"
    result_path = tmp_path / "reference-lists.json"
    procedure.write_text(
        "Check reference lists of included Reports.",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(_SKILL_ROOT / "scripts/source_status.py"),
            "--query-file",
            str(procedure),
            "--output",
            str(result_path),
            "--run-id",
            "reference-list-run",
            "--source-name",
            "Reference-list searching",
            "--platform",
            "Included Reports",
            "--status",
            "unavailable",
            "--reason",
            "Included Reports are not available in this invocation.",
        ],
        check=True,
    )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["search_run"]["status"] == "unavailable"
    assert result["search_run"]["query"] == (
        "Check reference lists of included Reports."
    )
    assert result["search_run"]["result_count"] == 0
    assert result["records"] == []
    assert result["tool_observation"]["reason"] == (
        "Included Reports are not available in this invocation."
    )


def test_repository_loader_accepts_evidence_search_skill() -> None:
    package = load_skill(_SKILL_ROOT)

    assert package.name == "evidence-search"
    assert len(package.sha256) == 64


def _jsonl(values: list[dict[str, object]]) -> bytes:
    return (
        "\n".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return f"sha256:{sha256(value).hexdigest()}"


def _load_script(name: str):
    path = _SKILL_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        f"evidence_search_{path.stem}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
