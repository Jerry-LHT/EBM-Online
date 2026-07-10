from __future__ import annotations

from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.screening import (
    ScreeningCriteria,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.article_screener import (
    StudyScreeningArticleScreener,
)


def _article() -> CleanedArticle:
    return CleanedArticle(
        study_id="pmc::1",
        metadata=ArticleMetadata(title="Exercise for hypertension", pmid="1", pmc_id="PMC1"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(section_id="s1", title="Methods", text="Randomized trial methods."),
                ArticleSection(section_id="s2", title="Participants", text="Adults with hypertension."),
                ArticleSection(section_id="s3", title="Results", text="Blood pressure improved."),
            ]
        ),
    )


def test_article_screener_parses_criterion_judgments() -> None:
    screener = StudyScreeningArticleScreener(
        config={"temperature": 0},
        llm_caller=lambda **_: {
            "criterion_judgments": {
                "inc_1": {
                    "judgment": "yes",
                    "reason": "Adults with hypertension were enrolled.",
                    "evidence_spans": ["Adults with hypertension."],
                },
                "exc_1": {
                    "judgment": "no",
                    "reason": "This is not a protocol.",
                    "evidence_spans": [],
                },
            },
            "overall_note": "Eligible article.",
        },
    )

    result = screener.run(
        criteria=ScreeningCriteria(
            inclusion_criteria=["Adults with hypertension"],
            exclusion_criteria=["Protocol-only report"],
        ),
        article=_article(),
    )

    assert len(result.criterion_judgments) == 2
    assert result.criterion_judgments[0].criterion_type == ScreeningCriterionType.INCLUSION
    assert result.criterion_judgments[0].judgment == ScreeningCriterionJudgmentValue.YES
    assert result.criterion_judgments[1].criterion_type == ScreeningCriterionType.EXCLUSION
    assert result.overall_note == "Eligible article."


def test_article_screener_rejects_invalid_judgment() -> None:
    screener = StudyScreeningArticleScreener(
        config={"temperature": 0},
        llm_caller=lambda **_: {
            "criterion_judgments": {
                "inc_1": {"judgment": "maybe", "reason": "", "evidence_spans": []},
            },
            "overall_note": "",
        },
    )

    try:
        screener.run(
            criteria=ScreeningCriteria(inclusion_criteria=["Adults"], exclusion_criteria=[]),
            article=_article(),
        )
    except ValueError as exc:
        assert "must be one of yes, no, unclear" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
