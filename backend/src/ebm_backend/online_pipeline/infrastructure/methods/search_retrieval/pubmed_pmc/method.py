"""PubMed/PMC retrieval method."""

from __future__ import annotations

from dataclasses import dataclass, field

from ebm_backend.online_pipeline.domain.article import SearchRetrievalResult
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.search import SearchQueryPlan
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.service import SearchRetrievalService


@dataclass(frozen=True)
class Method:
    service: SearchRetrievalService = field(default_factory=SearchRetrievalService)

    def run(self, *, query_plan: SearchQueryPlan, config: ModuleRunConfig) -> SearchRetrievalResult:
        return self.service.run(query_plan=query_plan, config=config)


def build_method() -> Method:
    return Method()
