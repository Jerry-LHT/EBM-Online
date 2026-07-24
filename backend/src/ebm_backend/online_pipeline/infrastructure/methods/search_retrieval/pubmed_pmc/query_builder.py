"""Compile a source-neutral search plan into PubMed query syntax."""

from __future__ import annotations

import re

from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.search import SearchQueryConcept, SearchQueryPlan


TRIAL_FILTER = (
    '(("randomized controlled trial"[Publication Type] '
    'OR "controlled clinical trial"[Publication Type] '
    'OR randomized[Title/Abstract] '
    'OR randomised[Title/Abstract] '
    'OR placebo[Title/Abstract] '
    'OR "drug therapy"[Subheading] '
    'OR randomly[Title/Abstract] '
    'OR trial[Title/Abstract] '
    'OR groups[Title/Abstract]) '
    'NOT (animals[MeSH Terms] NOT humans[MeSH Terms]))'
)


def build_pubmed_query(
    *,
    query_plan: SearchQueryPlan,
    constraints: WorkflowConstraints,
) -> str:
    grouped_clauses: dict[str, list[str]] = {}
    for concept in query_plan.concepts:
        if not _concept_terms_present(concept):
            continue
        clause = _concept_clause(concept)
        if clause:
            grouped_clauses.setdefault(concept.slot, []).append(clause)
    clauses = [
        "(" + " OR ".join(group) + ")"
        for group in grouped_clauses.values()
        if group
    ]
    if not clauses:
        raise ValueError("pubmed_pmc could not compile any query clauses")
    if str(constraints.study_design or "").strip().upper() == "RCT":
        clauses.append(TRIAL_FILTER)
    publication_date_clause = _publication_date_clause(
        constraints.publication_year_range
    )
    if publication_date_clause:
        clauses.append(publication_date_clause)
    return " AND ".join(clauses)


def _publication_date_clause(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.fullmatch(r"(\d{4})\s*-\s*(\d{4})", text)
    if match is None:
        raise ValueError("publication_year_range must use YYYY-YYYY format")
    start, end = (int(item) for item in match.groups())
    if start > end:
        raise ValueError(
            "publication_year_range start must be less than or equal to end"
        )
    return f'("{start}"[Date - Publication] : "{end}"[Date - Publication])'


def _concept_terms_present(concept: SearchQueryConcept) -> bool:
    return bool(concept.base_text_terms or concept.expanded_text_terms or concept.mesh_terms)


def _concept_clause(concept: SearchQueryConcept) -> str:
    text_terms = _dedupe_text_terms(
        concept.base_text_terms + concept.expanded_text_terms
    )
    clause_terms: list[str] = []
    for term in text_terms:
        literal = _pubmed_literal(term)
        if literal:
            clause_terms.append(f'"{literal}"[Title/Abstract]')
    for mesh in concept.mesh_terms:
        literal = _pubmed_literal(mesh.heading)
        if literal:
            clause_terms.append(f'"{literal}"[MeSH Terms]')
    return "(" + " OR ".join(clause_terms) + ")" if clause_terms else ""


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


def _pubmed_literal(value: str) -> str:
    text = re.sub(r'["\[\]{}()]', " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip(" .;,")
