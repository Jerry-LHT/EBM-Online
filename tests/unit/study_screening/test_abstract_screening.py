from __future__ import annotations

from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import (
    ScreeningCriteria,
    ScreeningCriterionJudgmentValue,
    screening_decision_from_article_result,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.abstract_screening_llm.abstract_selector import (
    select_abstract_text,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.abstract_screening_llm.article_screener import (
    AbstractStudyArticleScreener,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.abstract_screening_llm.criteria_planner import (
    AbstractScreeningCriteriaPlanner,
)


def _article(*, include_abstract: bool = True) -> CleanedArticle:
    sections = [
        ArticleSection(
            section_id="abstract",
            title="Abstract",
            text="Adults with hypertension were randomized to exercise or usual care.",
        ),
        ArticleSection(
            section_id="methods",
            title="Methods",
            text="FULL-TEXT-ONLY allocation concealment detail.",
        ),
        ArticleSection(
            section_id="results",
            title="Results",
            text="FULL-TEXT-ONLY numerical result.",
        ),
    ]
    if not include_abstract:
        sections = sections[1:]
    return CleanedArticle(
        study_id="study-1",
        metadata=ArticleMetadata(
            title="Exercise for hypertension",
            publication_year="2024",
        ),
        xml_content=ArticleXmlContent(sections=sections),
    )


def test_abstract_selector_does_not_fall_back_to_full_text() -> None:
    assert select_abstract_text(_article()) == (
        "Adults with hypertension were randomized to exercise or usual care."
    )
    assert select_abstract_text(_article(include_abstract=False)) is None


def test_abstract_criteria_planner_uses_abstract_stage_contract() -> None:
    captured: dict[str, str] = {}

    def fake_llm(**kwargs):
        captured["system"] = kwargs["system"]
        captured["prompt"] = kwargs["prompt"]
        captured["schema"] = kwargs["json_schema"]
        return {
            "inclusion_criteria": ["Adults with hypertension receiving exercise."],
            "exclusion_criteria": ["The record is a review or protocol."],
            "rationale": "High-recall title-and-abstract criteria.",
        }

    planner = AbstractScreeningCriteriaPlanner(
        config={"temperature": 0},
        llm_caller=fake_llm,
    )
    result = planner.run(
        question_text="Does exercise reduce blood pressure in adults with hypertension?",
        question_pico=QuestionPICO(
            P=["Adults with hypertension"],
            I=["Exercise"],
            C=["Usual care"],
            O=["Blood pressure"],
        ),
        constraints=WorkflowConstraints(study_design="RCT"),
    )

    assert result.inclusion_criteria == ["Adults with hypertension receiving exercise."]
    assert "title-and-abstract" in captured["system"]
    assert "final binary decision" in captured["prompt"]
    assert captured["schema"]["additionalProperties"] is False


def test_abstract_screener_sends_only_title_year_and_abstract_to_llm() -> None:
    captured: dict[str, str] = {}

    def fake_llm(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        captured["schema"] = kwargs["json_schema"]
        return {
            "criterion_judgments": {
                "inc_1": {
                    "judgment": "yes",
                    "reason": "The abstract describes eligible adults and exercise.",
                    "evidence_spans": ["Adults with hypertension were randomized to exercise"],
                }
            },
            "overall_note": "Potentially eligible from the abstract.",
        }

    screener = AbstractStudyArticleScreener(
        config={"temperature": 0},
        llm_caller=fake_llm,
    )
    result = screener.run(
        criteria=ScreeningCriteria(
            inclusion_criteria=["Adults with hypertension receiving exercise."],
        ),
        article=_article(),
    )

    assert "Adults with hypertension were randomized" in captured["prompt"]
    assert "FULL-TEXT-ONLY" not in captured["prompt"]
    assert captured["schema"]["additionalProperties"] is False
    assert result.criterion_judgments[0].source_spans[0].source_id == "abstract"


def test_missing_abstract_skips_llm_and_is_excluded_from_final_screening() -> None:
    calls: list[None] = []
    screener = AbstractStudyArticleScreener(
        llm_caller=lambda **_: calls.append(None),
    )
    result = screener.run(
        criteria=ScreeningCriteria(
            inclusion_criteria=["Adults with hypertension."],
            exclusion_criteria=["Protocol-only report."],
        ),
        article=_article(include_abstract=False),
    )
    decision = screening_decision_from_article_result(
        study_id="study-1",
        result=result,
    )

    assert calls == []
    assert [judgment.judgment for judgment in result.criterion_judgments] == [
        ScreeningCriterionJudgmentValue.NO,
        ScreeningCriterionJudgmentValue.NO,
    ]
    assert decision.decision == "exclude"
    assert "does not provide an abstract" in decision.rationale
