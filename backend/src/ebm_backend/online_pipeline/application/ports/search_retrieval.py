"""Application ports for retrieval strategy expansion and execution."""

from __future__ import annotations

from typing import Protocol

from ebm_backend.online_pipeline.domain.article import SearchRetrievalResult
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.search import SearchQueryConcept, SearchQueryPlan


class SearchRetrievalPort(Protocol):
    def run(self, *, query_plan: SearchQueryPlan, config: ModuleRunConfig) -> SearchRetrievalResult:
        ...


class SearchMeshMappingPort(Protocol):
    def run(self, *, concepts: list[SearchQueryConcept]) -> list[SearchQueryConcept]:
        ...


class SearchTextwordExpansionPort(Protocol):
    def run(self, *, concepts: list[SearchQueryConcept]) -> list[SearchQueryConcept]:
        ...
