"""Use case for search and article retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ebm_backend.online_pipeline.application.ports import (
    SearchMeshMappingPort,
    SearchRetrievalPort,
    SearchTextwordExpansionPort,
)
from ebm_backend.online_pipeline.domain.article import SearchRetrievalResult
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.search import SearchQueryConcept, SearchQueryPlan, SearchRetrievalOptions


MAX_POPULATION_TERMS = 5
MAX_INTERVENTION_TERMS = 5
MAX_COMPARATOR_TERMS = 3
TRIAL_FILTER = (
    '("randomized controlled trial"[Publication Type] '
    'OR randomized[Title/Abstract] '
    'OR randomised[Title/Abstract] '
    'OR randomly[Title/Abstract] '
    'OR trial[Title])'
)
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
    retrieval_method: SearchRetrievalPort
    mesh_mapping_method: SearchMeshMappingPort | None = None
    textword_expansion_method: SearchTextwordExpansionPort | None = None

    def execute(
        self,
        *,
        question_pico: QuestionPICO,
        config: ModuleRunConfig,
        options: SearchRetrievalOptions | None = None,
    ) -> SearchRetrievalResult:
        resolved_options = options or SearchRetrievalOptions()
        concepts = _select_search_concepts(question_pico=question_pico)
        if resolved_options.mesh_method_name and self.mesh_mapping_method is not None:
            concepts = self.mesh_mapping_method.run(concepts=concepts)
        if resolved_options.textword_method_name and self.textword_expansion_method is not None:
            concepts = self.textword_expansion_method.run(concepts=concepts)
        query_plan = _assemble_search_query(
            concepts=concepts,
            constraints=config.constraints,
            mesh_method_name=resolved_options.mesh_method_name,
            textword_method_name=resolved_options.textword_method_name,
        )
        return self.retrieval_method.run(query_plan=query_plan, config=config)


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


def _assemble_search_query(
    *,
    concepts: list[SearchQueryConcept],
    constraints: WorkflowConstraints,
    mesh_method_name: str | None = None,
    textword_method_name: str | None = None,
) -> SearchQueryPlan:
    clauses = [_concept_clause(concept) for concept in concepts if _concept_terms_present(concept)]
    if not clauses:
        raise ValueError("search_retrieval could not assemble any query clauses from the selected concepts")
    if str(constraints.study_design or "").strip().upper() == "RCT":
        clauses.append(TRIAL_FILTER)
    return SearchQueryPlan(
        search_query=" AND ".join(clauses),
        concepts=concepts,
        mesh_method_name=mesh_method_name,
        textword_method_name=textword_method_name,
    )


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
    return bool(concept.base_text_terms or concept.expanded_text_terms or concept.mesh_terms)


def _concept_clause(concept: SearchQueryConcept) -> str:
    text_terms = _dedupe_text_terms(concept.base_text_terms + concept.expanded_text_terms)
    clause_terms = [
        f'"{term}"[Title/Abstract]' if " " in term or "-" in term or "/" in term else f"{term}[Title/Abstract]"
        for term in text_terms
    ]
    clause_terms.extend(
        f'"{mesh.heading}"[MeSH Terms]' if " " in mesh.heading else f"{mesh.heading}[MeSH Terms]"
        for mesh in concept.mesh_terms
    )
    return "(" + " OR ".join(clause_terms) + ")"


def _dedupe_text_terms(values: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value or "").strip())
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        results.append(normalized)
        seen.add(key)
    return results
