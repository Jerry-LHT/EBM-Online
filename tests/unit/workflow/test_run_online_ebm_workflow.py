from __future__ import annotations

from threading import Barrier

from ebm_backend.online_pipeline.application.use_cases.run_online_ebm_workflow import (
    RunOnlineEBMWorkflow,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleXmlContent,
    CleanedArticle,
    SearchRetrievalResult,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleQualificationAssessment,
    ArticleQualificationDecision,
    ArticleQualificationResult,
    ArticleReportRole,
    RandomizationStatus,
    ResultsReportStatus,
    TrialDesign,
)
from ebm_backend.online_pipeline.domain.grade import GradeResult
from ebm_backend.online_pipeline.domain.meta_analysis import (
    MetaAnalysisResultPackage,
    MetaAnalysisSynthesisPlan,
)
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria, StudyScreeningResult
from ebm_backend.online_pipeline.domain.serialization import to_jsonable


ARTICLE = CleanedArticle(
    study_id="study-1",
    metadata=ArticleMetadata(title="RCT"),
    xml_content=ArticleXmlContent(),
)


class _Q2PICO:
    def execute(self, **kwargs):
        return QuestionPICO(P=["adults"], I=["treatment"], C=["control"], O=["outcome"])


class _Search:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        articles: list[CleanedArticle] | None = None,
    ) -> None:
        self.error = error
        self.articles = articles or [ARTICLE]

    def execute(self, **kwargs):
        if self.error:
            raise self.error
        return SearchRetrievalResult(
            returned_count=len(self.articles),
            articles=self.articles,
        )


class _Qualification:
    def execute(self, *, articles):
        assessments = [
            ArticleQualificationAssessment(
                study_id=article.study_id,
                decision=ArticleQualificationDecision.PASS,
                report_role=ArticleReportRole.PRIMARY_RESULTS,
                randomization_status=RandomizationStatus.RANDOMIZED,
                trial_design=TrialDesign.INDIVIDUAL_PARALLEL,
                results_report_status=ResultsReportStatus.RESULTS_REPORTED,
                has_quantitative_results=True,
                reason="Eligible article type.",
            )
            for article in articles
        ]
        return ArticleQualificationResult(
            assessments=assessments,
            passed_studies=[item.study_id for item in assessments],
        )


class _Screening:
    def __init__(
        self,
        included_studies: list[str] | None = None,
        meta_ready_studies: list[str] | None = None,
    ) -> None:
        self.included_studies = (
            ["study-1"] if included_studies is None else included_studies
        )
        self.meta_ready_studies = (
            self.included_studies
            if meta_ready_studies is None
            else meta_ready_studies
        )
        self.calls = []

    def prepare_criteria(self, **kwargs):
        return ScreeningCriteria(inclusion_criteria=["Eligible randomized trial"])

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return StudyScreeningResult(
            screening_criteria=kwargs["criteria"],
            decisions=[],
            included_studies=self.included_studies,
            meta_ready_studies=self.meta_ready_studies,
        )


class _ParallelBranch:
    def __init__(self, barrier: Barrier, result=None, error: Exception | None = None):
        self.barrier = barrier
        self.result = result
        self.error = error
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        self.barrier.wait(timeout=2)
        if self.error:
            raise self.error
        return self.result


class _MetaBranch(_ParallelBranch):
    def plan(self, **kwargs):
        return MetaAnalysisSynthesisPlan(
            plan_id="plan-1",
            review_id=kwargs["review_id"],
            version="1",
            status="frozen",
            plan_hash="hash-1",
        )


class _Grade:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return GradeResult(
            review_id=kwargs["review_id"],
            question_text=kwargs["question_text"],
        )


def _workflow(
    *,
    pio_error: Exception | None = None,
    grade_error: Exception | None = None,
    search_error: Exception | None = None,
    run_store=None,
    articles: list[CleanedArticle] | None = None,
    included_studies: list[str] | None = None,
    meta_ready_studies: list[str] | None = None,
) -> RunOnlineEBMWorkflow:
    barrier = Barrier(3)
    return RunOnlineEBMWorkflow(
        q2pico=_Q2PICO(),  # type: ignore[arg-type]
        search_retrieval=_Search(  # type: ignore[arg-type]
            error=search_error,
            articles=articles,
        ),
        article_qualification=_Qualification(),  # type: ignore[arg-type]
        study_screening=_Screening(  # type: ignore[arg-type]
            included_studies,
            meta_ready_studies,
        ),
        study_pio=_ParallelBranch(barrier, result=[], error=pio_error),  # type: ignore[arg-type]
        risk_of_bias=_ParallelBranch(barrier, result=[]),  # type: ignore[arg-type]
        meta_analysis=_MetaBranch(  # type: ignore[arg-type]
            barrier,
            result=MetaAnalysisResultPackage(review_id="review-1"),
        ),
        grade=_Grade(error=grade_error),  # type: ignore[arg-type]
        run_store=run_store,
    )


class _RecordingRunStore:
    def __init__(self, *, fail_writes: bool = False) -> None:
        self.fail_writes = fail_writes
        self.events = []

    def _record(self, name, kwargs):
        if self.fail_writes:
            raise OSError("disk unavailable")
        self.events.append((name, kwargs))

    def create_run(self, **kwargs):
        self._record("create", kwargs)

    def save_stage(self, **kwargs):
        self._record("stage", kwargs)

    def finalize_run(self, **kwargs):
        self._record("final", kwargs)

    def load_run(self, **kwargs):
        raise NotImplementedError


def test_workflow_runs_three_post_screening_branches_concurrently_and_records_stages() -> None:
    workflow = _workflow()
    result = workflow.execute(
        review_id="review-1",
        question_text="question",
        constraints=WorkflowConstraints(),
        retrieval_config=ModuleRunConfig(),
    )

    assert result.status == "succeeded"
    assert [stage.stage_name for stage in result.stages[:8]] == [
        "q2pico",
        "search_retrieval",
        "article_precheck",
        "article_qualification",
        "meta_analysis.synthesis_planning",
        "study_screening",
        "downstream_study_selection",
        "study_pio",
    ]
    assert result.stages[8].stage_name == "risk_of_bias"
    assert result.stages[9].stage_name == "meta_analysis"
    assert result.stages[-1].stage_name == "grade"
    assert result.stages[-1].status == "succeeded"
    assert result.grade is not None
    assert result.grade_status == "succeeded"
    assert result.search_retrieval is not None
    assert result.search_retrieval.retrieved_study_ids == ["study-1"]
    serialized = to_jsonable(result)
    assert "articles" not in serialized["search_retrieval"]
    assert "RCT" not in str(serialized["search_retrieval"])
    assert "articles" not in result.stages[1].output
    grade_call = workflow.grade.calls[0]  # type: ignore[attr-defined]
    assert grade_call["study_characteristics"] == result.study_pio
    assert grade_call["risk_of_bias"] == result.risk_of_bias
    assert grade_call["meta_analysis_result"] is result.meta_analysis


def test_workflow_routes_all_review_included_without_scientific_top_n() -> None:
    articles = [
        CleanedArticle(
            study_id=f"study-{index}",
            metadata=ArticleMetadata(title=f"RCT {index}"),
            xml_content=ArticleXmlContent(),
        )
        for index in range(1, 5)
    ]
    included_studies = [article.study_id for article in articles]
    workflow = _workflow(
        articles=articles,
        included_studies=included_studies,
    )

    result = workflow.execute(
        review_id="review-1",
        question_text="question",
        constraints=WorkflowConstraints(),
        retrieval_config=ModuleRunConfig(),
    )

    assert result.study_screening is not None
    assert result.study_screening.included_studies == included_studies
    assert result.study_selection is not None
    assert result.study_selection.selected_study_ids == included_studies
    assert result.study_selection.not_selected_study_ids == []
    assert result.study_selection.truncated is False
    for branch in (workflow.study_pio, workflow.risk_of_bias, workflow.meta_analysis):
        assert branch.calls[0]["included_studies"] == included_studies  # type: ignore[attr-defined]
        assert [article.study_id for article in branch.calls[0]["articles"]] == [  # type: ignore[attr-defined]
            "study-1",
            "study-2",
            "study-3",
            "study-4",
        ]


def test_workflow_routes_review_included_no_table_study_to_pio_and_rob_not_meta() -> None:
    articles = [
        CleanedArticle(
            study_id=study_id,
            metadata=ArticleMetadata(title=study_id),
            xml_content=ArticleXmlContent(),
        )
        for study_id in ("meta-ready", "no-readable-table")
    ]
    workflow = _workflow(
        articles=articles,
        included_studies=["meta-ready", "no-readable-table"],
        meta_ready_studies=["meta-ready"],
    )

    result = workflow.execute(
        review_id="review-1",
        question_text="question",
        constraints=WorkflowConstraints(),
        retrieval_config=ModuleRunConfig(),
    )

    assert result.status == "succeeded"
    assert workflow.study_pio.calls[0]["included_studies"] == [  # type: ignore[attr-defined]
        "meta-ready",
        "no-readable-table",
    ]
    assert workflow.risk_of_bias.calls[0]["included_studies"] == [  # type: ignore[attr-defined]
        "meta-ready",
        "no-readable-table",
    ]
    assert workflow.meta_analysis.calls[0]["included_studies"] == [  # type: ignore[attr-defined]
        "meta-ready"
    ]
    assert result.study_selection.meta_unavailable_study_ids == [
        "no-readable-table"
    ]


def test_workflow_checkpoints_stages_and_returns_run_identity() -> None:
    store = _RecordingRunStore()
    result = _workflow(run_store=store).execute(
        review_id="review-1",
        question_text="question",
        constraints=WorkflowConstraints(),
        retrieval_config=ModuleRunConfig(),
    )

    assert result.run_id
    assert result.persistence_status == "succeeded"
    assert store.events[0][0] == "create"
    assert store.events[-1][0] == "final"
    stage_names = [
        event[1]["stage"].stage_name
        for event in store.events
        if event[0] == "stage"
    ]
    assert stage_names[:3] == [
        "q2pico",
        "search_retrieval",
        "article_precheck",
    ]
    assert set(stage_names) >= {"study_pio", "risk_of_bias", "meta_analysis", "grade"}


def test_workflow_persistence_failure_does_not_fail_evidence_chain() -> None:
    result = _workflow(run_store=_RecordingRunStore(fail_writes=True)).execute(
        review_id="review-1",
        question_text="question",
        constraints=WorkflowConstraints(),
        retrieval_config=ModuleRunConfig(),
    )

    assert result.status == "succeeded"
    assert result.persistence_status == "failed"


def test_workflow_retains_successful_parallel_outputs_when_one_branch_fails() -> None:
    result = _workflow(pio_error=RuntimeError("pio failed")).execute(
        review_id="review-1",
        question_text="question",
        constraints=WorkflowConstraints(),
        retrieval_config=ModuleRunConfig(),
    )

    statuses = {stage.stage_name: stage.status for stage in result.stages}
    assert result.status == "failed"
    assert statuses["study_pio"] == "failed"
    assert statuses["risk_of_bias"] == "succeeded"
    assert statuses["meta_analysis"] == "succeeded"
    assert statuses["grade"] == "not_run_due_to_upstream_failure"
    assert result.meta_analysis is not None
    assert result.grade is None
    assert result.grade_status == "not_run_due_to_upstream_failure"


def test_workflow_retains_all_upstream_outputs_when_grade_fails() -> None:
    result = _workflow(grade_error=RuntimeError("grade failed")).execute(
        review_id="review-1",
        question_text="question",
        constraints=WorkflowConstraints(),
        retrieval_config=ModuleRunConfig(),
    )

    assert result.status == "failed"
    assert result.question_pico is not None
    assert result.search_retrieval is not None
    assert result.study_screening is not None
    assert result.meta_analysis is not None
    assert result.grade is None
    assert result.grade_status == "failed"
    assert result.stages[-1].stage_name == "grade"
    assert result.stages[-1].status == "failed"


def test_workflow_returns_prior_evidence_when_a_sequential_stage_fails() -> None:
    result = _workflow(search_error=RuntimeError("search failed")).execute(
        review_id="review-1",
        question_text="question",
        constraints=WorkflowConstraints(),
        retrieval_config=ModuleRunConfig(),
    )

    statuses = {stage.stage_name: stage.status for stage in result.stages}
    assert result.status == "failed"
    assert result.question_pico is not None
    assert result.search_retrieval is None
    assert result.study_screening is None
    assert statuses["q2pico"] == "succeeded"
    assert statuses["search_retrieval"] == "failed"
    assert statuses["study_screening"] == "not_run_due_to_upstream_failure"
    assert statuses["grade"] == "not_run_due_to_upstream_failure"
