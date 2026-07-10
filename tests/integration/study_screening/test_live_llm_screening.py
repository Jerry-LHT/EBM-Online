from __future__ import annotations

import os

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_study_screening import (
    RunStudyScreening,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.factory import (
    build_study_screening_method,
)


RUN_LIVE_LLM_TESTS = os.getenv("RUN_LIVE_LLM_TESTS") == "1"


@pytest.mark.skipif(not RUN_LIVE_LLM_TESTS, reason="Set RUN_LIVE_LLM_TESTS=1 to run live LLM tests.")
def test_study_screening_live_llm_smoke() -> None:
    use_case = RunStudyScreening(method=build_study_screening_method(method_name="default"))
    result = use_case.execute(
        question_text="Should adults with hypertension receive aerobic exercise compared with usual care?",
        question_pico=QuestionPICO(
            P=["Adults with hypertension"],
            I=["aerobic exercise"],
            C=["usual care"],
            O=["blood pressure"],
        ),
        constraints=WorkflowConstraints(),
        articles=[
            CleanedArticle(
                study_id="pmc::smoke1",
                metadata=ArticleMetadata(
                    title="Aerobic exercise for adults with hypertension: a randomized controlled trial",
                    pmid="0000001",
                    pmc_id="PMC0000001",
                    publication_year="2024",
                ),
                xml_content=ArticleXmlContent(
                    sections=[
                        ArticleSection(section_id="s1", title="Abstract", text="Randomized trial in adults with hypertension."),
                        ArticleSection(section_id="s2", title="Methods", text="Adults with hypertension were randomized to aerobic exercise or usual care."),
                        ArticleSection(section_id="s3", title="Results", text="Blood pressure decreased after aerobic exercise."),
                    ]
                ),
            )
        ],
    )

    assert result.screening_criteria.inclusion_criteria
    assert len(result.decisions) == 1
    assert result.decisions[0].decision in {"include", "exclude"}
