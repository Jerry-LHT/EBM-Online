from __future__ import annotations

from dataclasses import dataclass

from benchmark.online_pipeline.study_screening.evaluation.method_adapter import (
    ArticleScreeningBenchmarkMethod,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.screening import (
    ArticleScreeningResult,
    ScreeningCriteria,
    ScreeningCriterionJudgment,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
)


@dataclass(frozen=True)
class _FakeArticleScreener:
    def run(self, *, criteria, article) -> ArticleScreeningResult:
        return ArticleScreeningResult(
            criterion_judgments=[
                ScreeningCriterionJudgment(
                    criterion_text="Protocol-only report",
                    criterion_type=ScreeningCriterionType.EXCLUSION,
                    judgment=ScreeningCriterionJudgmentValue.YES,
                    reason="Protocol identified.",
                )
            ]
        )


def test_benchmark_adapter_uses_backend_article_screening_contract() -> None:
    criteria = ScreeningCriteria(exclusion_criteria=["Protocol-only report"])
    article = CleanedArticle(
        study_id="pmc::1",
        metadata=ArticleMetadata(title="Protocol"),
        xml_content=ArticleXmlContent(),
    )

    result = ArticleScreeningBenchmarkMethod(
        article_screener=_FakeArticleScreener()
    ).run_article_screening(
        question_text="Question",
        screening_criteria=criteria,
        articles=[article],
    )

    assert result.screening_criteria == criteria
    assert result.decisions[0].decision == "exclude"
    assert result.included_studies == []
