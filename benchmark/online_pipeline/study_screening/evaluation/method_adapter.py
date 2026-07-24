"""Benchmark adapter for the backend article-screening capability."""

from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.application.ports import StudyArticleScreenerPort
from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.screening import (
    ScreeningCriteria,
    StudyScreeningResult,
    screening_decision_from_article_result,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.factory import (
    build_production_study_screening,
)


@dataclass(frozen=True)
class ArticleScreeningBenchmarkMethod:
    article_screener: StudyArticleScreenerPort

    def run_article_screening(
        self,
        *,
        question_text: str,
        screening_criteria: ScreeningCriteria,
        articles: list[CleanedArticle],
    ) -> StudyScreeningResult:
        decisions = [
            screening_decision_from_article_result(
                study_id=article.study_id,
                result=self.article_screener.run(
                    criteria=screening_criteria,
                    article=article,
                ),
            )
            for article in articles
        ]
        return StudyScreeningResult(
            screening_criteria=screening_criteria,
            decisions=decisions,
            included_studies=[
                decision.study_id
                for decision in decisions
                if decision.decision == "include"
            ],
        )


def load_article_screening_method(method_spec: str) -> ArticleScreeningBenchmarkMethod:
    method_name = _method_name(method_spec=method_spec, module_name="study_screening")
    if method_name != "default":
        raise ValueError(f"Unknown Study Screening benchmark method '{method_name}'")
    method_pair = build_production_study_screening()
    return ArticleScreeningBenchmarkMethod(article_screener=method_pair.article_screener)


def _method_name(*, method_spec: str, module_name: str) -> str:
    if "." not in method_spec:
        return method_spec
    supplied_module, method_name = method_spec.split(".", 1)
    if supplied_module != module_name:
        raise ValueError(
            f"Method '{method_spec}' does not belong to benchmark module '{module_name}'"
        )
    return method_name
