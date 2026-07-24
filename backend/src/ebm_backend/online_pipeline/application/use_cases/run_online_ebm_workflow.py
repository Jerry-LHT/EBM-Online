"""Application orchestration for the complete currently enabled Online EBM workflow."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Any, Callable
from uuid import uuid4

from ebm_backend.online_pipeline.application.ports.workflow_persistence import (
    WorkflowRunStorePort,
)
from ebm_backend.online_pipeline.application.use_cases.run_grade import RunGrade
from ebm_backend.online_pipeline.application.use_cases.run_article_qualification import (
    RunArticleQualification,
)
from ebm_backend.online_pipeline.application.use_cases.run_meta_analysis import RunMetaAnalysis
from ebm_backend.online_pipeline.application.use_cases.run_q2pico import RunQ2PICO
from ebm_backend.online_pipeline.application.use_cases.run_risk_of_bias import RunRiskOfBias
from ebm_backend.online_pipeline.application.use_cases.run_search_retrieval import RunSearchRetrieval
from ebm_backend.online_pipeline.application.use_cases.run_study_pio import RunStudyPIO
from ebm_backend.online_pipeline.application.use_cases.run_study_screening import RunStudyScreening
from ebm_backend.online_pipeline.domain.article import CleanedArticle, SearchRetrievalResult
from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleQualificationDecision,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.domain.workflow import (
    OnlineEBMWorkflowResult,
    WorkflowSearchRetrievalSummary,
    WorkflowSearchSourceSummary,
    WorkflowArticlePrecheckDecision,
    WorkflowArticlePrecheckResult,
    WorkflowStageRecord,
    WorkflowStudySelection,
)
@dataclass(frozen=True)
class RunOnlineEBMWorkflow:
    q2pico: RunQ2PICO
    search_retrieval: RunSearchRetrieval
    article_qualification: RunArticleQualification
    study_screening: RunStudyScreening
    study_pio: RunStudyPIO
    risk_of_bias: RunRiskOfBias
    meta_analysis: RunMetaAnalysis
    grade: RunGrade
    run_store: WorkflowRunStorePort | None = None

    def execute(
        self,
        *,
        review_id: str,
        question_text: str,
        constraints: WorkflowConstraints,
        retrieval_config: ModuleRunConfig,
        expand_outcomes: bool = True,
    ) -> OnlineEBMWorkflowResult:
        run_id = str(uuid4())
        persistence = _PersistenceTracker(store=self.run_store, run_id=run_id)
        persistence.create(
            review_id=review_id,
            question_text=question_text,
            request={
                "review_id": review_id,
                "question_text": question_text,
                "constraints": to_jsonable(constraints),
                "retrieval_config": to_jsonable(retrieval_config),
                "expand_outcomes": expand_outcomes,
            },
        )
        stages: list[WorkflowStageRecord] = []
        current_stage = "q2pico"
        try:
            question_pico = self.q2pico.execute(
                question_text=question_text,
                expand_outcomes=expand_outcomes,
            )
            _record_stage(
                stages=stages,
                stage=_success("q2pico", question_pico),
                persistence=persistence,
            )
            current_stage = "search_retrieval"
            search_result = self.search_retrieval.execute(
                question_pico=question_pico,
                config=retrieval_config,
            )
            search_summary = _search_retrieval_summary(search_result)
            _record_stage(
                stages=stages,
                stage=_success("search_retrieval", search_summary),
                persistence=persistence,
            )
            current_stage = "article_precheck"
            article_precheck = _precheck_articles(
                articles=search_result.articles,
                constraints=constraints,
            )
            _record_stage(
                stages=stages,
                stage=_success("article_precheck", article_precheck),
                persistence=persistence,
            )
            prechecked_articles = _included_articles(
                included_studies=article_precheck.passed_studies,
                articles=search_result.articles,
            )
            current_stage = "article_qualification"
            qualification_result = self.article_qualification.execute(
                articles=prechecked_articles,
            )
            _record_stage(
                stages=stages,
                stage=_success("article_qualification", qualification_result),
                persistence=persistence,
            )
            screening_candidate_ids = [
                assessment.study_id
                for assessment in qualification_result.assessments
                if assessment.decision != ArticleQualificationDecision.EXCLUDE
            ]
            screening_articles = _included_articles(
                included_studies=screening_candidate_ids,
                articles=prechecked_articles,
            )
            current_stage = "study_screening"
            screening_criteria = self.study_screening.prepare_criteria(
                question_text=question_text,
                question_pico=question_pico,
                constraints=constraints,
            )
            current_stage = "meta_analysis.synthesis_planning"
            synthesis_plan = self.meta_analysis.plan(
                review_id=review_id,
                question_text=question_text,
                question_pico=question_pico,
                screening_criteria=screening_criteria,
            )
            _record_stage(
                stages=stages,
                stage=_success("meta_analysis.synthesis_planning", synthesis_plan),
                persistence=persistence,
            )
            current_stage = "study_screening"
            screening_result = self.study_screening.execute(
                question_text=question_text,
                question_pico=question_pico,
                constraints=constraints,
                articles=screening_articles,
                criteria=screening_criteria,
                synthesis_plan=synthesis_plan,
            )
            _record_stage(
                stages=stages,
                stage=_success("study_screening", screening_result),
                persistence=persistence,
            )
            current_stage = "downstream_study_selection"
            study_selection = _select_downstream_studies(
                included_studies=screening_result.included_studies,
                meta_analysis_studies=_meta_analysis_studies(
                    included_studies=screening_result.included_studies,
                    ready_studies=screening_result.meta_ready_studies,
                    investigation_studies=screening_result.meta_investigation_studies,
                ),
            )
            _record_stage(
                stages=stages,
                stage=_success("downstream_study_selection", study_selection),
                persistence=persistence,
            )
            included_articles = _included_articles(
                included_studies=study_selection.selected_study_ids,
                articles=screening_articles,
            )
            meta_articles = _included_articles(
                included_studies=study_selection.meta_analysis_study_ids,
                articles=screening_articles,
            )
        except Exception as exc:
            failed_stage = current_stage
            _record_stage(
                stages=stages,
                stage=_failure(failed_stage, exc),
                persistence=persistence,
            )
            for stage in _not_run_after_sequential_failure(failed_stage):
                _record_stage(
                    stages=stages,
                    stage=stage,
                    persistence=persistence,
                )
            return persistence.finalize(OnlineEBMWorkflowResult(
                review_id=review_id,
                question_text=question_text,
                status="failed",
                run_id=run_id,
                stages=stages,
                question_pico=locals().get("question_pico"),
                search_retrieval=locals().get("search_summary"),
                article_precheck=locals().get("article_precheck"),
                article_qualification=locals().get("qualification_result"),
                study_screening=locals().get("screening_result"),
                study_selection=locals().get("study_selection"),
                grade_status="not_run_due_to_upstream_failure",
            ))

        branch_actions: dict[str, Callable[[], Any]] = {
            "study_pio": lambda: self.study_pio.execute(
                question_pico=question_pico,
                included_studies=study_selection.selected_study_ids,
                articles=included_articles,
            ),
            "risk_of_bias": lambda: self.risk_of_bias.execute(
                included_studies=study_selection.selected_study_ids,
                articles=included_articles,
            ),
            "meta_analysis": lambda: self.meta_analysis.execute(
                review_id=review_id,
                question_text=question_text,
                question_pico=question_pico,
                screening_criteria=screening_result.screening_criteria,
                included_studies=study_selection.meta_analysis_study_ids,
                articles=meta_articles,
                synthesis_plan=synthesis_plan,
            ),
        }
        branch_results: dict[str, Any] = {}
        branch_errors: dict[str, Exception] = {}
        branch_records: dict[str, WorkflowStageRecord] = {}
        meta_substage_records: list[WorkflowStageRecord] = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures: dict[Future[Any], str] = {
                executor.submit(action): name
                for name, action in branch_actions.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    branch_results[name] = future.result()
                except Exception as exc:
                    branch_errors[name] = exc
                    branch_records[name] = _failure(name, exc)
                else:
                    branch_records[name] = _success(name, branch_results[name])
                    if name == "meta_analysis":
                        meta_substage_records = _meta_substage_records(
                            branch_results[name]
                        )
                persistence.save(branch_records[name])
                if name == "meta_analysis":
                    for stage in meta_substage_records:
                        persistence.save(stage)
        for name in ("study_pio", "risk_of_bias", "meta_analysis"):
            stages.append(branch_records[name])
            if name == "meta_analysis":
                stages.extend(meta_substage_records)
        if branch_errors:
            _record_stage(
                stages=stages,
                stage=_not_run(
                    "grade", "One or more required post-screening branches failed."
                ),
                persistence=persistence,
            )
            return persistence.finalize(OnlineEBMWorkflowResult(
                review_id=review_id,
                question_text=question_text,
                status="failed",
                run_id=run_id,
                stages=stages,
                question_pico=question_pico,
                search_retrieval=search_summary,
                article_precheck=article_precheck,
                article_qualification=qualification_result,
                study_screening=screening_result,
                study_selection=study_selection,
                study_pio=branch_results.get("study_pio") or [],
                risk_of_bias=branch_results.get("risk_of_bias") or [],
                meta_analysis=branch_results.get("meta_analysis"),
                grade_status="not_run_due_to_upstream_failure",
            ))

        try:
            grade_result = self.grade.execute(
                review_id=review_id,
                question_text=question_text,
                question_pico=question_pico,
                screening_criteria=screening_result.screening_criteria,
                study_characteristics=branch_results["study_pio"],
                risk_of_bias=branch_results["risk_of_bias"],
                meta_analysis_result=branch_results["meta_analysis"],
            )
            _record_stage(
                stages=stages,
                stage=_success("grade", grade_result),
                persistence=persistence,
            )
        except Exception as exc:
            _record_stage(
                stages=stages,
                stage=_failure("grade", exc),
                persistence=persistence,
            )
            return persistence.finalize(OnlineEBMWorkflowResult(
                review_id=review_id,
                question_text=question_text,
                status="failed",
                run_id=run_id,
                stages=stages,
                question_pico=question_pico,
                search_retrieval=search_summary,
                article_precheck=article_precheck,
                article_qualification=qualification_result,
                study_screening=screening_result,
                study_selection=study_selection,
                study_pio=branch_results["study_pio"],
                risk_of_bias=branch_results["risk_of_bias"],
                meta_analysis=branch_results["meta_analysis"],
                grade_status="failed",
            ))
        return persistence.finalize(OnlineEBMWorkflowResult(
            review_id=review_id,
            question_text=question_text,
            status="succeeded",
            run_id=run_id,
            stages=stages,
            question_pico=question_pico,
            search_retrieval=search_summary,
            article_precheck=article_precheck,
            article_qualification=qualification_result,
            study_screening=screening_result,
            study_selection=study_selection,
            study_pio=branch_results.get("study_pio") or [],
            risk_of_bias=branch_results.get("risk_of_bias") or [],
            meta_analysis=branch_results.get("meta_analysis"),
            grade=grade_result,
            grade_status="succeeded",
        ))


_STAGE_SEQUENCE = {
    "q2pico": 10,
    "search_retrieval": 20,
    "article_precheck": 22,
    "article_qualification": 24,
    "meta_analysis.synthesis_planning": 25,
    "study_screening": 30,
    "downstream_study_selection": 35,
    "study_pio": 40,
    "risk_of_bias": 50,
    "meta_analysis": 60,
    "meta_analysis.candidate_extraction": 62,
    "meta_analysis.candidate_resolution": 63,
    "meta_analysis.analysis_dataset": 64,
    "meta_analysis.analysis_model_decision": 65,
    "meta_analysis.subgroup_analysis": 66,
    "meta_analysis.overall_estimate": 67,
    "grade": 70,
}


@dataclass
class _PersistenceTracker:
    store: WorkflowRunStorePort | None
    run_id: str
    successful_writes: int = 0
    failed_writes: int = 0

    def create(
        self,
        *,
        review_id: str,
        question_text: str,
        request: dict[str, Any],
    ) -> None:
        if self.store is None:
            return
        try:
            self.store.create_run(
                run_id=self.run_id,
                review_id=review_id,
                question_text=question_text,
                request=request,
            )
        except Exception:
            self.failed_writes += 1
        else:
            self.successful_writes += 1

    def save(self, stage: WorkflowStageRecord) -> None:
        if self.store is None:
            return
        try:
            self.store.save_stage(
                run_id=self.run_id,
                sequence=_STAGE_SEQUENCE[stage.stage_name],
                stage=stage,
            )
        except Exception:
            self.failed_writes += 1
        else:
            self.successful_writes += 1

    def finalize(
        self,
        result: OnlineEBMWorkflowResult,
    ) -> OnlineEBMWorkflowResult:
        if self.store is None:
            return replace(
                result,
                persistence_status="disabled",
                persistence_error_code=None,
            )
        status = self._status()
        candidate = replace(
            result,
            persistence_status=status,
            persistence_error_code=(
                "workflow_persistence_failed"
                if status in {"partial", "failed"}
                else None
            ),
        )
        try:
            self.store.finalize_run(run_id=self.run_id, result=candidate)
        except Exception:
            self.failed_writes += 1
            status = self._status()
            return replace(
                result,
                persistence_status=status,
                persistence_error_code="workflow_persistence_failed",
            )
        self.successful_writes += 1
        return candidate

    def _status(self) -> str:
        if self.failed_writes == 0:
            return "succeeded"
        if self.successful_writes > 0:
            return "partial"
        return "failed"


def _record_stage(
    *,
    stages: list[WorkflowStageRecord],
    stage: WorkflowStageRecord,
    persistence: _PersistenceTracker,
) -> None:
    stages.append(stage)
    persistence.save(stage)


def _included_articles(
    *,
    included_studies: list[str],
    articles: list[CleanedArticle],
) -> list[CleanedArticle]:
    if len(set(included_studies)) != len(included_studies):
        raise ValueError("included_studies must not contain duplicate study IDs")
    by_study: dict[str, CleanedArticle] = {}
    for article in articles:
        if article.study_id in by_study:
            raise ValueError(f"Multiple articles were provided for study_id '{article.study_id}'")
        by_study[article.study_id] = article
    missing = [study_id for study_id in included_studies if study_id not in by_study]
    if missing:
        raise ValueError(f"Missing CleanedArticle for included study_id(s): {', '.join(missing)}")
    return [by_study[study_id] for study_id in included_studies]


def _select_downstream_studies(
    *,
    included_studies: list[str],
    meta_analysis_studies: list[str],
) -> WorkflowStudySelection:
    if len(set(included_studies)) != len(included_studies):
        raise ValueError("included_studies must not contain duplicate study IDs")
    included_set = set(included_studies)
    unexpected_meta = [
        study_id for study_id in meta_analysis_studies if study_id not in included_set
    ]
    if unexpected_meta:
        raise ValueError(
            "Meta-analysis routing contains non-included study IDs: "
            + ", ".join(unexpected_meta)
        )
    selected = list(included_studies)
    meta_set = set(meta_analysis_studies)
    return WorkflowStudySelection(
        eligible_study_ids=list(included_studies),
        selected_study_ids=selected,
        not_selected_study_ids=[],
        max_downstream_studies=None,
        selection_policy="all_review_included_no_scientific_top_n",
        truncated=False,
        meta_analysis_study_ids=list(meta_analysis_studies),
        meta_unavailable_study_ids=[
            study_id for study_id in included_studies if study_id not in meta_set
        ],
    )


def _meta_analysis_studies(
    *,
    included_studies: list[str],
    ready_studies: list[str],
    investigation_studies: list[str],
) -> list[str]:
    candidates = set(ready_studies) | set(investigation_studies)
    return [study_id for study_id in included_studies if study_id in candidates]


def _precheck_articles(
    *,
    articles: list[CleanedArticle],
    constraints: WorkflowConstraints,
) -> WorkflowArticlePrecheckResult:
    start, end = _publication_year_bounds(constraints.publication_year_range)
    decisions: list[WorkflowArticlePrecheckDecision] = []
    passed: list[str] = []
    excluded: list[str] = []
    for article in articles:
        if article.metadata.is_retracted or article.metadata.is_retraction_notice:
            decision = WorkflowArticlePrecheckDecision(
                study_id=article.study_id,
                decision="exclude",
                reason="Provider metadata identifies a retracted article or retraction notice.",
            )
            excluded.append(article.study_id)
        elif start is not None or end is not None:
            year = _publication_year(article.metadata.publication_year)
            if (
                year is None
                or (start is not None and year < start)
                or (end is not None and year > end)
            ):
                decision = WorkflowArticlePrecheckDecision(
                    study_id=article.study_id,
                    decision="exclude",
                    reason=(
                        "Publication year is missing, invalid, or outside the "
                        f"configured range {start or '-inf'}..{end or '+inf'}."
                    ),
                )
                excluded.append(article.study_id)
            else:
                decision = WorkflowArticlePrecheckDecision(
                    study_id=article.study_id,
                    decision="pass",
                    reason="Publication year satisfies the configured deterministic rule.",
                )
                passed.append(article.study_id)
        else:
            decision = WorkflowArticlePrecheckDecision(
                study_id=article.study_id,
                decision="pass",
                reason="Full-text XML is available and no configured hard exclusion matched.",
            )
            passed.append(article.study_id)
        decisions.append(decision)
    return WorkflowArticlePrecheckResult(
        decisions=decisions,
        passed_studies=passed,
        excluded_studies=excluded,
    )


def _publication_year_bounds(value: str | None) -> tuple[int | None, int | None]:
    raw = str(value or "").strip()
    if not raw:
        return None, None
    parts = [part.strip() for part in raw.split("-", 1)]
    if len(parts) != 2 or not all(part.isdigit() and len(part) == 4 for part in parts):
        raise ValueError("publication_year_range must use YYYY-YYYY format")
    start, end = (int(part) for part in parts)
    if start > end:
        raise ValueError("publication_year_range start must not exceed end")
    return start, end


def _publication_year(value: str | None) -> int | None:
    text = str(value or "").strip()
    return int(text) if len(text) == 4 and text.isdigit() else None


def _search_retrieval_summary(
    result: SearchRetrievalResult,
) -> WorkflowSearchRetrievalSummary:
    return WorkflowSearchRetrievalSummary(
        returned_count=result.returned_count,
        retrieved_record_count=result.retrieved_record_count,
        full_text_available_count=result.full_text_available_count,
        remaining_full_text_count=result.remaining_full_text_count,
        truncated=result.truncated,
        retrieved_study_ids=[article.study_id for article in result.articles],
        source_results=[
            WorkflowSearchSourceSummary(
                source_name=item.source_name,
                search_query=item.search_query,
                query_used=item.query_used,
                total_hits=item.total_hits,
                returned_count=item.returned_count,
                retrieved_record_count=item.retrieved_record_count,
                full_text_available_count=item.full_text_available_count,
                remaining_full_text_count=item.remaining_full_text_count,
                truncated=item.truncated,
                warnings=list(item.warnings),
            )
            for item in result.source_results
        ],
    )


def _success(stage_name: str, value: Any) -> WorkflowStageRecord:
    output = to_jsonable(value)
    return WorkflowStageRecord(stage_name=stage_name, status="succeeded", output=output)


def _failure(stage_name: str, exc: Exception) -> WorkflowStageRecord:
    return WorkflowStageRecord(
        stage_name=stage_name,
        status="failed",
        error=f"{type(exc).__name__}: {exc}",
    )


def _not_run(stage_name: str, reason: str) -> WorkflowStageRecord:
    return WorkflowStageRecord(
        stage_name=stage_name,
        status="not_run_due_to_upstream_failure",
        error=reason,
    )


def _not_run_after_sequential_failure(
    failed_stage: str,
) -> list[WorkflowStageRecord]:
    order = (
        "q2pico",
        "search_retrieval",
        "article_precheck",
        "article_qualification",
        "meta_analysis.synthesis_planning",
        "study_screening",
        "downstream_study_selection",
        "study_pio",
        "risk_of_bias",
        "meta_analysis",
        "grade",
    )
    failed_index = order.index(failed_stage)
    return [
        _not_run(
            stage_name,
            f"Required upstream stage '{failed_stage}' failed.",
        )
        for stage_name in order[failed_index + 1 :]
    ]


def _meta_substage_records(meta_result: Any) -> list[WorkflowStageRecord]:
    return [
        _success("meta_analysis.candidate_extraction", meta_result.study_result_rows),
        _success(
            "meta_analysis.candidate_resolution",
            meta_result.candidate_resolution_records,
        ),
        _success(
            "meta_analysis.analysis_dataset",
            meta_result.synthesis_analysis_datasets,
        ),
        _success("meta_analysis.analysis_model_decision", meta_result.analysis_methods),
        _success(
            "meta_analysis.subgroup_analysis",
            {
                "subgroup_estimates": to_jsonable(meta_result.subgroup_estimates),
                "subgroup_difference_tests": to_jsonable(meta_result.subgroup_difference_tests),
            },
        ),
        _success("meta_analysis.overall_estimate", meta_result.overall_estimates),
    ]
