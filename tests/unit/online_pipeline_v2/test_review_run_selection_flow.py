from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from ebm_backend.online_pipeline_v2.application.use_cases.review_run.execute import (
    ExecuteReviewRun,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactFile,
    ArtifactIssue,
    ArtifactStatus,
    CompletedArtifactRef,
    TaskContext,
    TaskName,
    TaskWorkResult,
    TaskWorkStatus,
    build_artifact,
)
from ebm_backend.online_pipeline_v2.domain.protocol import TopicKind
from ebm_backend.online_pipeline_v2.domain.review_run import (
    CreateReviewRun,
    ReviewRun,
    ReviewRunStatus,
    ReviewStage,
)
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchArtifact,
    SearchPackageRef,
    SearchRun,
    SearchRunStatus,
    SearchSummary,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    SearchContinuationDecision,
    SearchContinuationStatus,
    SelectionPackageRef,
    SelectionSummary,
    StudySelectionArtifact,
)
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    ReviewPath,
    SystematicReviewEvidencePackageRef,
)


@pytest.mark.parametrize(
    (
        "task_status",
        "continuation_status",
        "expected_stage",
        "expected_run_status",
        "expected_event",
    ),
    (
        (
            ArtifactStatus.COMPLETED,
            SearchContinuationStatus.PROCEED,
            ReviewStage.STUDY_DATA_COLLECTION,
            ReviewRunStatus.RUNNING,
            "stage_completed",
        ),
        (
            ArtifactStatus.COMPLETED,
            SearchContinuationStatus.CONTINUE_SEARCH,
            ReviewStage.EVIDENCE_SEARCH,
            ReviewRunStatus.NEEDS_ATTENTION,
            "supplementary_search_required",
        ),
        (
            ArtifactStatus.PARTIAL,
            SearchContinuationStatus.PROCEED,
            ReviewStage.STUDY_SELECTION,
            ReviewRunStatus.NEEDS_ATTENTION,
            "professional_task_partial",
        ),
    ),
)
def test_review_run_keeps_selection_completion_separate_from_search_follow_up(
    protocol,
    source,
    task_status: ArtifactStatus,
    continuation_status: SearchContinuationStatus,
    expected_stage: ReviewStage,
    expected_run_status: ReviewRunStatus,
    expected_event: str,
) -> None:
    context = TaskContext("review-1", protocol.version)
    selection = StudySelectionArtifact(
        package_ref=SelectionPackageRef(
            package_id="selection-package-1",
            review_id=context.review_id,
            protocol_version=context.protocol_version,
            schema_version="selection-package.v4",
            content_digest="sha256:selection",
        ),
        summary=SelectionSummary(
            source_record_count=2,
            duplicate_record_count=0,
            records_screened_count=2,
            title_abstract_excluded_count=0,
            reports_sought_count=2,
            reports_not_retrieved_count=1,
            reports_assessed_count=1,
            study_count=2,
            included_count=1,
            excluded_count=0,
            awaiting_classification_count=1,
            ongoing_count=0,
            unresolved_conflict_count=0,
        ),
        search_continuation=SearchContinuationDecision(
            status=continuation_status,
            rationale=(
                "A material Study-identification gap requires another Search Package."
                if continuation_status is SearchContinuationStatus.CONTINUE_SEARCH
                else "Known Reports reached honest access conclusions."
            ),
            evidence_gaps=(
                ("A planned source remains unsearched.",)
                if continuation_status is SearchContinuationStatus.CONTINUE_SEARCH
                else ()
            ),
            candidate_leads=(
                ("A newly identified trial registry.",)
                if continuation_status is SearchContinuationStatus.CONTINUE_SEARCH
                else ()
            ),
        ),
    )
    issues = (
        (
            ArtifactIssue(
                code="selection_work_unfinished",
                message="Required Report investigation was not completed.",
            ),
        )
        if task_status is ArtifactStatus.PARTIAL
        else ()
    )
    selection_result = build_artifact(
        context=context,
        task=TaskName.STUDY_SELECTION,
        data=selection,
        provenance=(source,),
        status=task_status,
        issues=issues,
    )
    run = ReviewRun(
        run_id="run-1",
        request=CreateReviewRun(
            review_id=context.review_id,
            protocol_version=context.protocol_version,
            topic_text=protocol.review_question,
            topic_kind=TopicKind.QUESTION,
            provenance=(source,),
        ),
        status=ReviewRunStatus.RUNNING,
        stage=ReviewStage.STUDY_SELECTION,
        created_at="2026-08-01T00:00:00Z",
        updated_at="2026-08-01T00:00:00Z",
        artifacts={
            "q2protocol": build_artifact(
                context=context,
                task=TaskName.Q2PROTOCOL,
                data=protocol,
                provenance=(source,),
            ),
            "evidence_search": build_artifact(
                context=context,
                task=TaskName.EVIDENCE_SEARCH,
                data=EvidenceSearchArtifact(
                    search_runs=(
                        SearchRun(
                            search_run_id="search-run-1",
                            source_name="PubMed",
                            platform="NCBI",
                            query="randomized trial",
                            executed_at="2026-08-01T00:00:00Z",
                            status=SearchRunStatus.SUCCEEDED,
                            result_count=0,
                            retrieved_count=0,
                            status_reason=None,
                            search_narrative="The source returned no Records.",
                            provenance=(source,),
                        ),
                    ),
                    records=(),
                    summary=SearchSummary(1, 1, 0),
                    package_ref=SearchPackageRef(
                        package_id="search-package-1",
                        review_id=context.review_id,
                        protocol_version=context.protocol_version,
                        schema_version="search-package.v2",
                        content_digest="sha256:search",
                    ),
                ),
                provenance=(source,),
            ),
        },
    )
    use_case = ExecuteReviewRun(
        q2protocol=lambda: None,
        evidence_search=lambda: None,
        study_selection=lambda: SimpleNamespace(
            execute=lambda invocation: selection_result
        ),
        study_data_collection=lambda: None,
        risk_of_bias=lambda: None,
        evidence_synthesis=lambda: None,
        grade=lambda: None,
        systematic_review_reporting=lambda: None,
        data_collection_repository=None,
        grade_evidence_package_builder=None,
        systematic_review_evidence_package_builder=None,
    )

    advanced = use_case.advance(run)

    assert advanced.stage is expected_stage
    assert advanced.status is expected_run_status
    assert advanced.events[-1].code == expected_event
    assert advanced.artifacts["study_selection"] is selection_result


@pytest.mark.parametrize(
    (
        "run_statuses",
        "result_counts",
        "expected_stage",
        "expected_status",
        "expected_event",
    ),
    (
        (
            (SearchRunStatus.SUCCEEDED, SearchRunStatus.SUCCEEDED),
            (0, 0),
            ReviewStage.STUDY_SELECTION,
            ReviewRunStatus.RUNNING,
            "stage_completed",
        ),
        (
            (SearchRunStatus.SUCCEEDED, SearchRunStatus.FAILED),
            (0, 0),
            ReviewStage.STUDY_SELECTION,
            ReviewRunStatus.RUNNING,
            "stage_completed",
        ),
        (
            (SearchRunStatus.SUCCEEDED, SearchRunStatus.SUCCEEDED),
            (1, 0),
            ReviewStage.STUDY_SELECTION,
            ReviewRunStatus.RUNNING,
            "stage_completed",
        ),
    ),
)
def test_completed_search_always_advances_to_selection_including_zero_records(
    protocol,
    source,
    run_statuses,
    result_counts,
    expected_stage,
    expected_status,
    expected_event,
) -> None:
    context = TaskContext("review-1", protocol.version)
    runs = tuple(
        SearchRun(
            search_run_id=f"search-run-{index}",
            source_name=f"source-{index}",
            platform=f"platform-{index}",
            query="randomized trial",
            executed_at="2026-08-01T00:00:00Z",
            status=status,
            result_count=result_counts[index - 1],
            retrieved_count=0,
            status_reason=(
                "The source failed before returning Records."
                if status is SearchRunStatus.FAILED
                else None
            ),
            search_narrative="The source was executed and returned no Records.",
            provenance=(source,),
        )
        for index, status in enumerate(run_statuses, start=1)
    )
    search_result = build_artifact(
        context=context,
        task=TaskName.EVIDENCE_SEARCH,
        data=EvidenceSearchArtifact(
            search_runs=runs,
            records=(),
            summary=SearchSummary(
                run_count=len(runs),
                source_count=len(runs),
                record_count=0,
            ),
            package_ref=SearchPackageRef(
                package_id="search-package-1",
                review_id=context.review_id,
                protocol_version=context.protocol_version,
                schema_version="search-package.v2",
                content_digest="sha256:search",
            ),
        ),
        provenance=(source,),
    )
    run = _review_run(
        protocol=protocol,
        source=source,
        stage=ReviewStage.EVIDENCE_SEARCH,
    )
    use_case = _use_case(
        evidence_search=SimpleNamespace(execute=lambda invocation: search_result)
    )

    advanced = use_case.advance(run)

    assert advanced.stage is expected_stage
    assert advanced.status is expected_status
    assert advanced.events[-1].code == expected_event
    assert advanced.artifacts["evidence_search"] is search_result


def test_review_run_stops_when_search_task_is_truly_partial(
    protocol,
    source,
) -> None:
    context = TaskContext("review-1", protocol.version)
    search_result = build_artifact(
        context=context,
        task=TaskName.EVIDENCE_SEARCH,
        data=EvidenceSearchArtifact(
            search_runs=(
                SearchRun(
                    search_run_id="search-run-1",
                    source_name="source-1",
                    platform="platform-1",
                    query="randomized trial",
                    executed_at="2026-08-01T00:00:00Z",
                    status=SearchRunStatus.SUCCEEDED,
                    result_count=0,
                    retrieved_count=0,
                    status_reason=None,
                    search_narrative="The source returned no Records.",
                    provenance=(source,),
                ),
                SearchRun(
                    search_run_id="search-run-2",
                    source_name="source-2",
                    platform="platform-2",
                    query="randomized trial",
                    executed_at="2026-08-01T00:00:00Z",
                    status=SearchRunStatus.FAILED,
                    result_count=0,
                    retrieved_count=0,
                    status_reason="The source was unavailable.",
                    search_narrative="No Records could be retrieved.",
                    provenance=(source,),
                ),
            ),
            records=(),
            summary=SearchSummary(run_count=2, source_count=2, record_count=0),
            package_ref=SearchPackageRef(
                package_id="search-package-1",
                review_id=context.review_id,
                protocol_version=context.protocol_version,
                schema_version="search-package.v2",
                content_digest="sha256:search",
            ),
        ),
        provenance=(source,),
        status=ArtifactStatus.PARTIAL,
        issues=(
            ArtifactIssue(
                code="search_source_unavailable",
                message="One planned source was unavailable.",
            ),
        ),
    )
    run = _review_run(
        protocol=protocol,
        source=source,
        stage=ReviewStage.EVIDENCE_SEARCH,
    )
    use_case = _use_case(
        evidence_search=SimpleNamespace(execute=lambda invocation: search_result)
    )

    advanced = use_case.advance(run)

    assert advanced.stage is ReviewStage.EVIDENCE_SEARCH
    assert advanced.status is ReviewRunStatus.NEEDS_ATTENTION
    assert advanced.events[-1].code == "professional_task_partial"
    assert advanced.artifacts["evidence_search"] is search_result


def test_review_run_stops_when_risk_of_bias_task_is_truly_partial(
    protocol,
    source,
) -> None:
    context = TaskContext("review-1", protocol.version)
    selection_result = build_artifact(
        context=context,
        task=TaskName.STUDY_SELECTION,
        data=StudySelectionArtifact(
            package_ref=SelectionPackageRef(
                package_id="selection-package-1",
                review_id=context.review_id,
                protocol_version=context.protocol_version,
                schema_version="selection-package.v4",
                content_digest="sha256:selection",
            ),
            summary=SelectionSummary(
                source_record_count=1,
                duplicate_record_count=0,
                records_screened_count=1,
                title_abstract_excluded_count=0,
                reports_sought_count=1,
                reports_not_retrieved_count=0,
                reports_assessed_count=1,
                study_count=1,
                included_count=1,
                excluded_count=0,
                awaiting_classification_count=0,
                ongoing_count=0,
                unresolved_conflict_count=0,
            ),
        ),
        provenance=(source,),
    )
    collection_ref = CompletedArtifactRef(
        artifact_id="collection-1",
        schema_version="study-data-collection-artifact.v3",
        review_id=context.review_id,
        protocol_version=context.protocol_version,
        task=TaskName.STUDY_DATA_COLLECTION,
        content_digest="sha256:collection",
        files=(ArtifactFile("collection.json", "sha256:collection-file", 1),),
        counts={"study_count": 1},
    )
    partial = SimpleNamespace(
        status=ArtifactStatus.PARTIAL,
        data=object(),
        issues=(
            ArtifactIssue(
                code="rob_work_unfinished",
                message="A planned target remains unassessed.",
            ),
        ),
    )
    run = _review_run(
        protocol=protocol,
        source=source,
        stage=ReviewStage.RISK_OF_BIAS,
        include_search=True,
    )
    run = replace(
        run,
        artifacts={
            **run.artifacts,
            "study_selection": selection_result,
            "study_data_collection": collection_ref,
        },
    )

    advanced = _use_case(
        risk_of_bias=SimpleNamespace(execute=lambda invocation: partial)
    ).advance(run)

    assert advanced.stage is ReviewStage.RISK_OF_BIAS
    assert advanced.status is ReviewRunStatus.NEEDS_ATTENTION
    assert advanced.events[-1].code == "professional_task_partial"


def test_completed_data_collection_with_evidence_warnings_advances_to_risk_of_bias(
    protocol,
    source,
) -> None:
    context = TaskContext("review-1", protocol.version)
    selection_result = _included_selection_result(context, source)
    collection_ref = CompletedArtifactRef(
        artifact_id="collection-1",
        schema_version="study-data-collection-artifact.v3",
        review_id=context.review_id,
        protocol_version=context.protocol_version,
        task=TaskName.STUDY_DATA_COLLECTION,
        content_digest="sha256:collection",
        files=(ArtifactFile("collection.json", "sha256:collection-file", 1),),
        counts={"study_count": 1, "unreported_result_count": 1},
        warnings=(
            "One prespecified result was unreported after the available Report was read.",
        ),
    )
    completed = TaskWorkResult(
        status=TaskWorkStatus.COMPLETED,
        artifact=collection_ref,
        issues=(
            ArtifactIssue(
                code="result_unreported",
                message="The source did not report a usable result.",
            ),
        ),
    )
    run = _review_run(
        protocol=protocol,
        source=source,
        stage=ReviewStage.STUDY_DATA_COLLECTION,
        include_search=True,
    )
    run = replace(
        run,
        artifacts={**run.artifacts, "study_selection": selection_result},
    )

    advanced = _use_case(
        study_data_collection=SimpleNamespace(execute=lambda invocation: completed)
    ).advance(run)

    assert advanced.stage is ReviewStage.RISK_OF_BIAS
    assert advanced.status is ReviewRunStatus.RUNNING
    assert advanced.events[-1].code == "stage_completed"
    assert advanced.artifacts["study_data_collection"] is collection_ref
    assert collection_ref.warnings


@pytest.mark.parametrize(
    ("work_status", "expected_run_status", "expected_event"),
    (
        (
            TaskWorkStatus.INCOMPLETE,
            ReviewRunStatus.NEEDS_ATTENTION,
            "study_data_collection_incomplete",
        ),
        (
            TaskWorkStatus.BLOCKED,
            ReviewRunStatus.BLOCKED,
            "study_data_collection_blocked",
        ),
    ),
)
def test_data_collection_stops_only_when_required_work_is_unfinished_or_blocked(
    protocol,
    source,
    work_status,
    expected_run_status,
    expected_event,
) -> None:
    context = TaskContext("review-1", protocol.version)
    selection_result = _included_selection_result(context, source)
    result = TaskWorkResult(
        status=work_status,
        work_id="collection-work-1",
        blocker=(
            "The verified Selection Package cannot be opened."
            if work_status is TaskWorkStatus.BLOCKED
            else None
        ),
        issues=(
            ArtifactIssue(
                code="collection_work_unfinished",
                message="An Included Study has not yet been processed.",
            ),
        ),
    )
    run = _review_run(
        protocol=protocol,
        source=source,
        stage=ReviewStage.STUDY_DATA_COLLECTION,
        include_search=True,
    )
    run = replace(
        run,
        artifacts={**run.artifacts, "study_selection": selection_result},
    )

    advanced = _use_case(
        study_data_collection=SimpleNamespace(execute=lambda invocation: result)
    ).advance(run)

    assert advanced.stage is ReviewStage.STUDY_DATA_COLLECTION
    assert advanced.status is expected_run_status
    assert advanced.events[-1].code == expected_event
    assert advanced.work_ids["study_data_collection"] == "collection-work-1"
    assert "study_data_collection" not in advanced.artifacts


def test_completed_risk_of_bias_with_information_limits_advances_to_synthesis(
    protocol,
    source,
) -> None:
    context = TaskContext("review-1", protocol.version)
    selection_result = _included_selection_result(context, source)
    collection_ref = CompletedArtifactRef(
        artifact_id="collection-1",
        schema_version="study-data-collection-artifact.v3",
        review_id=context.review_id,
        protocol_version=context.protocol_version,
        task=TaskName.STUDY_DATA_COLLECTION,
        content_digest="sha256:collection",
        files=(ArtifactFile("collection.json", "sha256:collection-file", 1),),
        counts={"study_count": 1},
    )
    completed = SimpleNamespace(
        status=ArtifactStatus.COMPLETED,
        data=object(),
        issues=(
            ArtifactIssue(
                code="rob_information_insufficient",
                message=(
                    "The Report omitted allocation-concealment details; the "
                    "selected method's uncertainty judgement was recorded."
                ),
            ),
        ),
    )
    run = _review_run(
        protocol=protocol,
        source=source,
        stage=ReviewStage.RISK_OF_BIAS,
        include_search=True,
    )
    run = replace(
        run,
        artifacts={
            **run.artifacts,
            "study_selection": selection_result,
            "study_data_collection": collection_ref,
        },
    )

    advanced = _use_case(
        risk_of_bias=SimpleNamespace(execute=lambda invocation: completed)
    ).advance(run)

    assert advanced.stage is ReviewStage.EVIDENCE_SYNTHESIS
    assert advanced.status is ReviewRunStatus.RUNNING
    assert advanced.events[-1].code == "stage_completed"
    assert advanced.artifacts["risk_of_bias"] is completed
    assert advanced.issues[0].code == "rob_information_insufficient"


@pytest.mark.parametrize(
    ("grade_status", "expected_stage", "expected_run_status", "expected_event"),
    (
        (
            TaskWorkStatus.COMPLETED,
            ReviewStage.SYSTEMATIC_REVIEW_REPORTING,
            ReviewRunStatus.RUNNING,
            "stage_completed",
        ),
        (
            TaskWorkStatus.BLOCKED,
            ReviewStage.GRADE_SUMMARY_OF_FINDINGS,
            ReviewRunStatus.BLOCKED,
            "grade_summary_of_findings_blocked",
        ),
    ),
)
def test_grade_evidence_issues_do_not_escalate_task_status(
    protocol,
    source,
    grade_status,
    expected_stage,
    expected_run_status,
    expected_event,
) -> None:
    run = _review_run(
        protocol=protocol,
        source=source,
        stage=ReviewStage.GRADE_SUMMARY_OF_FINDINGS,
        include_search=True,
    )
    grade_ref = CompletedArtifactRef(
        artifact_id="grade-1",
        schema_version="grade-sof-artifact.v4",
        review_id="review-1",
        protocol_version=protocol.version,
        task=TaskName.GRADE_SUMMARY_OF_FINDINGS,
        content_digest="sha256:grade",
        files=(ArtifactFile("summary-of-findings.json", "sha256:sof", 1),),
        counts={"sof_rows": 1},
        warnings=("One selected outcome was not estimable.",),
    )
    grade_result = TaskWorkResult(
        status=grade_status,
        artifact=grade_ref if grade_status is TaskWorkStatus.COMPLETED else None,
        work_id="grade-work-1" if grade_status is TaskWorkStatus.BLOCKED else None,
        issues=(
            ArtifactIssue(
                code="grade_evidence_not_estimable",
                message="The effect could not be estimated from reported data.",
            ),
        ),
        blocker=(
            "The verified semantic Synthesis document is invalid."
            if grade_status is TaskWorkStatus.BLOCKED
            else None
        ),
    )
    use_case = ExecuteReviewRun(
        q2protocol=lambda: None,
        evidence_search=lambda: None,
        study_selection=lambda: None,
        study_data_collection=lambda: None,
        risk_of_bias=lambda: None,
        evidence_synthesis=lambda: None,
        grade=lambda: SimpleNamespace(execute=lambda invocation: grade_result),
        systematic_review_reporting=lambda: None,
        data_collection_repository=None,
        grade_evidence_package_builder=SimpleNamespace(
            build=lambda **kwargs: object()
        ),
        systematic_review_evidence_package_builder=None,
    )

    advanced = use_case.advance(run)

    assert advanced.stage is expected_stage
    assert advanced.status is expected_run_status
    assert advanced.events[-1].code == expected_event
    if grade_status is TaskWorkStatus.COMPLETED:
        assert advanced.artifacts["grade_summary_of_findings"] is grade_ref
    else:
        assert "grade_summary_of_findings" not in advanced.artifacts


@pytest.mark.parametrize(
    (
        "awaiting_count",
        "conflict_count",
        "expected_stage",
        "expected_status",
        "expected_event",
    ),
    (
        (
            0,
            0,
            ReviewStage.SYSTEMATIC_REVIEW_REPORTING,
            ReviewRunStatus.RUNNING,
            "empty_review_ready_for_reporting",
        ),
        (
            1,
            0,
            ReviewStage.SYSTEMATIC_REVIEW_REPORTING,
            ReviewRunStatus.RUNNING,
            "empty_review_ready_for_reporting",
        ),
        (
            0,
            1,
            ReviewStage.SYSTEMATIC_REVIEW_REPORTING,
            ReviewRunStatus.RUNNING,
            "empty_review_ready_for_reporting",
        ),
    ),
)
def test_review_run_routes_zero_included_studies_to_empty_review_reporting(
    protocol,
    source,
    awaiting_count,
    conflict_count,
    expected_stage,
    expected_status,
    expected_event,
) -> None:
    context = TaskContext("review-1", protocol.version)
    selection_result = build_artifact(
        context=context,
        task=TaskName.STUDY_SELECTION,
        data=StudySelectionArtifact(
            package_ref=SelectionPackageRef(
                package_id="selection-package-1",
                review_id=context.review_id,
                protocol_version=context.protocol_version,
                schema_version="selection-package.v4",
                content_digest="sha256:selection",
            ),
            summary=SelectionSummary(
                source_record_count=1,
                duplicate_record_count=0,
                records_screened_count=1,
                title_abstract_excluded_count=0,
                reports_sought_count=1,
                reports_not_retrieved_count=awaiting_count,
                reports_assessed_count=1 - awaiting_count,
                study_count=1,
                included_count=0,
                excluded_count=1 - awaiting_count,
                awaiting_classification_count=awaiting_count,
                ongoing_count=0,
                unresolved_conflict_count=conflict_count,
            ),
            search_continuation=SearchContinuationDecision(
                status=SearchContinuationStatus.PROCEED,
                rationale="The supplied evidence reached an honest conclusion.",
            ),
        ),
        provenance=(source,),
    )
    run = _review_run(
        protocol=protocol,
        source=source,
        stage=ReviewStage.STUDY_SELECTION,
        include_search=True,
    )
    use_case = _use_case(
        study_selection=SimpleNamespace(execute=lambda invocation: selection_result)
    )

    advanced = use_case.advance(run)

    assert advanced.stage is expected_stage
    assert advanced.status is expected_status
    assert advanced.events[-1].code == expected_event
    assert "study_data_collection" not in advanced.artifacts

    report_ref = CompletedArtifactRef(
        artifact_id="empty-review-1",
        schema_version="systematic-review-artifact.v5",
        review_id=context.review_id,
        protocol_version=context.protocol_version,
        task=TaskName.SYSTEMATIC_REVIEW_REPORTING,
        content_digest="sha256:empty-review",
        files=(ArtifactFile("review.json", "sha256:review", 1),),
        counts={"review_section_count": 8},
    )
    captured = {}

    evidence_package = SystematicReviewEvidencePackageRef(
        package_id="review-1:systematic-review-evidence",
        schema_version="systematic-review-evidence-package.v2",
        review_id=context.review_id,
        protocol_version=context.protocol_version,
        review_path=ReviewPath.EMPTY_REVIEW,
        content_digest="sha256:review-evidence",
        files=(ArtifactFile("review-context/protocol.json", "sha256:p", 1),),
    )

    def build_evidence_package(**kwargs):
        captured["empty_review"] = kwargs["empty_review"]
        return evidence_package

    def publish(invocation):
        captured["inputs"] = invocation.inputs
        return TaskWorkResult(
            status=TaskWorkStatus.COMPLETED,
            artifact=report_ref,
        )

    published = _use_case(
        systematic_review_reporting=SimpleNamespace(execute=publish),
        systematic_review_evidence_package_builder=SimpleNamespace(
            build=build_evidence_package
        ),
    ).advance(advanced)

    empty_review = captured["empty_review"]
    assert captured["inputs"].evidence_package is evidence_package
    assert captured["inputs"].protocol is protocol
    assert empty_review.selection_package_id == "selection-package-1"
    assert empty_review.included_count == 0
    assert empty_review.awaiting_classification_count == awaiting_count
    assert empty_review.unresolved_conflict_count == conflict_count
    assert published.status is ReviewRunStatus.RUNNING
    assert published.stage is ReviewStage.DONE
    assert published.events[-1].code == "stage_completed"
    assert published.artifacts["systematic_review"] is report_ref


def _review_run(
    *,
    protocol,
    source,
    stage: ReviewStage,
    include_search: bool = False,
) -> ReviewRun:
    context = TaskContext("review-1", protocol.version)
    artifacts = {
        "q2protocol": build_artifact(
            context=context,
            task=TaskName.Q2PROTOCOL,
            data=protocol,
            provenance=(source,),
        )
    }
    if include_search:
        artifacts["evidence_search"] = build_artifact(
            context=context,
            task=TaskName.EVIDENCE_SEARCH,
            data=EvidenceSearchArtifact(
                search_runs=(
                    SearchRun(
                        search_run_id="search-run-1",
                        source_name="source-1",
                        platform="platform-1",
                        query="randomized trial",
                        executed_at="2026-08-01T00:00:00Z",
                        status=SearchRunStatus.SUCCEEDED,
                        result_count=0,
                        retrieved_count=0,
                        status_reason=None,
                        search_narrative="The source returned no Records.",
                        provenance=(source,),
                    ),
                ),
                records=(),
                summary=SearchSummary(1, 1, 0),
                package_ref=SearchPackageRef(
                    package_id="search-package-1",
                    review_id=context.review_id,
                    protocol_version=context.protocol_version,
                    schema_version="search-package.v2",
                    content_digest="sha256:search",
                ),
            ),
            provenance=(source,),
        )
    return ReviewRun(
        run_id="run-1",
        request=CreateReviewRun(
            review_id=context.review_id,
            protocol_version=context.protocol_version,
            topic_text=protocol.review_question,
            topic_kind=TopicKind.QUESTION,
            provenance=(source,),
        ),
        status=ReviewRunStatus.RUNNING,
        stage=stage,
        created_at="2026-08-01T00:00:00Z",
        updated_at="2026-08-01T00:00:00Z",
        artifacts=artifacts,
    )


def _included_selection_result(context, source):
    return build_artifact(
        context=context,
        task=TaskName.STUDY_SELECTION,
        data=StudySelectionArtifact(
            package_ref=SelectionPackageRef(
                package_id="selection-package-1",
                review_id=context.review_id,
                protocol_version=context.protocol_version,
                schema_version="selection-package.v4",
                content_digest="sha256:selection",
            ),
            summary=SelectionSummary(
                source_record_count=1,
                duplicate_record_count=0,
                records_screened_count=1,
                title_abstract_excluded_count=0,
                reports_sought_count=1,
                reports_not_retrieved_count=0,
                reports_assessed_count=1,
                study_count=1,
                included_count=1,
                excluded_count=0,
                awaiting_classification_count=0,
                ongoing_count=0,
                unresolved_conflict_count=0,
            ),
        ),
        provenance=(source,),
    )


def _use_case(**overrides) -> ExecuteReviewRun:
    defaults = {
        "q2protocol": lambda: None,
        "evidence_search": lambda: None,
        "study_selection": lambda: None,
        "study_data_collection": lambda: None,
        "risk_of_bias": lambda: None,
        "evidence_synthesis": lambda: None,
        "grade": lambda: None,
        "systematic_review_reporting": lambda: None,
        "data_collection_repository": None,
        "grade_evidence_package_builder": None,
        "systematic_review_evidence_package_builder": None,
    }
    for name, value in overrides.items():
        if name.endswith("_package_builder") or name.endswith("_repository"):
            defaults[name] = value
        else:
            defaults[name] = lambda value=value: value
    return ExecuteReviewRun(**defaults)
