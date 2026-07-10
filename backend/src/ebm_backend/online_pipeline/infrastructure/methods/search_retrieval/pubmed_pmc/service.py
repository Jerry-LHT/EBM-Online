"""Search retrieval orchestration for PubMed and PMC."""

from __future__ import annotations

from dataclasses import dataclass, field

from ebm_backend.online_pipeline.domain.article import SearchRetrievalResult
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.search import SearchQueryPlan
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pmc_client import PmcClient
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pubmed_client import PubMedClient
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.xml_cleaner import clean_article_xml


@dataclass(frozen=True)
class SearchRetrievalService:
    pubmed_client: PubMedClient = field(default_factory=PubMedClient)
    pmc_client: PmcClient = field(default_factory=PmcClient)

    def run(self, *, query_plan: SearchQueryPlan, config: ModuleRunConfig) -> SearchRetrievalResult:
        query = query_plan.search_query.strip()
        if not query:
            raise ValueError("search_query is required")

        search_result = self.pubmed_client.search(query=query, max_results=config.max_results)
        metadata_by_pmid = self.pubmed_client.fetch_metadata(pmids=search_result.pmids)
        pmcid_by_pmid = self.pmc_client.resolve_pmcids(pmids=search_result.pmids)
        xml_by_pmcid = self.pmc_client.fetch_full_text_xml(pmcids=list(pmcid_by_pmid.values()))

        articles = []
        for rank, pmid in enumerate(search_result.pmids, start=1):
            metadata = metadata_by_pmid.get(pmid)
            if metadata is None:
                continue
            pmcid = pmcid_by_pmid.get(pmid)
            if not pmcid:
                continue
            xml_text = xml_by_pmcid.get(pmcid)
            if not xml_text:
                continue
            articles.append(
                clean_article_xml(
                    xml_text=xml_text,
                    metadata=metadata,
                    pmcid=pmcid,
                    retrieval_rank=rank,
                )
            )

        return SearchRetrievalResult(
            search_query=query,
            query_used=search_result.query_translation or query,
            database="pubmed",
            total_hits=search_result.total_hits,
            returned_count=len(articles),
            articles=articles,
        )
