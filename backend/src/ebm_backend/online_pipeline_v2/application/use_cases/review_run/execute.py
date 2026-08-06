"""Application orchestration for persistent end-to-end Review Runs."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from pydantic import TypeAdapter

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactEnvelope,
    ArtifactStatus,
    CompletedArtifactRef,
    Provenance,
    TaskContext,
    TaskInvocation,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.grade import (
    GradeProtocol,
    GradeSummaryOfFindingsInput,
)
from ebm_backend.online_pipeline_v2.domain.protocol import (
    ProtocolDraft,
    Q2ProtocolInput,
)
from ebm_backend.online_pipeline_v2.domain.review_run import (
    ReviewRun,
    ReviewRunStatus,
    ReviewStage,
)
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasArtifact,
    RiskOfBiasInput,
)
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchMode,
    EvidenceSearchArtifact,
    EvidenceSearchInput,
    public_search_artifact,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    SearchContinuationStatus,
    StudySelectionArtifact,
    StudySelectionInput,
    study_selection_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.domain.study_data_collection import (
    StudyDataCollectionInput,
    study_data_collection_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.domain.synthesis import (
    EvidenceSynthesisInput,
    evidence_synthesis_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    EmptyReviewContext,
    SystematicReviewReportingInput,
)
from ebm_backend.online_pipeline_v2.application.ports.review_runs import (
    GradeEvidencePackageBuilder,
    SystematicReviewEvidencePackageBuilder,
)


_PROTOCOL_ENVELOPE = TypeAdapter(ArtifactEnvelope[ProtocolDraft])
_SEARCH_ENVELOPE = TypeAdapter(ArtifactEnvelope[EvidenceSearchArtifact])
_SELECTION_ENVELOPE = TypeAdapter(ArtifactEnvelope[StudySelectionArtifact])
_ROB_ENVELOPE = TypeAdapter(ArtifactEnvelope[RiskOfBiasArtifact])
_COMPLETED = TypeAdapter(CompletedArtifactRef)


class ExecuteReviewRun:
    """Choose and advance one approved professional task boundary."""

    def __init__(
        self,
        *,
        q2protocol: Callable[[], object],
        evidence_search: Callable[[], object],
        study_selection: Callable[[], object],
        study_data_collection: Callable[[], object],
        risk_of_bias: Callable[[], object],
        evidence_synthesis: Callable[[], object],
        grade: Callable[[], object],
        systematic_review_reporting: Callable[[], object],
        data_collection_repository,
        grade_evidence_package_builder: GradeEvidencePackageBuilder,
        systematic_review_evidence_package_builder: SystematicReviewEvidencePackageBuilder,
    ) -> None:
        self._q2protocol = q2protocol
        self._evidence_search = evidence_search
        self._study_selection = study_selection
        self._study_data_collection = study_data_collection
        self._risk_of_bias = risk_of_bias
        self._evidence_synthesis = evidence_synthesis
        self._grade = grade
        self._systematic_review_reporting = systematic_review_reporting
        self._data_collection_repository = data_collection_repository
        self._grade_evidence_package_builder = grade_evidence_package_builder
        self._systematic_review_evidence_package_builder = (
            systematic_review_evidence_package_builder
        )

    def advance(self, run: ReviewRun) -> ReviewRun:
        attempts = dict(run.stage_attempts)
        attempts[run.stage.value] = attempts.get(run.stage.value, 0) + 1
        run = replace(run, stage_attempts=attempts)
        method = getattr(self, f"_advance_{run.stage.value}")
        return method(run)

    def _advance_q2protocol(self, run: ReviewRun) -> ReviewRun:
        request = run.request
        result = self._q2protocol().execute(
            TaskInvocation(
                context=self._context(run),
                inputs=Q2ProtocolInput(
                    topic_text=request.topic_text,
                    topic_kind=request.topic_kind,
                    scope_notes=request.scope_notes,
                    background_sources=request.background_sources,
                    standards=request.standards,
                    template=request.template,
                ),
                provenance=request.provenance,
            )
        )
        run = self._with_artifact(run, "q2protocol", result)
        return self._after_envelope(
            run,
            result,
            next_stage=ReviewStage.EVIDENCE_SEARCH,
        )

    def _advance_evidence_search(self, run: ReviewRun) -> ReviewRun:
        protocol = self._protocol(run)
        search_input = EvidenceSearchInput(protocol=protocol)
        previous_selection = run.artifacts.get("study_selection")
        if previous_selection is not None:
            selection = _SELECTION_ENVELOPE.validate_python(previous_selection)
            decision = selection.data.search_continuation
            if decision.status is SearchContinuationStatus.CONTINUE_SEARCH:
                prior_search = _SEARCH_ENVELOPE.validate_python(
                    run.artifacts["evidence_search"]
                )
                search_input = EvidenceSearchInput(
                    protocol=protocol,
                    mode=EvidenceSearchMode.SUPPLEMENTARY,
                    parent_package_ref=prior_search.data.package_ref,
                    supplementary_reason=decision.rationale,
                    evidence_gaps=decision.evidence_gaps,
                    candidate_leads=decision.candidate_leads,
                )
        result = self._evidence_search().execute(
            TaskInvocation(
                context=self._context(run),
                inputs=search_input,
                provenance=run.request.provenance,
            )
        )
        run = self._with_artifact(run, "evidence_search", result)
        return self._after_envelope(
            run,
            result,
            next_stage=ReviewStage.STUDY_SELECTION,
        )

    def _advance_study_selection(self, run: ReviewRun) -> ReviewRun:
        protocol = self._protocol(run)
        search = _SEARCH_ENVELOPE.validate_python(run.artifacts["evidence_search"])
        result = self._study_selection().execute(
            TaskInvocation(
                context=self._context(run),
                inputs=StudySelectionInput(
                    protocol=study_selection_protocol_from_draft(protocol),
                    search=public_search_artifact(search.data),
                ),
                provenance=run.request.provenance,
            )
        )
        run = self._with_artifact(run, "study_selection", result)
        if result.status is not ArtifactStatus.COMPLETED:
            return self._after_envelope(
                run,
                result,
                next_stage=ReviewStage.STUDY_DATA_COLLECTION,
            )
        decision = result.data.search_continuation
        if decision.status is SearchContinuationStatus.BLOCKED:
            return run.event(
                code="selection_blocked_search",
                message=decision.rationale,
                status=ReviewRunStatus.BLOCKED,
            )
        if decision.status is SearchContinuationStatus.CONTINUE_SEARCH:
            return run.event(
                code="supplementary_search_required",
                message=decision.rationale,
                stage=ReviewStage.EVIDENCE_SEARCH,
                status=ReviewRunStatus.NEEDS_ATTENTION,
            )
        summary = result.data.summary
        if summary.included_count == 0:
            return run.event(
                code="empty_review_ready_for_reporting",
                message=(
                    "Study Selection completed with no Included Studies; "
                    "the recorded awaiting, ongoing, and conflict states will be "
                    "carried into an explicit empty-review reporting outcome."
                ),
                stage=ReviewStage.SYSTEMATIC_REVIEW_REPORTING,
                status=ReviewRunStatus.RUNNING,
            )
        return run.event(
            code="stage_completed",
            message="Study Selection completed.",
            stage=ReviewStage.STUDY_DATA_COLLECTION,
        )

    def _advance_study_data_collection(self, run: ReviewRun) -> ReviewRun:
        protocol = self._protocol(run)
        selection = self._selection(run)
        result = self._study_data_collection().execute(
            TaskInvocation(
                context=self._context(run),
                inputs=StudyDataCollectionInput(
                    protocol=study_data_collection_protocol_from_draft(protocol),
                    selection=selection.data,
                ),
                provenance=run.request.provenance,
            )
        )
        return self._after_work(
            run,
            "study_data_collection",
            result,
            ReviewStage.RISK_OF_BIAS,
        )

    def _advance_risk_of_bias(self, run: ReviewRun) -> ReviewRun:
        protocol = self._protocol(run)
        selection = self._selection(run)
        collection_ref = _COMPLETED.validate_python(
            run.artifacts["study_data_collection"]
        )
        result = self._risk_of_bias().execute(
            TaskInvocation(
                context=self._context(run),
                inputs=RiskOfBiasInput(
                    protocol=protocol,
                    selection=selection.data,
                    study_data_collection=collection_ref,
                ),
                provenance=run.request.provenance,
            )
        )
        run = self._with_artifact(run, "risk_of_bias", result)
        return self._after_envelope(
            run,
            result,
            next_stage=ReviewStage.EVIDENCE_SYNTHESIS,
        )

    def _advance_evidence_synthesis(self, run: ReviewRun) -> ReviewRun:
        protocol = self._protocol(run)
        collection_ref = _COMPLETED.validate_python(
            run.artifacts["study_data_collection"]
        )
        rob = _ROB_ENVELOPE.validate_python(run.artifacts["risk_of_bias"])
        result = self._evidence_synthesis().execute(
            TaskInvocation(
                context=self._context(run),
                inputs=EvidenceSynthesisInput(
                    protocol=evidence_synthesis_protocol_from_draft(protocol),
                    study_data_collection=collection_ref,
                    risk_of_bias=rob.data,
                    work_id=run.work_ids.get("evidence_synthesis"),
                ),
                provenance=run.request.provenance,
            )
        )
        return self._after_work(
            run,
            "evidence_synthesis",
            result,
            ReviewStage.GRADE_SUMMARY_OF_FINDINGS,
        )

    def _advance_grade_summary_of_findings(self, run: ReviewRun) -> ReviewRun:
        protocol = self._protocol(run)
        package = self._grade_evidence_package_builder.build(
            run=run,
            protocol=protocol,
        )
        result = self._grade().execute(
            TaskInvocation(
                context=self._context(run),
                inputs=GradeSummaryOfFindingsInput(
                    protocol=GradeProtocol.from_protocol(protocol),
                    evidence_package=package,
                ),
                provenance=run.request.provenance,
            )
        )
        return self._after_work(
            run,
            "grade_summary_of_findings",
            result,
            ReviewStage.SYSTEMATIC_REVIEW_REPORTING,
        )

    def _advance_systematic_review_reporting(self, run: ReviewRun) -> ReviewRun:
        protocol = self._protocol(run)
        empty_review = self._empty_review_context(run)
        evidence_package = self._systematic_review_evidence_package_builder.build(
            run=run,
            protocol=protocol,
            empty_review=empty_review,
        )
        result = self._systematic_review_reporting().execute(
            TaskInvocation(
                context=self._context(run),
                inputs=SystematicReviewReportingInput(
                    protocol=protocol,
                    evidence_package=evidence_package,
                ),
                provenance=run.request.provenance,
            )
        )
        return self._after_work(
            run,
            "systematic_review",
            result,
            ReviewStage.DONE,
        )

    def _advance_done(self, run: ReviewRun) -> ReviewRun:
        return run.event(
            code="run_completed",
            message="All professional task boundaries completed.",
            status=ReviewRunStatus.COMPLETED,
        )

    def _after_envelope(self, run, result, *, next_stage):
        if result.status is ArtifactStatus.BLOCKED:
            return run.event(
                code="professional_task_blocked",
                message=f"{run.stage.value} returned blocked.",
                status=ReviewRunStatus.BLOCKED,
            )
        if result.status is ArtifactStatus.PARTIAL:
            return run.event(
                code="professional_task_partial",
                message=f"{run.stage.value} returned partial.",
                status=ReviewRunStatus.NEEDS_ATTENTION,
            )
        return run.event(
            code="stage_completed",
            message=f"{run.stage.value} completed.",
            stage=next_stage,
        )

    def _after_work(self, run, key, result, next_stage):
        artifacts = dict(run.artifacts)
        work_ids = dict(run.work_ids)
        if result.status is TaskWorkStatus.COMPLETED:
            artifacts[key] = result.artifact
            work_ids.pop(key, None)
            return replace(
                run,
                artifacts=artifacts,
                work_ids=work_ids,
            ).event(
                code="stage_completed",
                message=f"{key} completed.",
                stage=next_stage,
            )
        work_ids[key] = result.work_id
        status = (
            ReviewRunStatus.BLOCKED
            if result.status is TaskWorkStatus.BLOCKED
            else ReviewRunStatus.NEEDS_ATTENTION
        )
        return replace(run, work_ids=work_ids, issues=result.issues).event(
            code=f"{key}_{result.status.value}",
            message=result.blocker or f"{key} requires another explicit resume.",
            status=status,
        )

    def _context(self, run):
        return TaskContext(
            review_id=run.request.review_id,
            protocol_version=run.request.protocol_version,
        )

    def _protocol(self, run):
        return _PROTOCOL_ENVELOPE.validate_python(run.artifacts["q2protocol"]).data

    def _selection(self, run):
        return _SELECTION_ENVELOPE.validate_python(run.artifacts["study_selection"])

    def _empty_review_context(self, run: ReviewRun) -> EmptyReviewContext | None:
        value = run.artifacts.get("study_selection")
        if value is None:
            return None
        selection = _SELECTION_ENVELOPE.validate_python(value)
        if (
            selection.status is not ArtifactStatus.COMPLETED
            or selection.data is None
            or selection.data.summary.included_count != 0
        ):
            return None
        summary = selection.data.summary
        package = selection.data.package_ref
        return EmptyReviewContext(
            selection_package_id=package.package_id,
            selection_package_digest=package.content_digest,
            source_record_count=summary.source_record_count,
            study_count=summary.study_count,
            included_count=summary.included_count,
            excluded_count=summary.excluded_count,
            awaiting_classification_count=summary.awaiting_classification_count,
            ongoing_count=summary.ongoing_count,
            unresolved_conflict_count=summary.unresolved_conflict_count,
        )

    def _with_artifact(self, run, key, artifact):
        artifacts = dict(run.artifacts)
        artifacts[key] = artifact
        return replace(run, artifacts=artifacts, issues=artifact.issues)
