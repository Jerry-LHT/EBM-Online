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
from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan, WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import (
    ArticleScreeningResult,
    ScreeningCriteria,
    ScreeningCriterionJudgment,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
)


@dataclass(frozen=True)
class _FakeCriteriaPlanner:
    def run(self, **kwargs) -> ScreeningCriteria:
        return ScreeningCriteria(
            inclusion_criteria=["Adults with hypertension"],
            exclusion_criteria=["Protocol-only report"],
            rationale="Planned.",
        )


@dataclass(frozen=True)
class _FakeArticleScreener:
    def run(self, *, criteria, article, **kwargs) -> ArticleScreeningResult:
        judgments = [
            ScreeningCriterionJudgment(
                criterion_text=criterion,
                criterion_type=ScreeningCriterionType.INCLUSION,
                judgment=ScreeningCriterionJudgmentValue.YES,
                reason="Inclusion criterion is satisfied.",
            )
            for criterion in criteria.inclusion_criteria
        ]
        judgments.extend(
            ScreeningCriterionJudgment(
                criterion_text=criterion,
                criterion_type=ScreeningCriterionType.EXCLUSION,
                judgment=(
                    ScreeningCriterionJudgmentValue.YES
                    if article.study_id == "pmc::exclude"
                    else ScreeningCriterionJudgmentValue.NO
                ),
                reason=(
                    "This is a protocol."
                    if article.study_id == "pmc::exclude"
                    else "The exclusion criterion is not triggered."
                ),
            )
            for criterion in criteria.exclusion_criteria
        )
        return ArticleScreeningResult(
            criterion_judgments=judgments,
            overall_note="Screened.",
        )


def _article(study_id: str) -> CleanedArticle:
    return CleanedArticle(
        study_id=study_id,
        metadata=ArticleMetadata(title=study_id),
        xml_content=ArticleXmlContent(),
    )


def test_run_study_screening_orchestrates_and_aggregates_decisions() -> None:
    result = RunStudyScreening(
        criteria_planner=_FakeCriteriaPlanner(),
        article_screener=_FakeArticleScreener(),
        max_workers=2,
    ).execute(
        question_text="Question",
        question_pico=QuestionPICO(P=["Adults"], I=["exercise"]),
        constraints=WorkflowConstraints(),
        articles=[_article("pmc::include"), _article("pmc::exclude")],
    )

    assert result.screening_criteria.inclusion_criteria[0] == "Adults with hypertension"
    assert any(
        "randomized allocation" in criterion
        for criterion in result.screening_criteria.inclusion_criteria
    )
    assert any(
        "primary results report" in criterion
        for criterion in result.screening_criteria.inclusion_criteria
    )
    assert [item.study_id for item in result.decisions] == ["pmc::include", "pmc::exclude"]
    assert [item.decision for item in result.decisions] == ["include", "exclude"]
    assert result.included_studies == ["pmc::include"]
    assert result.decisions[1].exclusion_reason == "This is a protocol."


def test_run_study_screening_returns_empty_decisions_for_no_articles() -> None:
    result = RunStudyScreening(
        criteria_planner=_FakeCriteriaPlanner(),
        article_screener=_FakeArticleScreener(),
    ).execute(
        question_text="Question",
        question_pico=QuestionPICO(P=["Adults"]),
        constraints=WorkflowConstraints(),
        articles=[],
    )

    assert result.decisions == []
    assert result.included_studies == []


def test_run_study_screening_rejects_non_positive_worker_limit() -> None:
    use_case = RunStudyScreening(
        criteria_planner=_FakeCriteriaPlanner(),
        article_screener=_FakeArticleScreener(),
        max_workers=0,
    )

    try:
        use_case.execute(
            question_text="Question",
            question_pico=QuestionPICO(P=["Adults"]),
            constraints=WorkflowConstraints(),
            articles=[],
        )
    except ValueError as exc:
        assert "max_workers must be positive" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
