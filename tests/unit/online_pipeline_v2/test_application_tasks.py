from __future__ import annotations

from types import SimpleNamespace

from ebm_backend.online_pipeline_v2.application.use_cases.evidence_search.execute import (
    ExecuteEvidenceSearch,
)
from ebm_backend.online_pipeline_v2.application.use_cases.evidence_search.search_evidence import (
    SearchEvidence,
)
from ebm_backend.online_pipeline_v2.application.use_cases.evidence_synthesis.execute import (
    ExecuteEvidenceSynthesis,
)
from ebm_backend.online_pipeline_v2.application.use_cases.q2protocol.draft_protocol import (
    DraftProtocol,
)
from ebm_backend.online_pipeline_v2.application.use_cases.q2protocol.execute import (
    ExecuteQ2Protocol,
)
from ebm_backend.online_pipeline_v2.application.use_cases.risk_of_bias.assess import (
    AssessRiskOfBias,
)
from ebm_backend.online_pipeline_v2.application.use_cases.risk_of_bias.execute import (
    ExecuteRiskOfBias,
)
from ebm_backend.online_pipeline_v2.application.use_cases.study_data_collection.collect import (
    ExecuteStudyDataCollection,
)
from ebm_backend.online_pipeline_v2.application.use_cases.study_characteristics.collect import (
    CollectStudyCharacteristics,
)
from ebm_backend.online_pipeline_v2.application.use_cases.study_characteristics.execute import (
    ExecuteStudyCharacteristics,
)
from ebm_backend.online_pipeline_v2.application.use_cases.study_selection.execute import (
    ExecuteStudySelection,
)
from ebm_backend.online_pipeline_v2.application.use_cases.study_selection.select_studies import (
    SelectStudies,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactFile,
    ArtifactIssue,
    ArtifactStatus,
    CompletedArtifactRef,
    TaskCompletion,
    TaskContext,
    TaskInvocation,
    TaskName,
    TaskWorkResult,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.protocol import Q2ProtocolInput, TopicKind
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasArtifact,
    RiskOfBiasInput,
    RiskOfBiasPackageRef,
    RiskOfBiasReviewProcess,
    RiskOfBiasSummary,
)
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchArtifact,
    EvidenceSearchInput,
    SearchRun,
    SearchRunStatus,
    SearchPackageRef,
    SearchSummary,
    public_search_artifact,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    SelectionPackageRef,
    SelectionSummary,
    StudySelectionArtifact,
    StudySelectionInput,
)
from ebm_backend.online_pipeline_v2.domain.study_data_collection import (
    StudyDataCollectionInput,
    study_data_collection_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.domain.study_characteristics import (
    StudyCharacteristicsArtifact,
    StudyCharacteristicsInput,
    StudyCharacteristicsPackageRef,
    StudyCharacteristicsSummary,
)
from ebm_backend.online_pipeline_v2.domain.synthesis import (
    EvidenceSynthesisInput,
)


def _invocation(inputs, source) -> TaskInvocation:
    return TaskInvocation(
        context=TaskContext("review-1", "protocol-1"),
        inputs=inputs,
        provenance=(source,),
    )


def _selection_artifact() -> StudySelectionArtifact:
    return StudySelectionArtifact(
        package_ref=SelectionPackageRef(
            package_id="selection-package-1",
            review_id="review-1",
            protocol_version="protocol-1",
            schema_version="selection-package.v4",
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


def test_q2protocol_calls_its_single_draft_port(protocol, source) -> None:
    calls: list[str] = []
    use_case = ExecuteQ2Protocol(
        draft_protocol=DraftProtocol(
            SimpleNamespace(
                draft=lambda inputs, version: calls.append("draft")
                or TaskCompletion(ArtifactStatus.COMPLETED, protocol)
            )
        ),
    )

    result = use_case.execute(
        _invocation(
            Q2ProtocolInput(
                topic_text=protocol.review_question,
                topic_kind=TopicKind.QUESTION,
            ),
            source,
        )
    )

    assert calls == ["draft"]
    assert result.task is TaskName.Q2PROTOCOL


def test_evidence_search_calls_its_single_task_port(protocol, source) -> None:
    calls: list[str] = []
    run = SearchRun(
        search_run_id="run-1",
        source_name="source",
        platform="database",
        query="query",
        executed_at="2026-07-24T00:00:00Z",
        status=SearchRunStatus.SUCCEEDED,
        result_count=0,
        provenance=(source,),
        retrieved_count=0,
        status_reason=None,
        search_narrative="Test search.",
    )
    search = EvidenceSearchArtifact(
        search_runs=(run,),
        records=(),
        summary=SearchSummary(run_count=1, source_count=1, record_count=0),
    )
    use_case = ExecuteEvidenceSearch(
        search_evidence=SearchEvidence(
            SimpleNamespace(
                search=lambda protocol, version: calls.append("search")
                or TaskCompletion(ArtifactStatus.COMPLETED, search)
            ),
        ),
    )

    result = use_case.execute(
        _invocation(EvidenceSearchInput(protocol=protocol), source)
    )

    assert calls == ["search"]
    assert result.data is search


def test_study_selection_calls_its_single_task_port(
    selection_protocol,
    source,
) -> None:
    calls: list[str] = []
    search = public_search_artifact(
        EvidenceSearchArtifact(
            search_runs=(
                SearchRun(
                    search_run_id="run-1",
                    source_name="source",
                    platform="database",
                    query="query",
                    executed_at="2026-07-24T00:00:00Z",
                    status=SearchRunStatus.SUCCEEDED,
                    result_count=0,
                    provenance=(source,),
                    retrieved_count=0,
                    status_reason=None,
                    search_narrative="Test search.",
                ),
            ),
            records=(),
            summary=SearchSummary(run_count=1, source_count=1, record_count=0),
            package_ref=SearchPackageRef(
                package_id="search-package-1",
                review_id="review-1",
                protocol_version="protocol-1",
                schema_version="search-package.v2",
                content_digest="sha256:search",
            ),
        )
    )
    selected = _selection_artifact()
    use_case = ExecuteStudySelection(
        select_studies=SelectStudies(
            SimpleNamespace(
                select=lambda *args: calls.append("select")
                or TaskCompletion(ArtifactStatus.COMPLETED, selected)
            )
        ),
    )

    result = use_case.execute(
        _invocation(StudySelectionInput(selection_protocol, search), source)
    )

    assert calls == ["select"]
    assert result.data is selected


def test_study_data_collection_has_one_port_and_synthesis_is_separate(
    protocol,
    synthesis_protocol,
    source,
) -> None:
    selection = _selection_artifact()
    study_data = CompletedArtifactRef(
        artifact_id="study-data-1",
        schema_version="study-data-collection-artifact.v3",
        review_id="review-1",
        protocol_version="protocol-1",
        task=TaskName.STUDY_DATA_COLLECTION,
        content_digest="sha256:study-data",
        files=(ArtifactFile("study-data.json", "sha256:file", 1),),
        counts={"study_count": 1},
    )
    rob = RiskOfBiasArtifact(
        package_ref=RiskOfBiasPackageRef(
            "risk-of-bias-package",
            "review-1",
            "protocol-1",
            "risk-of-bias-package.v4",
            "sha256:risk-of-bias",
        ),
        document=SimpleNamespace(),
        summary=RiskOfBiasSummary(0, 0, 0, 0, 0, 0),
        review_process=RiskOfBiasReviewProcess("risk-of-bias-run"),
    )
    calls: list[str] = []

    collection_work = TaskWorkResult(
        status=TaskWorkStatus.INCOMPLETE,
        work_id="study-data-work-1",
    )
    data_use_case = ExecuteStudyDataCollection(
        collect_study_data=SimpleNamespace(
            collect=lambda *args: calls.append("study_data_collection")
            or collection_work
        ),
    )
    collection_result = data_use_case.execute(
        _invocation(
            StudyDataCollectionInput(
                protocol=study_data_collection_protocol_from_draft(protocol),
                selection=selection,
            ),
            source,
        )
    )
    assert collection_result is collection_work

    synthesis_work = TaskWorkResult(
        status=TaskWorkStatus.INCOMPLETE,
        work_id="synthesis-work-1",
    )
    synthesis_use_case = ExecuteEvidenceSynthesis(
        synthesize_evidence=SimpleNamespace(
            synthesize=lambda *args: calls.append("synthesis") or synthesis_work
        ),
    )
    synthesis_result = synthesis_use_case.execute(
        _invocation(
            EvidenceSynthesisInput(
                protocol=synthesis_protocol,
                study_data_collection=study_data,
                risk_of_bias=rob,
            ),
            source,
        )
    )
    assert synthesis_result is synthesis_work

    assert calls == ["study_data_collection", "synthesis"]


def test_task_completion_propagates_partial_status(protocol, source) -> None:
    search = EvidenceSearchArtifact(
        search_runs=(
            SearchRun(
                search_run_id="run-1",
                source_name="source",
                platform="database",
                query="query",
                executed_at="2026-07-24T00:00:00Z",
                status=SearchRunStatus.PARTIAL,
                result_count=0,
                provenance=(source,),
                retrieved_count=0,
                status_reason="Source returned no usable records.",
                search_narrative="Test partial search.",
            ),
        ),
        records=(),
        summary=SearchSummary(run_count=1, source_count=1, record_count=0),
    )
    use_case = ExecuteEvidenceSearch(
        search_evidence=SearchEvidence(
            SimpleNamespace(
                search=lambda protocol, version: TaskCompletion(
                    status=ArtifactStatus.PARTIAL,
                    data=search,
                    issues=(
                        ArtifactIssue(
                            code="source_failed",
                            message="One planned source was unavailable",
                        ),
                    ),
                )
            ),
        ),
    )

    result = use_case.execute(
        _invocation(EvidenceSearchInput(protocol=protocol), source)
    )

    assert result.status is ArtifactStatus.PARTIAL
    assert result.issues[0].code == "source_failed"


def test_risk_of_bias_calls_its_single_task_port(protocol, source) -> None:
    selection = _selection_artifact()
    study_data = CompletedArtifactRef(
        artifact_id="study-data-1",
        schema_version="study-data-collection-artifact.v3",
        review_id="review-1",
        protocol_version="protocol-1",
        task=TaskName.STUDY_DATA_COLLECTION,
        content_digest="sha256:study-data",
        files=(ArtifactFile("study-data.json", "sha256:file", 1),),
        counts={"study_count": 1},
    )
    artifact = RiskOfBiasArtifact(
        package_ref=RiskOfBiasPackageRef(
            "risk-of-bias-package",
            "review-1",
            "protocol-1",
            "risk-of-bias-package.v4",
            "sha256:risk-of-bias",
        ),
        document=SimpleNamespace(),
        summary=RiskOfBiasSummary(0, 0, 0, 0, 0, 0),
        review_process=RiskOfBiasReviewProcess("risk-of-bias-run"),
    )
    calls: list[str] = []
    use_case = ExecuteRiskOfBias(
        assess_risk_of_bias=AssessRiskOfBias(
            SimpleNamespace(
                assess=lambda *args: calls.append("risk_of_bias")
                or TaskCompletion(ArtifactStatus.COMPLETED, artifact)
            )
        )
    )

    result = use_case.execute(
        _invocation(
            RiskOfBiasInput(protocol, selection, study_data),
            source,
        )
    )

    assert calls == ["risk_of_bias"]
    assert result.task is TaskName.RISK_OF_BIAS
