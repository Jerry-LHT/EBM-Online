from __future__ import annotations

from dataclasses import replace

import pytest

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    ArtifactStatus,
    DomainValidationError,
    IssueSeverity,
    TaskContext,
    TaskName,
    build_artifact,
)
from ebm_backend.online_pipeline_v2.domain.protocol import (
    MethodologyBasisStatus,
    MethodologyDecision,
    MethodologyDecisionOrigin,
    MethodologyProfile,
    MethodologyReference,
    OutcomeMeasure,
    OutcomePlan,
    OutcomeRole,
    ProtocolExtension,
    ProtocolExtensionValue,
    ProtocolExtensionValueKind,
    SearchPlan,
    SearchSource,
    SearchSourceStrategy,
    SearchSourceType,
)
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchArtifact,
    EvidenceSearchInput,
    EvidenceSearchMode,
    ExternalIdentifier,
    Record,
    RecordRelation,
    SearchPackageRef,
    SearchRun,
    SearchRunStatus,
    SearchSummary,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    SelectionPackageRef,
    SelectionSummary,
    StudySelectionArtifact,
    study_selection_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.domain.study_data import (
    ResultsReviewMode,
    StudyResultsInput,
    study_results_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.domain.synthesis import (
    evidence_synthesis_protocol_from_draft,
)


def test_study_selection_artifact_is_compact_and_never_claims_human_review() -> None:
    artifact = StudySelectionArtifact(
        package_ref=SelectionPackageRef(
            package_id="selection-package-1",
            review_id="review-1",
            protocol_version="protocol-1",
            schema_version="selection-package.v4",
            content_digest="sha256:selection",
        ),
        summary=SelectionSummary(
            source_record_count=10,
            duplicate_record_count=2,
            records_screened_count=8,
            title_abstract_excluded_count=4,
            reports_sought_count=4,
            reports_not_retrieved_count=1,
            reports_assessed_count=3,
            study_count=2,
            included_count=1,
            excluded_count=1,
            awaiting_classification_count=0,
            ongoing_count=0,
            unresolved_conflict_count=0,
        ),
    )

    assert artifact.summary.study_count == 2
    assert set(artifact.__dataclass_fields__) == {
        "package_ref",
        "summary",
        "search_continuation",
    }


def test_supplementary_search_requires_parent_and_reason(protocol) -> None:
    parent = SearchPackageRef(
        package_id="search-package-1",
        review_id="review-1",
        protocol_version=protocol.version,
        schema_version="search-package.v2",
        content_digest="sha256:search",
    )
    supplementary = EvidenceSearchInput(
        protocol=protocol,
        mode=EvidenceSearchMode.SUPPLEMENTARY,
        parent_package_ref=parent,
        supplementary_reason="Resolve an unidentified trial report.",
        evidence_gaps=("trial registry identifier",),
        candidate_leads=("NCT123",),
    )
    assert supplementary.mode is EvidenceSearchMode.SUPPLEMENTARY

    with pytest.raises(DomainValidationError, match="parent package"):
        EvidenceSearchInput(
            protocol=protocol,
            mode=EvidenceSearchMode.SUPPLEMENTARY,
            supplementary_reason="Missing report.",
        )
def test_complete_protocol_projects_to_study_selection_boundary(protocol) -> None:
    projected = study_selection_protocol_from_draft(protocol)

    assert projected.version == protocol.version
    assert projected.review_question == protocol.review_question
    assert projected.study_designs[0].heading == "Types of studies"
    assert not hasattr(projected, "outcomes")
    assert not hasattr(projected, "selection_methods")
    assert (
        projected.setting_restrictions
        == protocol.methods.eligibility.setting_restrictions
    )
    assert (
        projected.language_restrictions
        == protocol.methods.eligibility.language_restrictions
    )
    assert (
        projected.publication_status_restrictions
        == protocol.methods.eligibility.publication_status_restrictions
    )
    assert (
        projected.time_restrictions
        == protocol.methods.eligibility.time_restrictions
    )


def test_study_selection_optional_restrictions_are_preserved_when_present(
    protocol,
) -> None:
    projected = study_selection_protocol_from_draft(protocol)
    restricted = replace(
        projected,
        setting_restrictions=("Outpatient settings only",),
        language_restrictions=("English-language Reports only",),
        publication_status_restrictions=("Published and unpublished",),
        time_restrictions=("From 2020 onward",),
    )

    assert restricted.setting_restrictions == ("Outpatient settings only",)
    assert restricted.language_restrictions == (
        "English-language Reports only",
    )
    assert restricted.publication_status_restrictions == (
        "Published and unpublished",
    )
    assert restricted.time_restrictions == ("From 2020 onward",)


def test_complete_protocol_projects_to_results_and_synthesis_boundaries(
    protocol,
) -> None:
    results = study_results_protocol_from_draft(protocol)
    synthesis = evidence_synthesis_protocol_from_draft(protocol)

    assert results.version == synthesis.version == protocol.version
    assert results.review_pico == synthesis.review_pico == protocol.review_pico
    assert {item.heading for item in results.data_collection} == {
        "Data extraction and management",
        "Dealing with missing data",
    }
    assert any(item.heading == "Meta-analysis methods" for item in synthesis.synthesis)
    assert not hasattr(results, "search")
    assert not hasattr(synthesis, "certainty")


def test_study_selection_rejects_obsolete_package_schema() -> None:
    with pytest.raises(DomainValidationError, match="selection-package.v4"):
        StudySelectionArtifact(
            package_ref=SelectionPackageRef(
                package_id="selection-package-1",
                review_id="review-1",
                protocol_version="protocol-1",
                schema_version="selection-package.v1",
                content_digest="sha256:selection",
            ),
            summary=SelectionSummary(
                source_record_count=0,
                duplicate_record_count=0,
                records_screened_count=0,
                title_abstract_excluded_count=0,
                reports_sought_count=0,
                reports_not_retrieved_count=0,
                reports_assessed_count=0,
                study_count=0,
                included_count=0,
                excluded_count=0,
                awaiting_classification_count=0,
                ongoing_count=0,
                unresolved_conflict_count=0,
            ),
        )


def test_study_results_consumes_only_protocol_and_selection_ref(
    results_protocol,
) -> None:
    value = StudyResultsInput(
        protocol=results_protocol,
        selection_package=SelectionPackageRef(
            package_id="selection-package-1",
            review_id="review-1",
            protocol_version="protocol-1",
            schema_version="selection-package.v4",
            content_digest="sha256:selection",
        ),
        review_mode=ResultsReviewMode.SINGLE_AGENT,
    )

    assert value.review_mode is ResultsReviewMode.SINGLE_AGENT
    assert not hasattr(value, "characteristics")


def test_blocked_artifact_requires_error_issue(source) -> None:
    with pytest.raises(DomainValidationError, match="error issue"):
        build_artifact(
            context=TaskContext("review-1", "protocol-1"),
            task=TaskName.EVIDENCE_SEARCH,
            data=None,
            provenance=(source,),
            status=ArtifactStatus.BLOCKED,
        )

    artifact = build_artifact(
        context=TaskContext("review-1", "protocol-1"),
        task=TaskName.EVIDENCE_SEARCH,
        data=None,
        provenance=(source,),
        status=ArtifactStatus.BLOCKED,
        issues=(
            ArtifactIssue(
                code="search_unavailable",
                message="All required sources failed",
                severity=IssueSeverity.ERROR,
            ),
        ),
    )

    assert artifact.status is ArtifactStatus.BLOCKED


def test_search_artifact_preserves_record_identifiers_without_full_text(source) -> None:
    run = SearchRun(
        search_run_id="run-1",
        source_name="MEDLINE",
        platform="Ovid",
        query="intervention AND mortality",
        executed_at="2026-07-26T00:00:00Z",
        status=SearchRunStatus.SUCCEEDED,
        result_count=1,
        provenance=(source,),
        retrieved_count=1,
        status_reason=None,
        search_narrative="Test search.",
    )
    record = Record(
        record_id="record-1",
        source_name="MEDLINE",
        platform="Ovid",
        source_record_id="ovid-123",
        title="An intervention trial",
        citation="Example Journal. 2026;1:1-10.",
        abstract="A bibliographic abstract.",
        external_identifiers=(
            ExternalIdentifier(scheme="doi", value="10.1000/example"),
            ExternalIdentifier(scheme="nct", value="NCT00000001"),
        ),
        publication_types=("Randomized Controlled Trial",),
        related_records=(
            RecordRelation(
                relation_type="ErratumIn",
                related_source_record_id="ovid-456",
                citation="Example Journal. 2026;1:11.",
            ),
        ),
        locators=("https://doi.org/10.1000/example",),
        search_run_ids=("run-1",),
        provenance=(source,),
    )

    artifact = EvidenceSearchArtifact(
        search_runs=(run,),
        records=(record,),
        summary=SearchSummary(run_count=1, source_count=1, record_count=1),
    )

    assert artifact.records[0].external_identifiers[0].scheme == "doi"
    assert artifact.records[0].abstract == "A bibliographic abstract."
    assert artifact.records[0].publication_types == ("Randomized Controlled Trial",)
    assert artifact.records[0].related_records[0].relation_type == "ErratumIn"


def test_search_artifact_rejects_unknown_record_search_run(source) -> None:
    run = SearchRun(
        search_run_id="run-1",
        source_name="MEDLINE",
        platform="Ovid",
        query="query",
        executed_at="2026-07-26T00:00:00Z",
        status=SearchRunStatus.SUCCEEDED,
        result_count=1,
        provenance=(source,),
        retrieved_count=0,
        status_reason=None,
        search_narrative="Test search.",
    )
    record = Record(
        record_id="record-1",
        source_name="MEDLINE",
        platform="Ovid",
        source_record_id="ovid-123",
        search_run_ids=("missing-run",),
        provenance=(source,),
    )

    with pytest.raises(DomainValidationError, match="unknown search run"):
        EvidenceSearchArtifact(
            search_runs=(run,),
            records=(record,),
            summary=SearchSummary(run_count=1, source_count=1, record_count=1),
        )


def test_search_artifact_rejects_record_source_that_differs_from_run(source) -> None:
    run = SearchRun(
        search_run_id="run-1",
        source_name="MEDLINE",
        platform="PubMed",
        query="query",
        executed_at="2026-07-26T00:00:00Z",
        status=SearchRunStatus.SUCCEEDED,
        result_count=1,
        provenance=(source,),
        retrieved_count=0,
        status_reason=None,
        search_narrative="Test search.",
    )
    record = Record(
        record_id="record-1",
        source_name="Embase",
        platform="Embase.com",
        source_record_id="123",
        search_run_ids=("run-1",),
        provenance=(source,),
    )

    with pytest.raises(DomainValidationError, match="source and platform"):
        EvidenceSearchArtifact(
            search_runs=(run,),
            records=(record,),
            summary=SearchSummary(run_count=1, source_count=1, record_count=1),
        )


def test_q2protocol_fixed_format_requires_a_primary_outcome() -> None:
    with pytest.raises(DomainValidationError, match="primary outcome"):
        OutcomePlan(
            outcomes=(
                OutcomeMeasure(
                    name="quality of life",
                    definition="Participant-reported quality of life",
                    measurement="Validated scale",
                    time_points=("12 months",),
                    role=OutcomeRole.SECONDARY,
                ),
            )
        )


def test_q2protocol_domain_does_not_match_search_source_labels() -> None:
    database = SearchSource(
        source_name="MEDLINE",
        source_type=SearchSourceType.DATABASE,
        platform="Ovid",
        date_coverage="inception to search date",
    )

    plan = SearchPlan(
        structured_sources=(database,),
        strategies=(
            SearchSourceStrategy(
                source_name="MEDLINE via Ovid",
                strategy="1 condition.ti,ab.",
            ),
        ),
    )

    assert len(plan.structured_sources) == 1
    assert len(plan.strategies) == 1


def test_q2protocol_fixed_format_allows_search_strategy_to_be_developed_later() -> None:
    database = SearchSource(
        source_name="MEDLINE",
        source_type=SearchSourceType.DATABASE,
        platform="Ovid",
        date_coverage="inception to search date",
    )

    plan = SearchPlan(structured_sources=(database,), strategies=())
    assert plan.strategies == ()


def test_q2protocol_output_cannot_claim_a_non_draft_status(protocol) -> None:
    with pytest.raises(DomainValidationError, match="must be draft"):
        replace(protocol, document_status="approved")


def test_q2protocol_methodology_completeness_is_not_a_domain_invariant(
    protocol,
) -> None:
    draft = replace(
        protocol,
        methodology_profile=replace(
            protocol.methodology_profile,
            authorities=protocol.methodology_basis[:-1],
        ),
    )
    assert len(draft.methodology_basis) == len(protocol.methodology_basis) - 1


def test_methodology_reference_checks_date_format_but_not_source_authority() -> None:
    values = {
        "standard": "cochrane_handbook",
        "title": "Cochrane Handbook",
        "version_or_revision": "Version 6.5 (2024)",
        "sections": ("Chapter 2",),
        "url": "https://example.test/handbook",
        "accessed_on": "2026-07-25",
    }

    reference = MethodologyReference(**values)
    assert reference.url == "https://example.test/handbook"

    values["accessed_on"] = "25-07-2026"
    with pytest.raises(DomainValidationError, match="YYYY-MM-DD"):
        MethodologyReference(**values)


def test_protocol_extension_uses_one_typed_value_and_known_authority(
    protocol,
) -> None:
    extension = ProtocolExtension(
        extension_id="standard-specific-analysis-rule",
        namespace="example.standard",
        scope="methods.analysis",
        name="analysis rule",
        value=ProtocolExtensionValue(
            kind=ProtocolExtensionValueKind.TEXT,
            text="Apply the rule prospectively.",
            number=None,
            boolean=None,
            text_list=(),
        ),
        authority_standards=(protocol.methodology_basis[0].standard,),
    )

    extended = replace(protocol, extensions=(extension,))

    assert extended.extensions[0].value.text == "Apply the rule prospectively."


def test_protocol_extension_rejects_ambiguous_or_unknown_semantics(
    protocol,
) -> None:
    with pytest.raises(DomainValidationError, match="exactly"):
        ProtocolExtensionValue(
            kind=ProtocolExtensionValueKind.TEXT,
            text="text",
            number=1,
            boolean=None,
            text_list=(),
        )

    extension = ProtocolExtension(
        extension_id="unknown-rule",
        namespace="example.standard",
        scope="methods",
        name="unknown authority rule",
        value=ProtocolExtensionValue(
            kind=ProtocolExtensionValueKind.BOOLEAN,
            text=None,
            number=None,
            boolean=True,
            text_list=(),
        ),
        authority_standards=("not-consulted",),
    )
    with pytest.raises(DomainValidationError, match="unknown authority"):
        replace(protocol, extensions=(extension,))


def test_protocol_llm_fallback_preserves_unverified_standard_references(
    protocol,
) -> None:
    decision = MethodologyDecision(
        decision_id="fallback-method",
        topic="Review methodology",
        decision="Apply the supplied standard using model methodology knowledge.",
        origin=MethodologyDecisionOrigin.SUPPLIED,
        rationale="The official source could not be read in this run.",
        authority_standards=("cochrane_handbook",),
    )
    extension = ProtocolExtension(
        extension_id="fallback-rule",
        namespace="cochrane_handbook",
        scope="methods",
        name="fallback rule",
        value=ProtocolExtensionValue(
            kind=ProtocolExtensionValueKind.BOOLEAN,
            text=None,
            number=None,
            boolean=True,
            text_list=(),
        ),
        authority_standards=("cochrane_handbook",),
    )

    fallback = replace(
        protocol,
        methodology_profile=MethodologyProfile(
            decisions=(decision,),
            authorities=(),
            basis_status=MethodologyBasisStatus.LLM_FALLBACK,
            fallback_model="openai/gpt-5.6-terra",
            fallback_note="Official guidance was unavailable.",
        ),
        extensions=(extension,),
    )

    assert fallback.methodology_profile.authorities == ()
    assert fallback.methodology_profile.decisions[0].authority_standards == (
        "cochrane_handbook",
    )
