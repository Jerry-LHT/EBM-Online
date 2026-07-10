from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.search import SearchQueryConcept, SearchQueryPlan
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.method import Method
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.models import (
    PubMedArticleMetadata,
    PubMedSearchResult,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.service import SearchRetrievalService


@dataclass(frozen=True)
class _FakePubMedClient:
    def search(self, *, query: str, max_results: int) -> PubMedSearchResult:
        return PubMedSearchResult(total_hits=3, pmids=["100", "200", "300"], query_translation="translated query")

    def fetch_metadata(self, *, pmids: list[str]) -> dict[str, PubMedArticleMetadata]:
        return {
            "100": PubMedArticleMetadata(pmid="100", title="Article 100", publication_year="2020"),
            "200": PubMedArticleMetadata(pmid="200", title="Article 200", publication_year="2021"),
            "300": PubMedArticleMetadata(pmid="300", title="Article 300", publication_year="2022"),
        }


@dataclass(frozen=True)
class _FakePmcClient:
    def resolve_pmcids(self, *, pmids: list[str]) -> dict[str, str]:
        return {"100": "PMC100", "300": "PMC300"}

    def fetch_full_text_xml(self, *, pmcids: list[str]) -> dict[str, str]:
        return {
            "PMC100": '<?xml version="1.0"?><pmc-articleset><article><front><article-meta><article-id pub-id-type="pmcid">PMC100</article-id><abstract><p>Abstract A.</p></abstract></article-meta></front></article></pmc-articleset>',
            "PMC300": '<?xml version="1.0"?><pmc-articleset><article><front><article-meta><article-id pub-id-type="pmcid">PMC300</article-id><abstract><p>Abstract C.</p></abstract></article-meta></front></article></pmc-articleset>',
        }

def test_method_returns_cleaned_articles_in_pubmed_rank_order() -> None:
    method = Method(
        service=SearchRetrievalService(
            pubmed_client=_FakePubMedClient(),
            pmc_client=_FakePmcClient(),
        )
    )

    result = method.run(
        query_plan=SearchQueryPlan(
            search_query='("depression"[Title/Abstract]) AND (ssri[Title/Abstract])',
            concepts=[
                SearchQueryConcept(
                    slot="P",
                    source_text="Adults with depression",
                    normalized_concept="depression",
                    base_text_terms=["depression"],
                ),
                SearchQueryConcept(
                    slot="I",
                    source_text="SSRI",
                    normalized_concept="ssri",
                    base_text_terms=["ssri"],
                ),
            ],
        ),
        config=ModuleRunConfig(max_results=3),
    )

    assert result.search_query == '("depression"[Title/Abstract]) AND (ssri[Title/Abstract])'
    assert result.query_used == "translated query"
    assert result.total_hits == 3
    assert result.returned_count == 2
    assert [article.metadata.pmc_id for article in result.articles] == ["PMC100", "PMC300"]
    assert [article.source.retrieval_rank for article in result.articles] == [1, 3]
