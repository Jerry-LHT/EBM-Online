from __future__ import annotations

import os

import pytest

from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.factory import (
    build_production_study_pio,
)


RUN_LIVE_LLM_TESTS = os.getenv("RUN_LIVE_LLM_TESTS") == "1"


@pytest.mark.skipif(
    not RUN_LIVE_LLM_TESTS,
    reason="Set RUN_LIVE_LLM_TESTS=1 to run live Study PICO extraction.",
)
def test_slotwise_llm_extracts_one_study() -> None:
    method = build_production_study_pio()
    article = CleanedArticle(
        study_id="study-1",
        metadata=ArticleMetadata(title="Exercise and hypertension trial"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id="methods",
                    title="Methods",
                    text=(
                        "We randomized 120 adults with hypertension to supervised aerobic "
                        "exercise three times weekly or usual care."
                    ),
                ),
                ArticleSection(
                    section_id="outcomes",
                    title="Outcomes",
                    text="Systolic blood pressure was measured at baseline and 12 weeks.",
                ),
            ]
        ),
    )

    result = method.run(
        question_pico=QuestionPICO(
            P=["adults with hypertension"],
            I=["aerobic exercise"],
            C=["usual care"],
            O=["blood pressure"],
        ),
        study_id="study-1",
        article=article,
    )

    assert result.study_id == "study-1"
    assert result.population.description
    assert result.interventions
    assert result.comparators
    assert result.outcomes
