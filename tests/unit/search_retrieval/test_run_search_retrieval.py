from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.application.use_cases.run_search_retrieval import RunSearchRetrieval
from ebm_backend.online_pipeline.domain.article import SearchRetrievalResult
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.search import SearchRetrievalOptions


@dataclass(frozen=True)
class _FakeMeshMethod:
    def run(self, *, concepts):
        return concepts


@dataclass(frozen=True)
class _FakeTextwordMethod:
    def run(self, *, concepts):
        updated = []
        for concept in concepts:
            updated.append(type(concept)(**{**concept.__dict__, "expanded_text_terms": ["high blood pressure"] if concept.normalized_concept == "hypertension" else []}))
        return updated


@dataclass(frozen=True)
class _FakeRetrievalMethod:
    def run(self, *, query_plan, config):
        return SearchRetrievalResult(
            search_query=query_plan.search_query,
            query_used=query_plan.search_query,
            database="pubmed",
            total_hits=0,
            returned_count=0,
            articles=[],
        )


def test_run_search_retrieval_orchestrates_optional_methods() -> None:
    result = RunSearchRetrieval(
        retrieval_method=_FakeRetrievalMethod(),
        mesh_mapping_method=_FakeMeshMethod(),
        textword_expansion_method=_FakeTextwordMethod(),
    ).execute(
        question_pico=QuestionPICO(P=["Adults with hypertension"], I=["exercise"]),
        config=ModuleRunConfig(max_results=5),
        options=SearchRetrievalOptions(
            mesh_method_name="official",
            textword_method_name="official",
        ),
    )

    assert "high blood pressure" in result.search_query
    assert "exercise[Title/Abstract]" in result.search_query
