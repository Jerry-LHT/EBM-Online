from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.application.use_cases.run_study_screening import (
    RunStudyScreening,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import (
    ArticleScreeningResult,
    ScreeningCriteria,
    ScreeningCriterionJudgment,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
    ScreeningPolicy,
    ScreeningReportScope,
)


@dataclass(frozen=True)
class _Planner:
    def run(self, **kwargs) -> ScreeningCriteria:
        return ScreeningCriteria(inclusion_criteria=["Population is eligible."])


class _Screener:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, criteria, article) -> ArticleScreeningResult:
        self.calls += 1
        return ArticleScreeningResult(
            criterion_judgments=[
                ScreeningCriterionJudgment(
                    criterion_text=criterion,
                    criterion_type=ScreeningCriterionType.INCLUSION,
                    judgment=ScreeningCriterionJudgmentValue.YES,
                    reason="Supported by the article.",
                )
                for criterion in criteria.inclusion_criteria
            ]
        )


def _article(**metadata_kwargs) -> CleanedArticle:
    return CleanedArticle(
        study_id="article-1",
        metadata=ArticleMetadata(title="Candidate", **metadata_kwargs),
        xml_content=ArticleXmlContent(),
    )


def test_publication_year_is_evaluated_deterministically_before_llm() -> None:
    screener = _Screener()
    result = RunStudyScreening(
        criteria_planner=_Planner(),
        article_screener=screener,
    ).execute(
        question_text="Question",
        question_pico=QuestionPICO(P=["Adults"]),
        constraints=WorkflowConstraints(),
        articles=[_article(publication_year="1999")],
        policy=ScreeningPolicy(
            publication_year_start=2000,
            publication_year_end=2024,
        ),
    )

    assert screener.calls == 0
    assert result.decisions[0].decision == "exclude"
    assert result.decisions[0].criterion_judgments[0].criterion_id == (
        "metadata_publication_year"
    )
    assert result.decisions[0].criterion_judgments[0].decision_source == (
        "deterministic"
    )
    assert result.decisions[0].exclusion_reason == (
        "Publication year is missing, invalid, or outside 2000..2024."
    )
    assert result.excluded_articles == ["article-1"]


def test_pubmed_publication_type_does_not_deterministically_exclude() -> None:
    screener = _Screener()
    result = RunStudyScreening(
        criteria_planner=_Planner(),
        article_screener=screener,
    ).execute(
        question_text="Question",
        question_pico=QuestionPICO(P=["Adults"]),
        constraints=WorkflowConstraints(),
        articles=[_article(publication_types=["Systematic Review"])],
        policy=ScreeningPolicy(),
    )

    assert screener.calls == 1
    assert result.decisions[0].decision == "include"


def test_rct_and_primary_report_criteria_can_be_disabled_independently() -> None:
    screener = _Screener()
    result = RunStudyScreening(
        criteria_planner=_Planner(),
        article_screener=screener,
    ).execute(
        question_text="Question",
        question_pico=QuestionPICO(P=["Adults"]),
        constraints=WorkflowConstraints(study_design=""),
        articles=[_article()],
        policy=ScreeningPolicy(
            rct_only=False,
            report_scope=ScreeningReportScope.ALL_STUDY_REPORTS,
        ),
    )

    assert result.screening_criteria.inclusion_criteria == ["Population is eligible."]
    assert result.decisions[0].decision == "include"
    assert result.included_articles == ["article-1"]
