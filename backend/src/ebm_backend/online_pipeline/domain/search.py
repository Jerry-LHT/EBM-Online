"""Search strategy contracts for online retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchMeshHeading:
    descriptor_ui: str
    heading: str
    explode: bool = True


@dataclass(frozen=True)
class SearchQueryConcept:
    slot: str
    source_text: str
    normalized_concept: str
    base_text_terms: list[str] = field(default_factory=list)
    expanded_text_terms: list[str] = field(default_factory=list)
    mesh_terms: list[SearchMeshHeading] = field(default_factory=list)
    mesh_entry_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchQueryPlan:
    concepts: list[SearchQueryConcept] = field(default_factory=list)
