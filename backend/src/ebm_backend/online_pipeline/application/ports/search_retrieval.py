"""Application ports for retrieval strategy expansion and execution."""

from __future__ import annotations

from typing import Protocol

from ebm_backend.online_pipeline.domain.article import SearchSourceResult
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.search import SearchQueryPlan


class SearchRetrievalPort(Protocol):
    def run(self, *, query_plan: SearchQueryPlan, config: ModuleRunConfig) -> SearchSourceResult:
        ...
