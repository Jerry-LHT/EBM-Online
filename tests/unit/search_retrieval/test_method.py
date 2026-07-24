from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.domain.article import SearchSourceResult
from ebm_backend.online_pipeline.domain.article import FullTextAvailabilityStatus
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.search import SearchQueryConcept, SearchQueryPlan
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.method import Method
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.models import (
    PubMedArticleMetadata,
    PubMedSearchResult,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.service import SearchRetrievalService
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.errors import (
    SearchRetrievalStageError,
)


@dataclass(frozen=True)
class _FakePubMedClient:
    def search(self, *, query: str, max_candidates: int) -> PubMedSearchResult:
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


@dataclass(frozen=True)
class _FakeConceptMethod:
    name: str
    calls: list[str]

    def run(self, *, concepts):
        self.calls.append(self.name)
        return concepts

def test_method_returns_cleaned_articles_in_pubmed_rank_order() -> None:
    calls: list[str] = []
    method = Method(
        service=SearchRetrievalService(
            pubmed_client=_FakePubMedClient(),
            pmc_client=_FakePmcClient(),
        ),
        mesh_mapping_method=_FakeConceptMethod(name="mesh", calls=calls),  # type: ignore[arg-type]
        textword_expansion_method=_FakeConceptMethod(name="textword", calls=calls),  # type: ignore[arg-type]
    )

    result = method.run(
        query_plan=SearchQueryPlan(
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
        config=ModuleRunConfig(max_results_per_source=3),
    )

    assert '"depression"[Title/Abstract]' in result.search_query
    assert '"ssri"[Title/Abstract]' in result.search_query
    assert result.query_used == "translated query"
    assert result.total_hits == 3
    assert result.returned_count == 2
    assert [article.metadata.pmc_id for article in result.articles] == ["PMC100", "PMC300"]
    assert [article.source.retrieval_rank for article in result.articles] == [1, 3]
    assert [warning.code for warning in result.warnings] == ["pmcid_missing"]
    assert calls == ["mesh", "mesh", "textword"]


class _BatchPubMedClient:
    def __init__(self) -> None:
        self.search_limit = None
        self.metadata_batches: list[list[str]] = []

    def search(self, *, query: str, max_candidates: int) -> PubMedSearchResult:
        self.search_limit = max_candidates
        return PubMedSearchResult(
            total_hits=1000,
            pmids=[str(value) for value in range(1, 31)],
            query_translation=query,
        )

    def fetch_metadata(self, *, pmids: list[str]) -> dict[str, PubMedArticleMetadata]:
        self.metadata_batches.append(list(pmids))
        return {
            pmid: PubMedArticleMetadata(pmid=pmid, title=f"Article {pmid}")
            for pmid in pmids
        }


class _BatchPmcClient:
    def __init__(self) -> None:
        self.id_batches: list[list[str]] = []
        self.xml_batches: list[list[str]] = []

    def resolve_pmcids(self, *, pmids: list[str]) -> dict[str, str]:
        self.id_batches.append(list(pmids))
        return {
            pmid: f"PMC{pmid}"
            for pmid in pmids
            if pmid in {"2", "5", "21"}
        }

    def fetch_full_text_xml(self, *, pmcids: list[str]) -> dict[str, str]:
        self.xml_batches.append(list(pmcids))
        return {
            pmcid: (
                "<article><front><article-meta>"
                f'<article-id pub-id-type="pmcid">{pmcid}</article-id>'
                "</article-meta></front></article>"
            )
            for pmcid in pmcids
        }


def test_service_scans_bounded_candidates_in_batches_until_result_limit() -> None:
    pubmed = _BatchPubMedClient()
    pmc = _BatchPmcClient()
    service = SearchRetrievalService(pubmed_client=pubmed, pmc_client=pmc)  # type: ignore[arg-type]

    result = service.run(
        query_plan=SearchQueryPlan(
            concepts=[
                SearchQueryConcept(
                    slot="P",
                    source_text="depression",
                    normalized_concept="depression",
                    base_text_terms=["depression"],
                )
            ]
        ),
        config=ModuleRunConfig(
            max_candidates_per_source=30,
            max_results_per_source=3,
        ),
    )

    assert pubmed.search_limit == 30
    assert [len(batch) for batch in pubmed.metadata_batches] == [30]
    assert all(len(batch) <= 5 for batch in pmc.xml_batches)
    assert [article.source.retrieval_rank for article in result.articles] == [2, 5, 21]
    assert result.returned_count == 3
    assert result.retrieved_record_count == 30
    assert len(result.citations) == 30


class _FivePubMedClient:
    def __init__(self) -> None:
        self.metadata_pmids: list[str] = []

    def search(self, *, query: str, max_candidates: int | None) -> PubMedSearchResult:
        return PubMedSearchResult(total_hits=5, pmids=["1", "2", "3", "4", "5"])

    def fetch_metadata(self, *, pmids: list[str]) -> dict[str, PubMedArticleMetadata]:
        self.metadata_pmids.extend(pmids)
        return {
            pmid: PubMedArticleMetadata(pmid=pmid, title=f"Article {pmid}")
            for pmid in pmids
        }


class _FivePmcClient:
    def resolve_pmcids(self, *, pmids: list[str]) -> dict[str, str]:
        return {pmid: f"PMC{pmid}" for pmid in pmids}

    def fetch_full_text_xml(self, *, pmcids: list[str]) -> dict[str, str]:
        return {
            pmcid: f"<article><front><article-meta><article-id pub-id-type='pmcid'>{pmcid}</article-id></article-meta></front></article>"
            for pmcid in pmcids
        }


def test_service_retains_inventory_after_full_text_processing_limit() -> None:
    pubmed = _FivePubMedClient()
    result = SearchRetrievalService(
        pubmed_client=pubmed,  # type: ignore[arg-type]
        pmc_client=_FivePmcClient(),  # type: ignore[arg-type]
    ).run(
        query_plan=SearchQueryPlan(
            concepts=[
                SearchQueryConcept(
                    slot="P",
                    source_text="depression",
                    normalized_concept="depression",
                    base_text_terms=["depression"],
                )
            ]
        ),
        config=ModuleRunConfig(
            max_candidates_per_source=None,
            max_results_per_source=2,
        ),
    )

    assert pubmed.metadata_pmids == ["1", "2", "3", "4", "5"]
    assert result.retrieved_record_count == 5
    assert result.returned_count == 2
    assert result.remaining_full_text_count == 3
    assert [row.full_text_status for row in result.citations] == [
        FullTextAvailabilityStatus.AVAILABLE,
        FullTextAvailabilityStatus.AVAILABLE,
        FullTextAvailabilityStatus.NOT_PROCESSED,
        FullTextAvailabilityStatus.NOT_PROCESSED,
        FullTextAvailabilityStatus.NOT_PROCESSED,
    ]


class _FailingPopulationMesh:
    def run(self, *, concepts):
        if concepts[0].slot == "P":
            raise SearchRetrievalStageError(stage="mesh_lookup", attempts=2)
        return concepts


class _CapturingService:
    def __init__(self) -> None:
        self.query_plan = None
        self.warnings = None

    def run(self, *, query_plan, config, warnings):
        self.query_plan = query_plan
        self.warnings = warnings
        return SearchSourceResult(
            source_name="pubmed",
            search_query="query",
            query_used="query",
            total_hits=0,
            returned_count=0,
            warnings=warnings,
        )


def test_method_degrades_only_failed_mesh_concept_to_base_text() -> None:
    service = _CapturingService()
    method = Method(
        service=service,  # type: ignore[arg-type]
        mesh_mapping_method=_FailingPopulationMesh(),  # type: ignore[arg-type]
        textword_expansion_method=None,
    )

    result = method.run(
        query_plan=SearchQueryPlan(
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
            ]
        ),
        config=ModuleRunConfig(),
    )

    assert service.query_plan.concepts[0].base_text_terms == ["depression"]
    assert [warning.code for warning in result.warnings] == ["mesh_enrichment_failed"]
    assert result.warnings[0].concept_slot == "P"
    assert result.warnings[0].attempts == 2
