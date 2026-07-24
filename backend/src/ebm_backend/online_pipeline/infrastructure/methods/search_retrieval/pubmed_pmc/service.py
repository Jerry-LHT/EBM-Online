"""Search retrieval orchestration for PubMed and PMC."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from xml.etree import ElementTree

from ebm_backend.online_pipeline.domain.article import (
    ArticleSource,
    CleanedArticle,
    FullTextAvailabilityStatus,
    SearchCitation,
    SearchRetrievalWarning,
    SearchSourceResult,
)
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.search import SearchQueryPlan
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.cache import (
    PubMedPmcFileCache,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.models import (
    PubMedArticleMetadata,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pmc_client import PmcClient
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pubmed_client import PubMedClient
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.query_builder import build_pubmed_query
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.xml_cleaner import clean_article_xml


PROVIDER_BATCH_SIZE = 100
FULL_TEXT_BATCH_SIZE = 5


@dataclass(frozen=True)
class SearchRetrievalService:
    pubmed_client: PubMedClient = field(default_factory=PubMedClient)
    pmc_client: PmcClient = field(default_factory=PmcClient)
    cache: PubMedPmcFileCache | None = None

    def run(
        self,
        *,
        query_plan: SearchQueryPlan,
        config: ModuleRunConfig,
        warnings: list[SearchRetrievalWarning] | None = None,
    ) -> SearchSourceResult:
        query = build_pubmed_query(
            query_plan=query_plan,
            constraints=config.constraints,
        )

        search_result = self.pubmed_client.search(
            query=query,
            max_candidates=config.max_candidates_per_source,
        )
        result_warnings = list(warnings or [])
        articles: list[CleanedArticle] = []
        ranked_pmids = list(enumerate(search_result.pmids, start=1))
        metadata_by_pmid: dict[str, PubMedArticleMetadata] = {}
        pmcid_by_pmid: dict[str, str] = {}
        for ranked_batch in _chunks(ranked_pmids, PROVIDER_BATCH_SIZE):
            batch_pmids = [pmid for _, pmid in ranked_batch]
            batch_metadata = _metadata_with_cache(
                cache=self.cache,
                client=self.pubmed_client,
                pmids=batch_pmids,
                warnings=result_warnings,
            )
            metadata_by_pmid.update(batch_metadata)
            for pmid in batch_pmids:
                if pmid not in batch_metadata:
                    result_warnings.append(
                        SearchRetrievalWarning(
                            code="pubmed_metadata_missing",
                            message="PubMed returned no metadata for a candidate PMID.",
                            stage="pubmed_metadata",
                            pmid=pmid,
                        )
                    )

            metadata_pmids = [pmid for pmid in batch_pmids if pmid in batch_metadata]
            batch_pmcids = _pmcids_with_cache(
                cache=self.cache,
                client=self.pmc_client,
                pmids=metadata_pmids,
                warnings=result_warnings,
            )
            pmcid_by_pmid.update(batch_pmcids)
            for pmid in metadata_pmids:
                if pmid not in batch_pmcids:
                    result_warnings.append(
                        SearchRetrievalWarning(
                            code="pmcid_missing",
                            message="No PMCID was available for a PubMed candidate.",
                            stage="pmcid_resolution",
                            pmid=pmid,
                        )
                    )


        full_text_status = {
            pmid: (
                FullTextAvailabilityStatus.NOT_PROCESSED
                if pmid in pmcid_by_pmid
                else FullTextAvailabilityStatus.UNAVAILABLE
            )
            for _, pmid in ranked_pmids
        }
        ranked_pmc_candidates = [
            (rank, pmid, pmcid_by_pmid[pmid])
            for rank, pmid in ranked_pmids
            if pmid in metadata_by_pmid and pmid in pmcid_by_pmid
        ]
        cursor = 0
        while (
            cursor < len(ranked_pmc_candidates)
            and len(articles) < config.max_results_per_source
        ):
            remaining_slots = config.max_results_per_source - len(articles)
            batch_size = min(FULL_TEXT_BATCH_SIZE, remaining_slots)
            full_text_batch = ranked_pmc_candidates[cursor : cursor + batch_size]
            cursor += len(full_text_batch)
            pmcids = _dedupe([pmcid for _, _, pmcid in full_text_batch])
            xml_by_pmcid = _xml_with_cache(
                cache=self.cache,
                client=self.pmc_client,
                pmcids=pmcids,
                warnings=result_warnings,
            )
            for rank, pmid, pmcid in full_text_batch:
                xml_text = xml_by_pmcid.get(pmcid)
                if not xml_text:
                    full_text_status[pmid] = FullTextAvailabilityStatus.UNAVAILABLE
                    result_warnings.append(
                        SearchRetrievalWarning(
                            code="pmc_full_text_missing",
                            message="PMC returned no full-text XML for a resolved PMCID.",
                            stage="pmc_full_text",
                            pmid=pmid,
                            pmc_id=pmcid,
                        )
                    )
                    continue
                try:
                    article = _cleaned_article_with_cache(
                        cache=self.cache,
                        xml_text=xml_text,
                        metadata=metadata_by_pmid[pmid],
                        pmcid=pmcid,
                        retrieval_rank=rank,
                        warnings=result_warnings,
                    )
                except (ElementTree.ParseError, ValueError) as exc:
                    full_text_status[pmid] = (
                        FullTextAvailabilityStatus.TECHNICAL_FAILURE
                    )
                    result_warnings.append(
                        SearchRetrievalWarning(
                            code="article_xml_cleaning_failed",
                            message=f"Article XML could not be cleaned: {type(exc).__name__}.",
                            stage="article_xml_cleaning",
                            pmid=pmid,
                            pmc_id=pmcid,
                        )
                    )
                    continue
                articles.append(article)
                full_text_status[pmid] = FullTextAvailabilityStatus.AVAILABLE

        citations = [
            _citation(
                pmid=pmid,
                rank=rank,
                metadata=metadata_by_pmid.get(pmid),
                pmcid=pmcid_by_pmid.get(pmid),
                status=full_text_status[pmid],
            )
            for rank, pmid in ranked_pmids
        ]
        remaining_full_text_count = sum(
            citation.full_text_status == FullTextAvailabilityStatus.NOT_PROCESSED
            for citation in citations
        )

        return SearchSourceResult(
            source_name="pubmed",
            search_query=query,
            query_used=search_result.query_translation or query,
            total_hits=search_result.total_hits,
            returned_count=len(articles),
            retrieved_record_count=len(ranked_pmids),
            full_text_available_count=len(articles),
            remaining_full_text_count=remaining_full_text_count,
            truncated=(
                search_result.total_hits > len(ranked_pmids)
                or remaining_full_text_count > 0
            ),
            citations=citations,
            articles=articles,
            warnings=result_warnings,
        )


def _citation(
    *,
    pmid: str,
    rank: int,
    metadata: PubMedArticleMetadata | None,
    pmcid: str | None,
    status: FullTextAvailabilityStatus,
) -> SearchCitation:
    return SearchCitation(
        pmid=pmid,
        retrieval_rank=rank,
        title=metadata.title if metadata is not None else "",
        abstract=metadata.abstract if metadata is not None else "",
        pmc_id=pmcid,
        publication_year=(metadata.publication_year if metadata is not None else None),
        doi=metadata.doi if metadata is not None else None,
        full_text_status=status,
    )


def _chunks(values: list, size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _dedupe(values: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        results.append(value)
        seen.add(value)
    return results


def _metadata_with_cache(
    *,
    cache: PubMedPmcFileCache | None,
    client: PubMedClient,
    pmids: list[str],
    warnings: list[SearchRetrievalWarning],
) -> dict[str, PubMedArticleMetadata]:
    cached: dict[str, PubMedArticleMetadata] = {}
    missing: list[str] = []
    for pmid in pmids:
        value = _cache_read(
            cache=cache,
            action=(
                (lambda pmid=pmid: cache.get_metadata(pmid=pmid))
                if cache is not None
                else None
            ),
            warnings=warnings,
            stage="pubmed_metadata_cache_read",
            pmid=pmid,
        )
        if value is None:
            missing.append(pmid)
        else:
            cached[pmid] = value
    fetched = client.fetch_metadata(pmids=missing) if missing else {}
    if cache is not None:
        for metadata in fetched.values():
            _cache_write(
                action=lambda metadata=metadata: cache.put_metadata(
                    metadata=metadata
                ),
                warnings=warnings,
                stage="pubmed_metadata_cache_write",
                pmid=metadata.pmid,
            )
    return {**cached, **fetched}


def _pmcids_with_cache(
    *,
    cache: PubMedPmcFileCache | None,
    client: PmcClient,
    pmids: list[str],
    warnings: list[SearchRetrievalWarning],
) -> dict[str, str]:
    cached: dict[str, str] = {}
    missing: list[str] = []
    for pmid in pmids:
        value = _cache_read(
            cache=cache,
            action=(
                (lambda pmid=pmid: cache.get_pmcid(pmid=pmid))
                if cache is not None
                else None
            ),
            warnings=warnings,
            stage="pmcid_cache_read",
            pmid=pmid,
        )
        if value is None:
            missing.append(pmid)
        else:
            cached[pmid] = value
    fetched = client.resolve_pmcids(pmids=missing) if missing else {}
    if cache is not None:
        for pmid, pmcid in fetched.items():
            _cache_write(
                action=lambda pmid=pmid, pmcid=pmcid: cache.put_pmcid(
                    pmid=pmid,
                    pmcid=pmcid,
                ),
                warnings=warnings,
                stage="pmcid_cache_write",
                pmid=pmid,
                pmc_id=pmcid,
            )
    return {**cached, **fetched}


def _xml_with_cache(
    *,
    cache: PubMedPmcFileCache | None,
    client: PmcClient,
    pmcids: list[str],
    warnings: list[SearchRetrievalWarning],
) -> dict[str, str]:
    cached: dict[str, str] = {}
    missing: list[str] = []
    for pmcid in pmcids:
        value = _cache_read(
            cache=cache,
            action=(
                (lambda pmcid=pmcid: cache.get_xml(pmcid=pmcid))
                if cache is not None
                else None
            ),
            warnings=warnings,
            stage="pmc_full_text_cache_read",
            pmc_id=pmcid,
        )
        if value is None:
            missing.append(pmcid)
        else:
            cached[pmcid] = value
    fetched = client.fetch_full_text_xml(pmcids=missing) if missing else {}
    if cache is not None:
        for pmcid, xml_text in fetched.items():
            _cache_write(
                action=lambda pmcid=pmcid, xml_text=xml_text: cache.put_xml(
                    pmcid=pmcid,
                    xml_text=xml_text,
                ),
                warnings=warnings,
                stage="pmc_full_text_cache_write",
                pmc_id=pmcid,
            )
    return {**cached, **fetched}


def _cleaned_article_with_cache(
    *,
    cache: PubMedPmcFileCache | None,
    xml_text: str,
    metadata: PubMedArticleMetadata,
    pmcid: str,
    retrieval_rank: int,
    warnings: list[SearchRetrievalWarning],
) -> CleanedArticle:
    key = (
        cache.cleaned_article_key(xml_text=xml_text, metadata=metadata)
        if cache is not None
        else None
    )
    cached = _cache_read(
        cache=cache,
        action=(
            (lambda: cache.get_cleaned_article(key=key))
            if cache is not None and key is not None
            else None
        ),
        warnings=warnings,
        stage="cleaned_article_cache_read",
        pmid=metadata.pmid,
        pmc_id=pmcid,
    )
    if cached is not None:
        source = cached.source or ArticleSource(database="pubmed")
        return replace(cached, source=replace(source, retrieval_rank=retrieval_rank))

    article = clean_article_xml(
        xml_text=xml_text,
        metadata=metadata,
        pmcid=pmcid,
        retrieval_rank=retrieval_rank,
    )
    if cache is not None and key is not None:
        _cache_write(
            action=lambda: cache.put_cleaned_article(key=key, article=article),
            warnings=warnings,
            stage="cleaned_article_cache_write",
            pmid=metadata.pmid,
            pmc_id=pmcid,
        )
    return article


def _cache_read(
    *,
    cache: PubMedPmcFileCache | None,
    action,
    warnings: list[SearchRetrievalWarning],
    stage: str,
    pmid: str | None = None,
    pmc_id: str | None = None,
):
    if cache is None or action is None:
        return None
    try:
        return action()
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
    ):
        warnings.append(
            SearchRetrievalWarning(
                code="article_cache_read_failed",
                message=(
                    "A cached article artifact could not be read; the provider "
                    "was used instead."
                ),
                stage=stage,
                pmid=pmid,
                pmc_id=pmc_id,
            )
        )
        return None


def _cache_write(
    *,
    action,
    warnings: list[SearchRetrievalWarning],
    stage: str,
    pmid: str | None = None,
    pmc_id: str | None = None,
) -> None:
    try:
        action()
    except (OSError, UnicodeEncodeError, TypeError, ValueError):
        warnings.append(
            SearchRetrievalWarning(
                code="article_cache_write_failed",
                message=(
                    "An article artifact could not be cached; retrieval continued "
                    "normally."
                ),
                stage=stage,
                pmid=pmid,
                pmc_id=pmc_id,
            )
        )
