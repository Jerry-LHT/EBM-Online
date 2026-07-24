"""Cleaned article contracts consumed by online workflow modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FullTextAvailabilityStatus(str, Enum):
    """Provider/runtime status, never a medical eligibility conclusion."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_PROCESSED = "not_processed"
    TECHNICAL_FAILURE = "technical_failure"


@dataclass(frozen=True)
class ArticleMetadata:
    title: str
    pmid: str | None = None
    pmc_id: str | None = None
    source_type: str | None = None
    publication_year: str | None = None
    mesh_terms: list[str] = field(default_factory=list)
    doi: str | None = None
    publication_types: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    trial_registration_ids: list[str] = field(default_factory=list)
    related_article_types: list[str] = field(default_factory=list)
    is_retracted: bool = False
    is_retraction_notice: bool = False
    is_correction: bool = False


@dataclass(frozen=True)
class ArticleSection:
    section_id: str
    title: str
    text: str


@dataclass(frozen=True)
class ArticleXmlContent:
    sections: list[ArticleSection] = field(default_factory=list)


@dataclass(frozen=True)
class ArticleTable:
    table_id: str
    caption: str
    rows: list[dict[str, str]] = field(default_factory=list)
    # Preserve the provider's original table-wrap.  Study-evidence extraction
    # intentionally lets the LLM read the source rather than a lossy parsed
    # row/column representation.
    raw_xml: str | None = None


@dataclass(frozen=True)
class ArticleSource:
    database: str
    retrieval_rank: int | None = None
    retrieval_score: float | None = None
    raw_source_url: str | None = None
    raw_record_id: str | None = None


@dataclass(frozen=True)
class CleanedArticle:
    study_id: str
    metadata: ArticleMetadata
    xml_content: ArticleXmlContent
    tables: list[ArticleTable] = field(default_factory=list)
    source: ArticleSource | None = None


@dataclass(frozen=True)
class SearchCitation:
    """Lightweight PubMed inventory row retained independently of full text."""

    pmid: str
    retrieval_rank: int
    title: str = ""
    abstract: str = ""
    pmc_id: str | None = None
    publication_year: str | None = None
    doi: str | None = None
    full_text_status: FullTextAvailabilityStatus = (
        FullTextAvailabilityStatus.NOT_PROCESSED
    )


@dataclass(frozen=True)
class SearchRetrievalWarning:
    code: str
    message: str
    stage: str | None = None
    concept_slot: str | None = None
    concept_text: str | None = None
    attempts: int | None = None
    pmid: str | None = None
    pmc_id: str | None = None


@dataclass(frozen=True)
class SearchSourceResult:
    source_name: str
    search_query: str
    query_used: str
    total_hits: int
    returned_count: int
    retrieved_record_count: int = 0
    full_text_available_count: int = 0
    remaining_full_text_count: int = 0
    truncated: bool = False
    citations: list[SearchCitation] = field(default_factory=list)
    articles: list[CleanedArticle] = field(default_factory=list)
    warnings: list[SearchRetrievalWarning] = field(default_factory=list)


@dataclass(frozen=True)
class SearchRetrievalResult:
    returned_count: int
    retrieved_record_count: int = 0
    full_text_available_count: int = 0
    remaining_full_text_count: int = 0
    truncated: bool = False
    citations: list[SearchCitation] = field(default_factory=list)
    source_results: list[SearchSourceResult] = field(default_factory=list)
    articles: list[CleanedArticle] = field(default_factory=list)
