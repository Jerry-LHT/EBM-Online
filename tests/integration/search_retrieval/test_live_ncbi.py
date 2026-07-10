from __future__ import annotations

import os

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_search_retrieval import (
    RunSearchRetrieval,
)
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.search import SearchRetrievalOptions
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.factory import (
    build_search_mesh_mapping_method,
    build_search_retrieval_method,
    build_search_textword_expansion_method,
)


RUN_LIVE_NCBI_TESTS = os.getenv("RUN_LIVE_NCBI_TESTS") == "1"


@pytest.mark.skipif(not RUN_LIVE_NCBI_TESTS, reason="Set RUN_LIVE_NCBI_TESTS=1 to run live NCBI tests.")
def test_search_retrieval_live_ncbi_smoke() -> None:
    result = RunSearchRetrieval(
        retrieval_method=build_search_retrieval_method(method_name="pubmed_pmc"),
        mesh_mapping_method=build_search_mesh_mapping_method(method_name="official"),
        textword_expansion_method=build_search_textword_expansion_method(method_name="official"),
    ).execute(
        question_pico=QuestionPICO(
            P=["Adults with hypertension"],
            I=["aerobic exercise"],
            O=["blood pressure"],
        ),
        config=ModuleRunConfig(max_results=3),
        options=SearchRetrievalOptions(
            mesh_method_name="official",
            textword_method_name="official",
        ),
    )

    assert result.search_query
    assert result.query_used
    assert result.database == "pubmed"
    assert result.total_hits >= result.returned_count
    assert result.articles
    assert all(article.metadata.pmc_id for article in result.articles)
