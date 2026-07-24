"""Factories for search retrieval infrastructure methods."""

from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.method import (
    build_method as build_pubmed_pmc_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.cache import (
    PubMedPmcFileCache,
)


def build_search_retrieval_source(
    *,
    source_name: str,
    cache: PubMedPmcFileCache | None = None,
):
    if source_name != "pubmed":
        raise ValueError(f"Unknown search retrieval source '{source_name}'")
    return build_pubmed_pmc_method(cache=cache)


def build_search_retrieval_sources(
    *,
    source_names: list[str],
    cache: PubMedPmcFileCache | None = None,
):
    if not source_names:
        raise ValueError("At least one search retrieval source is required")
    if len(set(source_names)) != len(source_names):
        raise ValueError("Search retrieval source names must be unique")
    return tuple(
        build_search_retrieval_source(source_name=source_name, cache=cache)
        for source_name in source_names
    )
