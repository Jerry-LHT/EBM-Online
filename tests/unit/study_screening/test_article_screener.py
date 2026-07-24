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
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.full_text_screening_llm.article_screener import (
    FullTextStudyArticleScreener,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.errors import (
    StudyScreeningInvocationError,
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
    captured = {}

    def fake_llm(**kwargs):
        captured["schema"] = kwargs["json_schema"]
        return {
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
        }

    screener = FullTextStudyArticleScreener(
        config={"temperature": 0},
        llm_caller=fake_llm,
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
    assert captured["schema"]["additionalProperties"] is False


def test_article_screener_rejects_invalid_judgment() -> None:
    calls = 0

    def invalid_llm(**_):
        nonlocal calls
        calls += 1
        return {
            "criterion_judgments": {
                "inc_1": {"judgment": "maybe", "reason": "", "evidence_spans": []},
            },
            "overall_note": "",
        }

    screener = FullTextStudyArticleScreener(
        config={"temperature": 0},
        llm_caller=invalid_llm,
    )

    try:
        screener.run(
            criteria=ScreeningCriteria(inclusion_criteria=["Adults"], exclusion_criteria=[]),
            article=_article(),
        )
    except StudyScreeningInvocationError as exc:
        assert exc.stage == "article_screening"
        assert exc.attempts == 2
        assert calls == 2
    else:
        raise AssertionError("Expected ValueError")


def test_article_screener_keeps_only_traceable_evidence_spans() -> None:
    screener = FullTextStudyArticleScreener(
        config={"temperature": 0},
        llm_caller=lambda **_: {
            "criterion_judgments": {
                "inc_1": {
                    "judgment": "yes",
                    "reason": "The population is reported.",
                    "evidence_spans": [
                        "Adults   with hypertension.",
                        "Adults with hypertension were enrolled.",
                    ],
                },
            },
            "overall_note": "",
        },
    )

    result = screener.run(
        criteria=ScreeningCriteria(inclusion_criteria=["Adults with hypertension"]),
        article=_article(),
    )

    assert [span.text for span in result.criterion_judgments[0].source_spans] == [
        "Adults   with hypertension."
    ]
