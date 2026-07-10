"""Build textword expansions from base terms and official MeSH entry terms."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ebm_backend.online_pipeline.domain.search import SearchQueryConcept
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.shared.official_mesh_support import (
    OfficialMeshLookupClient,
    normalize_text_term,
)


MAX_EXPANDED_TERMS = 5


@dataclass(frozen=True)
class Method:
    client: OfficialMeshLookupClient = field(default_factory=OfficialMeshLookupClient)

    def run(self, *, concepts: list[SearchQueryConcept]) -> list[SearchQueryConcept]:
        expanded: list[SearchQueryConcept] = []
        for concept in concepts:
            entry_terms = concept.mesh_entry_terms
            if not entry_terms:
                descriptor = self.client.resolve(label=concept.normalized_concept)
                entry_terms = descriptor.entry_terms if descriptor is not None else []
            text_terms = _expanded_terms(base_terms=concept.base_text_terms, entry_terms=entry_terms)
            expanded.append(replace(concept, expanded_text_terms=text_terms))
        return expanded


def _expanded_terms(*, base_terms: list[str], entry_terms: list[str]) -> list[str]:
    base_keys = {normalize_text_term(term) for term in base_terms if normalize_text_term(term)}
    results: list[str] = []
    seen = set(base_keys)
    for term in entry_terms:
        normalized = normalize_text_term(term)
        if not normalized or normalized in seen:
            continue
        results.append(normalized)
        seen.add(normalized)
        if len(results) >= MAX_EXPANDED_TERMS:
            break
    return results


def build_method() -> Method:
    return Method()
