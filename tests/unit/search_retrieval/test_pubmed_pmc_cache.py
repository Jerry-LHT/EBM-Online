from __future__ import annotations

from pathlib import Path

from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.search import SearchQueryConcept, SearchQueryPlan
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.cache import (
    PubMedPmcFileCache,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.models import (
    PubMedArticleMetadata,
    PubMedSearchResult,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.service import (
    SearchRetrievalService,
)


class _PubMed:
    def __init__(self) -> None:
        self.search_calls = 0
        self.metadata_calls = 0

    def search(self, *, query: str, max_candidates: int) -> PubMedSearchResult:
        self.search_calls += 1
        order = ["101", "202"] if self.search_calls == 1 else ["202", "101"]
        return PubMedSearchResult(total_hits=2, pmids=order, query_translation=query)

    def fetch_metadata(self, *, pmids: list[str]) -> dict[str, PubMedArticleMetadata]:
        self.metadata_calls += 1
        return {
            pmid: PubMedArticleMetadata(pmid=pmid, title=f"Trial {pmid}")
            for pmid in pmids
        }


class _Pmc:
    def __init__(self) -> None:
        self.resolve_calls = 0
        self.xml_calls = 0

    def resolve_pmcids(self, *, pmids: list[str]) -> dict[str, str]:
        self.resolve_calls += 1
        return {pmid: f"PMC{pmid}" for pmid in pmids}

    def fetch_full_text_xml(self, *, pmcids: list[str]) -> dict[str, str]:
        self.xml_calls += 1
        return {
            pmcid: (
                "<article><front><article-meta>"
                f'<article-id pub-id-type="pmcid">{pmcid}</article-id>'
                f"<abstract><p>Abstract {pmcid}.</p></abstract>"
                "</article-meta></front></article>"
            )
            for pmcid in pmcids
        }


def _query_plan() -> SearchQueryPlan:
    return SearchQueryPlan(
        concepts=[
            SearchQueryConcept(
                slot="P",
                source_text="adults",
                normalized_concept="adults",
                base_text_terms=["adults"],
            )
        ]
    )


def test_retrieval_cache_skips_repeated_provider_fetches_but_not_search(
    tmp_path: Path,
) -> None:
    pubmed = _PubMed()
    pmc = _Pmc()
    service = SearchRetrievalService(
        pubmed_client=pubmed,  # type: ignore[arg-type]
        pmc_client=pmc,  # type: ignore[arg-type]
        cache=PubMedPmcFileCache(tmp_path / "cache"),
    )
    config = ModuleRunConfig(max_candidates_per_source=2, max_results_per_source=2)

    first = service.run(query_plan=_query_plan(), config=config)
    second = service.run(query_plan=_query_plan(), config=config)

    assert pubmed.search_calls == 2
    assert pubmed.metadata_calls == 1
    assert pmc.resolve_calls == 1
    assert pmc.xml_calls == 1
    assert [item.metadata.pmid for item in first.articles] == ["101", "202"]
    assert [item.metadata.pmid for item in second.articles] == ["202", "101"]
    assert [item.source.retrieval_rank for item in second.articles] == [1, 2]
    assert second.warnings == []


def test_cleaned_article_key_changes_with_source_or_metadata(tmp_path: Path) -> None:
    cache = PubMedPmcFileCache(tmp_path / "cache")
    metadata = PubMedArticleMetadata(pmid="101", title="Trial")

    base = cache.cleaned_article_key(xml_text="<article />", metadata=metadata)
    changed_xml = cache.cleaned_article_key(
        xml_text="<article><body /></article>",
        metadata=metadata,
    )
    changed_metadata = cache.cleaned_article_key(
        xml_text="<article />",
        metadata=PubMedArticleMetadata(pmid="101", title="Updated trial"),
    )

    assert len({base, changed_xml, changed_metadata}) == 3


def test_zero_ttl_forces_provider_refresh(tmp_path: Path) -> None:
    pubmed = _PubMed()
    pmc = _Pmc()
    service = SearchRetrievalService(
        pubmed_client=pubmed,  # type: ignore[arg-type]
        pmc_client=pmc,  # type: ignore[arg-type]
        cache=PubMedPmcFileCache(tmp_path / "cache", ttl_seconds=0),
    )
    config = ModuleRunConfig(max_candidates_per_source=2, max_results_per_source=2)

    service.run(query_plan=_query_plan(), config=config)
    service.run(query_plan=_query_plan(), config=config)

    assert pubmed.metadata_calls == 2
    assert pmc.resolve_calls == 2
    assert pmc.xml_calls == 2
