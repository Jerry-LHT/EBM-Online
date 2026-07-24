from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.application.use_cases.run_search_retrieval import RunSearchRetrieval
from ebm_backend.online_pipeline.domain.article import SearchSourceResult
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.question import QuestionPICO


@dataclass(frozen=True)
class _FakeRetrievalMethod:
    source_name: str = "source-a"
    articles: tuple[object, ...] = ()

    def run(self, *, query_plan, config):
        query = " | ".join(
            term
            for concept in query_plan.concepts
            for term in concept.base_text_terms + concept.expanded_text_terms
        )
        return SearchSourceResult(
            source_name=self.source_name,
            search_query=query,
            query_used=query,
            total_hits=0,
            returned_count=len(self.articles),
            articles=list(self.articles),  # type: ignore[arg-type]
        )


def test_run_search_retrieval_builds_source_neutral_concept_plan() -> None:
    result = RunSearchRetrieval(
        retrieval_sources=(_FakeRetrievalMethod(),),
    ).execute(
        question_pico=QuestionPICO(P=["Adults with hypertension"], I=["exercise"]),
        config=ModuleRunConfig(max_results_per_source=5),
    )

    assert "hypertension" in result.source_results[0].search_query
    assert "exercise" in result.source_results[0].search_query


def test_run_search_retrieval_aggregates_sources_in_configured_order() -> None:
    result = RunSearchRetrieval(
        retrieval_sources=(
            _FakeRetrievalMethod(source_name="source-a"),
            _FakeRetrievalMethod(source_name="source-b", articles=("article-b",)),
        )
    ).execute(
        question_pico=QuestionPICO(P=["hypertension"], I=["exercise"]),
        config=ModuleRunConfig(max_results_per_source=5),
    )

    assert [item.source_name for item in result.source_results] == [
        "source-a",
        "source-b",
    ]
    assert result.articles == ["article-b"]
    assert result.returned_count == 1
