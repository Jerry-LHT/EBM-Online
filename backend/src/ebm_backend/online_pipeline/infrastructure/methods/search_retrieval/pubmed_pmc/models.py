"""Internal models for PubMed/PMC retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PubMedSearchResult:
    total_hits: int
    pmids: list[str] = field(default_factory=list)
    query_translation: str | None = None


@dataclass(frozen=True)
class PubMedArticleMetadata:
    pmid: str
    title: str
    publication_year: str | None = None
    abstract: str = ""
    doi: str | None = None
    mesh_terms: list[str] = field(default_factory=list)
    publication_types: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    trial_registration_ids: list[str] = field(default_factory=list)
    related_article_types: list[str] = field(default_factory=list)
    is_retracted: bool = False
    is_retraction_notice: bool = False
    is_correction: bool = False
