"""Use case for search and article retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ebm_backend.online_pipeline.application.ports import SearchRetrievalPort
from ebm_backend.online_pipeline.domain.article import SearchRetrievalResult
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.search import SearchQueryConcept, SearchQueryPlan


MAX_POPULATION_TERMS = 5
MAX_INTERVENTION_TERMS = 5
MAX_COMPARATOR_TERMS = 3
_BOILERPLATE_PREFIXES = (
    r"patients?\s+with\s+",
    r"adults?\s+with\s+",
    r"children\s+with\s+",
    r"people\s+with\s+",
    r"participants?\s+with\s+",
    r"subjects?\s+with\s+",
)


@dataclass(frozen=True)
class RunSearchRetrieval:
    retrieval_sources: tuple[SearchRetrievalPort, ...]

    def execute(
        self,
        *,
        question_pico: QuestionPICO,
        config: ModuleRunConfig,
    ) -> SearchRetrievalResult:
        if not self.retrieval_sources:
            raise ValueError("search_retrieval requires at least one retrieval source")
        concepts = _select_search_concepts(question_pico=question_pico)
        query_plan = _build_search_query_plan(concepts=concepts)
        source_results = [
            source.run(query_plan=query_plan, config=config)
            for source in self.retrieval_sources
        ]
        articles = [
            article
            for source_result in source_results
            for article in source_result.articles
        ]
        citations = [
            citation
            for source_result in source_results
            for citation in source_result.citations
        ]
        return SearchRetrievalResult(
            returned_count=len(articles),
            retrieved_record_count=sum(
                result.retrieved_record_count for result in source_results
            ),
            full_text_available_count=sum(
                result.full_text_available_count for result in source_results
            ),
            remaining_full_text_count=sum(
                result.remaining_full_text_count for result in source_results
            ),
            truncated=any(result.truncated for result in source_results),
            citations=citations,
            source_results=source_results,
            articles=articles,
        )


def _select_search_concepts(*, question_pico: QuestionPICO) -> list[SearchQueryConcept]:
    concepts: list[SearchQueryConcept] = []
    concepts.extend(_select_slot("P", question_pico.P, MAX_POPULATION_TERMS))
    interventions = _select_slot("I", question_pico.I, MAX_INTERVENTION_TERMS)
    if interventions:
        concepts.extend(interventions)
    else:
        concepts.extend(_select_slot("C", question_pico.C, MAX_COMPARATOR_TERMS))
    if not concepts:
        raise ValueError("search_retrieval requires at least one searchable P, I, or fallback C concept")
    return concepts


def _build_search_query_plan(
    *,
    concepts: list[SearchQueryConcept],
) -> SearchQueryPlan:
    if not any(_concept_terms_present(concept) for concept in concepts):
        raise ValueError("search_retrieval could not build a query plan from the selected concepts")
    return SearchQueryPlan(concepts=concepts)


def _select_slot(slot: str, values: list[str], limit: int) -> list[SearchQueryConcept]:
    concepts: list[SearchQueryConcept] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_term(value)
        if not normalized or normalized in seen:
            continue
        concepts.append(
            SearchQueryConcept(
                slot=slot,
                source_text=str(value or "").strip(),
                normalized_concept=normalized,
                base_text_terms=[normalized],
            )
        )
        seen.add(normalized)
        if len(concepts) >= limit:
            break
    return concepts


def _normalize_term(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    lowered = text.casefold()
    for pattern in _BOILERPLATE_PREFIXES:
        lowered = re.sub(rf"^{pattern}", "", lowered, flags=re.IGNORECASE)
    lowered = re.sub(r"^[^a-z0-9]+", "", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip(" .;,")
    return lowered


def _concept_terms_present(concept: SearchQueryConcept) -> bool:
    return bool(
        concept.base_text_terms
        or concept.expanded_text_terms
        or concept.mesh_terms
    )
