from __future__ import annotations

import os

import pytest

from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.risk_of_bias import DEFAULT_ROB1_DOMAINS
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.factory import (
    build_production_risk_of_bias,
)


RUN_LIVE_LLM_TESTS = os.getenv("RUN_LIVE_LLM_TESTS") == "1"


@pytest.mark.skipif(
    not RUN_LIVE_LLM_TESTS,
    reason="Set RUN_LIVE_LLM_TESTS=1 to run live RoB 1 domain assessment.",
)
def test_live_method_assesses_default_domains_and_builds_overall() -> None:
    article = CleanedArticle(
        study_id="study-1",
        metadata=ArticleMetadata(title="Parallel randomized trial"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id="methods",
                    title="Methods",
                    text=(
                        "One hundred twenty adults were randomized 1:1 using a computer-generated "
                        "sequence held by an independent central service. Participants and treating "
                        "clinicians were not blinded. Outcome assessors were blinded."
                    ),
                ),
                ArticleSection(
                    section_id="results",
                    title="Results",
                    text=(
                        "All 60 participants assigned to each group were included in the primary "
                        "analysis, and no participants were lost to follow-up."
                    ),
                ),
            ]
        ),
    )

    result = build_production_risk_of_bias().assess(
        study_id="study-1",
        article=article,
    )

    assert [item.domain for item in result.domains] == DEFAULT_ROB1_DOMAINS
    assert result.overall.judgement in {"low_risk", "unclear_risk", "high_risk"}
    assert result.overall.rationale
