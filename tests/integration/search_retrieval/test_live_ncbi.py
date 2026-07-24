from __future__ import annotations

import os

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_search_retrieval import (
    RunSearchRetrieval,
)
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.factory import (
    build_search_retrieval_source,
)


RUN_LIVE_NCBI_TESTS = os.getenv("RUN_LIVE_NCBI_TESTS") == "1"


@pytest.mark.skipif(not RUN_LIVE_NCBI_TESTS, reason="Set RUN_LIVE_NCBI_TESTS=1 to run live NCBI tests.")
def test_search_retrieval_live_ncbi_smoke() -> None:
    result = RunSearchRetrieval(
        retrieval_sources=(
            build_search_retrieval_source(source_name="pubmed"),
        ),
    ).execute(
        question_pico=QuestionPICO(
            P=["Adults with hypertension"],
            I=["aerobic exercise"],
            O=["blood pressure"],
        ),
        config=ModuleRunConfig(
            max_candidates_per_source=20,
            max_results_per_source=3,
        ),
    )

    assert len(result.source_results) == 1
    source_result = result.source_results[0]
    assert source_result.search_query
    assert source_result.query_used
    assert source_result.source_name == "pubmed"
    assert source_result.total_hits >= source_result.returned_count
    assert result.articles
    assert all(article.metadata.pmc_id for article in result.articles)
