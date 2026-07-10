from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan, WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import (
    ScreeningCriteria,
    ScreeningCriterionJudgment,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.article_screener import (
    ArticleScreeningResult,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.method import Method


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
    def run(self, *, article, **kwargs) -> ArticleScreeningResult:
        if article.study_id == "pmc::exclude":
            judgments = [
                ScreeningCriterionJudgment(
                    criterion_text="Adults with hypertension",
                    criterion_type=ScreeningCriterionType.INCLUSION,
                    judgment=ScreeningCriterionJudgmentValue.YES,
                    reason="Population matches.",
                    source_spans=[EvidenceSourceSpan(source_id="article_text", text="Adults with hypertension")],
                ),
                ScreeningCriterionJudgment(
                    criterion_text="Protocol-only report",
                    criterion_type=ScreeningCriterionType.EXCLUSION,
                    judgment=ScreeningCriterionJudgmentValue.YES,
                    reason="This is a protocol.",
                    source_spans=[EvidenceSourceSpan(source_id="article_text", text="study protocol")],
                ),
            ]
            return ArticleScreeningResult(criterion_judgments=judgments, overall_note="Exclude.")
        judgments = [
            ScreeningCriterionJudgment(
                criterion_text="Adults with hypertension",
                criterion_type=ScreeningCriterionType.INCLUSION,
                judgment=ScreeningCriterionJudgmentValue.UNCLEAR,
                reason="Population likely matches but not explicit everywhere.",
                source_spans=[],
            ),
            ScreeningCriterionJudgment(
                criterion_text="Protocol-only report",
                criterion_type=ScreeningCriterionType.EXCLUSION,
                judgment=ScreeningCriterionJudgmentValue.NO,
                reason="Original study report.",
                source_spans=[],
            ),
        ]
        return ArticleScreeningResult(criterion_judgments=judgments, overall_note="")


def _article(study_id: str) -> CleanedArticle:
    return CleanedArticle(
        study_id=study_id,
        metadata=ArticleMetadata(title=study_id),
        xml_content=ArticleXmlContent(),
    )


def test_method_aggregates_to_binary_decisions() -> None:
    method = Method(
        criteria_planner=_FakeCriteriaPlanner(),
        article_screener=_FakeArticleScreener(),
        max_workers=2,
    )

    result = method.run(
        question_text="Question",
        question_pico=QuestionPICO(P=["Adults with hypertension"], I=["exercise"]),
        constraints=WorkflowConstraints(),
        articles=[_article("pmc::include"), _article("pmc::exclude")],
    )

    assert result.screening_criteria.inclusion_criteria == ["Adults with hypertension"]
    assert [item.decision for item in result.decisions] == ["include", "exclude"]
    assert result.included_studies == ["pmc::include"]
    assert result.decisions[1].exclusion_reason == "Protocol-only report"
