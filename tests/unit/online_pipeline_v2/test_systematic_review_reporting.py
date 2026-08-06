from __future__ import annotations

from dataclasses import replace
import json

import pytest
from pydantic import TypeAdapter, ValidationError

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    TaskContext,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    EmptyReviewContext,
    ReviewDocumentMaturity,
    ReviewDisplay,
    ReviewDisplayKind,
    ReviewDisplayLocation,
    ReviewPath,
    ReviewSectionName,
    ReportingMethodDecision,
    SystematicReviewDraft,
    SystematicReviewReportingInput,
    SystematicReviewSectionDraft,
)
from ebm_backend.online_pipeline_v2.domain.protocol import (
    MethodologyBasisStatus,
    MethodologyProfile,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.systematic_review import (
    systematic_review_agent_output_adapter,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.systematic_review import (
    FileSystematicReviewArtifactStore,
    FileSystematicReviewEvidencePackageStore,
)
from ebm_backend.online_pipeline_v2.infrastructure.systematic_review.reporting_index import (
    build_reporting_index,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskExecution,
    TaskProvider,
    TaskRunResult,
    WebAccessAudit,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.systematic_review_reporting import (
    ComposeSystematicReviewTask,
)


def _empty_review() -> EmptyReviewContext:
    return EmptyReviewContext(
        selection_package_id="selection-package-1",
        selection_package_digest="sha256:selection",
        source_record_count=3,
        study_count=2,
        included_count=0,
        excluded_count=1,
        awaiting_classification_count=1,
        ongoing_count=0,
        unresolved_conflict_count=0,
    )


def _draft(*, source_ids: tuple[str, ...] = ()) -> SystematicReviewDraft:
    return SystematicReviewDraft(
        schema_version="systematic-review-draft.v3",
        document_maturity=ReviewDocumentMaturity.SCIENTIFIC_DRAFT,
        title="Intervention for adults: a systematic review",
        review_path=ReviewPath.EMPTY_REVIEW,
        sections=tuple(
            SystematicReviewSectionDraft(
                name=name,
                content=f"Scientific draft content for {name.value}.",
                source_artifact_ids=source_ids,
            )
            for name in ReviewSectionName
        ),
        displays=(
            ReviewDisplay(
                display_id="selection-flow",
                kind=ReviewDisplayKind.SELECTION_FLOW,
                title="Study selection",
                location=ReviewDisplayLocation.RESULTS,
                source_file="review-context/reporting-index.json",
            ),
        ),
        issues=(
            ArtifactIssue(
                code="report_not_retrieved",
                message="One report could not be retrieved and remains visible.",
            ),
        ),
    )


def _empty_files() -> dict[str, bytes]:
    artifact_index = {
        "schema_version": "systematic-review-artifact-index.v1",
        "artifacts": [
            {
                "artifact_id": "selection-1",
                "schema_version": "selection-artifact.v1",
                "task": "study_selection",
                "content_digest": "sha256:selection",
            }
        ],
    }
    return {
        "review-context/protocol.json": b"{}\n",
        "review-context/search.json": b"{}\n",
        "review-context/selection.json": b"{}\n",
        "review-context/artifact-index.json": (
            json.dumps(artifact_index, sort_keys=True) + "\n"
        ).encode(),
        "review-context/reporting-index.json": b'{"schema_version":"systematic-review-reporting-index.v2"}\n',
        "review-context/empty-review.json": (
            json.dumps(_empty_review().__dict__ if hasattr(_empty_review(), "__dict__") else {
                "schema_version": _empty_review().schema_version,
                "included_count": 0,
            })
            + "\n"
        ).encode(),
    }


def test_reporting_input_preserves_protocol_and_verified_package(protocol, tmp_path) -> None:
    evidence = FileSystematicReviewEvidencePackageStore(tmp_path).persist(
        package_id="review-1:evidence",
        review_id="review-1",
        protocol_version=protocol.version,
        review_path=ReviewPath.EMPTY_REVIEW,
        files=_empty_files(),
    )

    inputs = SystematicReviewReportingInput(protocol, evidence.package)

    assert inputs.protocol is protocol
    assert inputs.evidence_package.review_path is ReviewPath.EMPTY_REVIEW


def test_reporting_index_summarizes_large_search_without_copying_records() -> None:
    files = {
        "review-context/search.json": json.dumps(
            {
                "manifest": {"summary": {"record_count": 1000, "source_count": 1}},
                "search_runs": [
                    {
                        "search_run_id": "pubmed-1",
                        "source_name": "MEDLINE via PubMed",
                        "status": "succeeded",
                        "result_count": 1000,
                        "retrieved_count": 1000,
                    }
                ],
                "records": [{"record_id": f"record-{number}"} for number in range(1000)],
            }
        ).encode(),
        "review-context/selection.json": json.dumps(
            {"record_screening": [], "study_decisions": [], "studies": []}
        ).encode(),
    }

    index = build_reporting_index(files, review_path="empty_review")
    serialized = json.dumps(index)

    assert index["stages"]["search"]["record_count"] == 1000
    assert "record-999" not in serialized
    assert next(
        item for item in index["source_files"] if item["path"].endswith("search.json")
    )["reading_role"] == "raw_audit_open_if_needed"


def test_reporting_index_groups_report_citations_by_study_status() -> None:
    files = {
        "review-context/search.json": b'{"search_runs":[],"records":[]}',
        "review-context/selection.json": json.dumps(
            {
                "record_screening": [],
                "reports": [
                    {
                        "report_id": "report-1",
                        "title": "Trial report",
                        "citation": "Author. Trial report. 2024.",
                        "external_identifiers": ["doi:10.1/example"],
                        "locators": ["https://example.org/report"],
                    }
                ],
                "studies": [{"study_id": "study-1", "display_name": "Study 1"}],
                "study_decisions": [
                    {"study_id": "study-1", "classification": "included"}
                ],
                "study_report_links": [
                    {
                        "study_id": "study-1",
                        "report_id": "report-1",
                        "is_primary": True,
                        "rationale": "Primary report",
                    }
                ],
            }
        ).encode(),
    }

    index = build_reporting_index(files, review_path="empty_review")
    reference = index["stages"]["selection"]["study_references"][0]

    assert index["schema_version"] == "systematic-review-reporting-index.v2"
    assert reference["classification"] == "included"
    assert reference["reports"][0]["citation"] == "Author. Trial report. 2024."


def test_completed_agent_output_can_retain_local_evidence_limitations() -> None:
    output = systematic_review_agent_output_adapter().validate_python(
        {
            "status": "completed",
            "artifact": _draft(),
            "issues": [
                {
                    "code": "full_text_unavailable",
                    "message": "A report was unavailable; this limits interpretation.",
                    "severity": "warning",
                    "provenance": [],
                }
            ],
            "blocker": None,
            "warnings": ["Evidence availability was limited."],
        }
    )

    assert output.status.value == "completed"
    assert output.issues[0].code == "full_text_unavailable"


def test_partial_requires_unfinished_work_instead_of_a_partial_artifact() -> None:
    with pytest.raises(ValidationError, match="must not contain artifact"):
        systematic_review_agent_output_adapter().validate_python(
            {
                "status": "partial",
                "artifact": _draft(),
                "issues": [],
                "blocker": None,
                "warnings": [],
            }
        )


def test_empty_review_persists_complete_scientific_draft_and_data_package(
    tmp_path,
) -> None:
    evidence_store = FileSystematicReviewEvidencePackageStore(tmp_path / "evidence")
    evidence = evidence_store.persist(
        package_id="review-1:evidence",
        review_id="review-1",
        protocol_version="protocol-1",
        review_path=ReviewPath.EMPTY_REVIEW,
        files=_empty_files(),
    )
    artifact_store = FileSystematicReviewArtifactStore(tmp_path / "artifacts")

    artifact = artifact_store.persist(
        binding={
            "review_id": "review-1",
            "protocol_version": "protocol-1",
            "protocol_digest": "sha256:protocol",
            "evidence_package_id": evidence.package.package_id,
            "evidence_package_digest": evidence.package.content_digest,
        },
        draft=_draft(source_ids=("selection-1",)),
        evidence=evidence,
        warnings=("One report remained unavailable.",),
    )
    snapshot = artifact_store.resolve(artifact.artifact_id)
    review = json.loads(
        (snapshot.public_directory / "systematic-review.json").read_text()
    )
    data_manifest = json.loads(
        (snapshot.public_directory / "review-data/manifest.json").read_text()
    )

    assert artifact.schema_version == "systematic-review-artifact.v5"
    assert artifact.counts["review_sections"] == len(ReviewSectionName)
    assert review["document_maturity"] == "scientific_draft"
    assert {section["name"] for section in review["sections"]} == {
        name.value for name in ReviewSectionName
    }
    assert data_manifest["schema_version"] == "review-data-package.v4"
    assert "review-context/empty-review.json" in data_manifest["files"]


def test_artifact_store_rejects_only_unknown_upstream_identity(tmp_path) -> None:
    evidence = FileSystematicReviewEvidencePackageStore(tmp_path / "evidence").persist(
        package_id="review-1:evidence",
        review_id="review-1",
        protocol_version="protocol-1",
        review_path=ReviewPath.EMPTY_REVIEW,
        files=_empty_files(),
    )

    with pytest.raises(ValueError, match="unknown upstream artifact"):
        FileSystematicReviewArtifactStore(tmp_path / "artifacts").persist(
            binding={
                "review_id": "review-1",
                "protocol_version": "protocol-1",
                "protocol_digest": "sha256:protocol",
                "evidence_package_id": evidence.package.package_id,
                "evidence_package_digest": evidence.package.content_digest,
            },
            draft=_draft(source_ids=("not-in-package",)),
            evidence=evidence,
            warnings=(),
        )


def test_completed_draft_records_methodology_llm_fallback_without_authority() -> None:
    decision = ReportingMethodDecision(
        decision_id="reporting-1",
        topic="reporting completeness",
        decision="Apply the known reporting structure provisionally.",
        rationale="The official guidance was temporarily inaccessible.",
        basis_status=MethodologyBasisStatus.LLM_FALLBACK,
        authoritative_sources=(),
        fallback_model="provider/model-id",
        fallback_note=(
            "Temporary methodology fallback; official guidance was not verified."
        ),
    )

    draft = SystematicReviewDraft(
        schema_version="systematic-review-draft.v3",
        document_maturity=ReviewDocumentMaturity.SCIENTIFIC_DRAFT,
        title="Intervention for adults: a systematic review",
        review_path=ReviewPath.EMPTY_REVIEW,
        sections=_draft().sections,
        method_decisions=(decision,),
        issues=(
            ArtifactIssue(
                code="methodology_llm_fallback",
                message="Official reporting guidance could not be verified.",
            ),
        ),
    )

    assert draft.method_decisions[0].basis_status.value == "llm_fallback"
    assert draft.method_decisions[0].authoritative_sources == ()


def test_completed_draft_rejects_unresolved_methodology() -> None:
    with pytest.raises(ValueError, match="unresolved methodology"):
        SystematicReviewDraft(
            schema_version="systematic-review-draft.v3",
            document_maturity=ReviewDocumentMaturity.SCIENTIFIC_DRAFT,
            title="Intervention for adults: a systematic review",
            review_path=ReviewPath.EMPTY_REVIEW,
            sections=_draft().sections,
            method_decisions=(
                ReportingMethodDecision(
                    decision_id="reporting-1",
                    topic="reporting completeness",
                    decision="No reliable method basis was established.",
                    rationale="Authority and fallback were unavailable.",
                    basis_status=MethodologyBasisStatus.UNRESOLVED,
                ),
            ),
        )


def test_agent_task_uses_closed_package_and_completes_despite_local_issue(
    protocol,
    tmp_path,
) -> None:
    protocol = replace(
        protocol,
        methodology_profile=MethodologyProfile(
            decisions=(),
            authorities=(),
            basis_status=MethodologyBasisStatus.LLM_FALLBACK,
            fallback_model="provider/model-id",
            fallback_note="Official methodology was temporarily inaccessible.",
        ),
    )
    evidence_store = FileSystematicReviewEvidencePackageStore(tmp_path / "evidence")
    evidence = evidence_store.persist(
        package_id="review-1:evidence",
        review_id="review-1",
        protocol_version=protocol.version,
        review_path=ReviewPath.EMPTY_REVIEW,
        files=_empty_files(),
    )
    executor = _CompletedExecutor()
    task = ComposeSystematicReviewTask(
        executor=executor,
        evidence_store=evidence_store,
        artifact_store=FileSystematicReviewArtifactStore(tmp_path / "artifacts"),
        run_id_factory=lambda: "systematic-review-test",
    )

    result = task.compose(
        SystematicReviewReportingInput(protocol, evidence.package),
        TaskContext("review-1", protocol.version),
    )

    assert result.status is TaskWorkStatus.COMPLETED
    assert result.issues[0].code == "full_text_unavailable"
    assert executor.request.enable_web_search is True
    assert executor.request.enable_workspace_network is True
    assert executor.request.output_artifacts == {}
    assert set(executor.request.input_artifacts) == {
        "systematic-review-evidence-package"
    }
    profile = executor.request.input_data["protocol"]["methodology_profile"]
    assert profile["basis_status"] == "llm_fallback"
    assert profile["authorities"] == []
    assert profile["fallback_model"] == "provider/model-id"


class _CompletedExecutor:
    def execute(self, request, *, output_adapter, error_context):
        self.request = request
        output = {
            "status": "completed",
            "artifact": TypeAdapter(SystematicReviewDraft).dump_python(
                _draft(), mode="json"
            ),
            "issues": [
                {
                    "code": "full_text_unavailable",
                    "message": "One report remained unavailable.",
                    "severity": "warning",
                    "provenance": [],
                }
            ],
            "blocker": None,
            "warnings": ["Evidence availability was limited."],
        }
        run = TaskRunResult(
            provider=TaskProvider.OPENAI,
            model="fake",
            run_id=request.run_id,
            session_id=None,
            output=output,
            events=(),
            stderr="",
            duration_seconds=0.01,
            web_access_audit=WebAccessAudit(False, False, 0, ()),
            skill_snapshots=(),
        )
        return TaskExecution(run, output_adapter.validate_python(output))
