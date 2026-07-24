"""Bounded article-level orchestration for content-based type qualification."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from ebm_backend.online_pipeline.application.ports.article_qualification import (
    ArticleQualificationPort,
)
from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleQualificationAssessment,
    ArticleQualificationDecision,
    ArticleQualificationResult,
    ArticleReportRole,
    RandomizationStatus,
    ResultsReportStatus,
    TrialDesign,
)


DEFAULT_MAX_WORKERS = 8
MAX_ARTICLES = 500


@dataclass(frozen=True)
class RunArticleQualification:
    qualifier: ArticleQualificationPort
    max_workers: int = DEFAULT_MAX_WORKERS

    def execute(
        self,
        *,
        articles: list[CleanedArticle],
    ) -> ArticleQualificationResult:
        if len(articles) > MAX_ARTICLES:
            raise ValueError(
                f"Article qualification supports at most {MAX_ARTICLES} articles per run"
            )
        if self.max_workers <= 0:
            raise ValueError("Article qualification max_workers must be positive")
        if not articles:
            return ArticleQualificationResult()

        assessments_by_index: dict[int, ArticleQualificationAssessment] = {}
        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, len(articles))
        ) as executor:
            futures: dict[Future[ArticleQualificationAssessment], tuple[int, str]] = {
                executor.submit(self.qualifier.run, article=article): (
                    index,
                    article.study_id,
                )
                for index, article in enumerate(articles)
            }
            for future in as_completed(futures):
                index, study_id = futures[future]
                try:
                    assessments_by_index[index] = future.result()
                except Exception as exc:
                    assessments_by_index[index] = _technical_failure(
                        study_id=study_id,
                        exc=exc,
                    )

        assessments = [
            assessments_by_index[index] for index in range(len(articles))
        ]
        return ArticleQualificationResult(
            assessments=assessments,
            passed_studies=[
                item.study_id
                for item in assessments
                if item.decision == ArticleQualificationDecision.PASS
            ],
            uncertain_studies=[
                item.study_id
                for item in assessments
                if item.decision == ArticleQualificationDecision.ADVANCE_UNCERTAIN
            ],
            excluded_studies=[
                item.study_id
                for item in assessments
                if item.decision == ArticleQualificationDecision.EXCLUDE
            ],
            technical_failure_studies=[
                item.study_id
                for item in assessments
                if item.decision == ArticleQualificationDecision.TECHNICAL_FAILURE
            ],
        )


def _technical_failure(
    *,
    study_id: str,
    exc: Exception,
) -> ArticleQualificationAssessment:
    failure_code = str(
        getattr(exc, "failure_code", "article_qualification_technical_failure")
    )
    return ArticleQualificationAssessment(
        study_id=study_id,
        decision=ArticleQualificationDecision.TECHNICAL_FAILURE,
        report_role=ArticleReportRole.UNCLEAR,
        randomization_status=RandomizationStatus.UNCLEAR,
        trial_design=TrialDesign.UNCLEAR,
        results_report_status=ResultsReportStatus.UNCLEAR,
        has_quantitative_results=None,
        reason=(
            "Article type could not be assessed because the classifier failed; "
            "the article advances rather than being medically excluded."
        ),
        failure_code=failure_code,
    )

