"""PubMed ESearch and EFetch client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import http.client
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree

import certifi

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.models import (
    PubMedArticleMetadata,
    PubMedSearchResult,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.errors import (
    SearchRetrievalStageError,
)


USER_AGENT = "ebm-online-pipeline-search-retrieval/0.1"
PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 1
DEFAULT_SEARCH_PAGE_SIZE = 500
MAX_SEARCH_RECORDS = 10_000

Urlopen = Callable[[urllib.request.Request, float], object]


@dataclass
class PubMedClient:
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    requests_per_second: float = 3.0
    opener: Urlopen | None = None

    def __post_init__(self) -> None:
        self.opener = self.opener or _default_urlopen
        self._min_interval = 1.0 / self.requests_per_second if self.requests_per_second > 0 else 0.0
        self._last_request_at = 0.0

    def search(
        self,
        *,
        query: str,
        max_candidates: int | None,
    ) -> PubMedSearchResult:
        limit = min(max_candidates or MAX_SEARCH_RECORDS, MAX_SEARCH_RECORDS)
        pmids: list[str] = []
        count = 0
        query_translation: str | None = None
        while len(pmids) < limit:
            page_size = min(DEFAULT_SEARCH_PAGE_SIZE, limit - len(pmids))
            params = urllib.parse.urlencode(
                {
                    "db": "pubmed",
                    "retmode": "xml",
                    "term": query,
                    "retstart": str(len(pmids)),
                    "retmax": str(page_size),
                }
            )
            root = self._request_xml(
                f"{PUBMED_ESEARCH_URL}?{params}",
                stage="pubmed_search",
                validator=_validate_search_response,
            )
            count = int(_first_text(root, "./Count") or 0)
            if query_translation is None:
                query_translation = _first_text(root, "./QueryTranslation")
            page = [
                _text_content(node).strip()
                for node in root.findall("./IdList/Id")
                if _text_content(node).strip()
            ]
            if not page:
                break
            before = len(pmids)
            seen = set(pmids)
            pmids.extend(pmid for pmid in page if pmid not in seen)
            if len(pmids) >= count or len(pmids) == before or len(page) < page_size:
                break
        return PubMedSearchResult(
            total_hits=count,
            pmids=pmids[:limit],
            query_translation=query_translation,
        )

    def fetch_metadata(self, *, pmids: list[str]) -> dict[str, PubMedArticleMetadata]:
        if not pmids:
            return {}
        params = urllib.parse.urlencode(
            {
                "db": "pubmed",
                "retmode": "xml",
                "id": ",".join(pmids),
            }
        )
        root = self._request_xml(
            f"{PUBMED_EFETCH_URL}?{params}",
            stage="pubmed_metadata",
        )
        metadata_by_pmid: dict[str, PubMedArticleMetadata] = {}
        for article in root.findall(".//PubmedArticle"):
            metadata = _parse_pubmed_article(article)
            if metadata is not None:
                metadata_by_pmid[metadata.pmid] = metadata
        return metadata_by_pmid

    def _request_xml(
        self,
        url: str,
        *,
        stage: str,
        validator: Callable[[ElementTree.Element], None] | None = None,
    ) -> ElementTree.Element:
        for attempt in range(self.retries + 1):
            try:
                self._throttle()
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with self.opener(request, self.timeout) as response:
                    payload = response.read().decode("utf-8")
                root = ElementTree.fromstring(payload)
                if validator is not None:
                    validator(root)
                return root
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500 and exc.code != 429:
                    raise SearchRetrievalStageError(
                        stage=stage,
                        attempts=attempt + 1,
                    ) from exc
                if attempt >= self.retries:
                    raise SearchRetrievalStageError(
                        stage=stage,
                        attempts=attempt + 1,
                    ) from exc
                time.sleep(min(2**attempt, 8))
            except (
                urllib.error.URLError,
                http.client.RemoteDisconnected,
                http.client.IncompleteRead,
                ConnectionError,
                TimeoutError,
                ssl.SSLError,
                UnicodeDecodeError,
                ElementTree.ParseError,
                ValueError,
            ) as exc:
                if attempt >= self.retries:
                    raise SearchRetrievalStageError(
                        stage=stage,
                        attempts=attempt + 1,
                    ) from exc
                time.sleep(min(2**attempt, 8))
        raise AssertionError("unreachable")

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()


def _parse_pubmed_article(article: ElementTree.Element) -> PubMedArticleMetadata | None:
    pmid = _first_text(article, ".//PMID")
    if not pmid:
        return None
    title = _first_text(article, ".//ArticleTitle")
    abstract_parts = [_text_content(node).strip() for node in article.findall(".//Abstract/AbstractText")]
    publication_year = (
        _first_text(article, ".//PubDate/Year")
        or _first_text(article, ".//ArticleDate/Year")
        or _first_text(article, ".//PubMedPubDate[@PubStatus='pubmed']/Year")
    )
    doi = None
    for article_id in article.findall(".//ArticleId"):
        if str(article_id.attrib.get("IdType") or "").lower() == "doi":
            doi = _text_content(article_id).strip() or None
            if doi:
                break
    mesh_terms: list[str] = []
    for heading in article.findall(".//MeshHeading"):
        label = _first_text(heading, ".//DescriptorName")
        if label:
            mesh_terms.append(label)
    publication_types: list[str] = []
    for node in article.findall(".//PublicationType"):
        label = _text_content(node).strip()
        if label:
            publication_types.append(label)
    languages = [
        _text_content(node).strip()
        for node in article.findall(".//Article/Language")
        if _text_content(node).strip()
    ]
    trial_registration_ids: list[str] = []
    for databank in article.findall(".//DataBankList/DataBank"):
        name = _first_text(databank, "./DataBankName") or ""
        if not _is_trial_registry_name(name):
            continue
        trial_registration_ids.extend(
            _text_content(node).strip()
            for node in databank.findall("./AccessionNumberList/AccessionNumber")
            if _text_content(node).strip()
        )
    related_article_types = [
        str(node.attrib.get("RefType") or "").strip()
        for node in article.findall(".//CommentsCorrections")
        if str(node.attrib.get("RefType") or "").strip()
    ]
    normalized_types = {value.casefold() for value in publication_types}
    normalized_relations = {value.casefold() for value in related_article_types}
    return PubMedArticleMetadata(
        pmid=pmid,
        title=title or pmid,
        publication_year=publication_year,
        abstract="\n\n".join(part for part in abstract_parts if part),
        doi=doi,
        mesh_terms=mesh_terms,
        publication_types=publication_types,
        languages=languages,
        trial_registration_ids=trial_registration_ids,
        related_article_types=related_article_types,
        is_retracted=(
            "retracted publication" in normalized_types
            or "retractionin" in normalized_relations
        ),
        is_retraction_notice=(
            "retraction of publication" in normalized_types
            or "retraction notice" in normalized_types
            or "retractionof" in normalized_relations
        ),
        is_correction=(
            "published erratum" in normalized_types
            or bool(normalized_relations & {"erratumin", "erratumfor", "correctedandrepublishedin"})
        ),
    )


def _is_trial_registry_name(value: str) -> bool:
    normalized = value.strip().casefold()
    return normalized in {
        "clinicaltrials.gov",
        "isrctn",
        "anzctr",
        "chictr",
        "ctri",
        "drks",
        "eudract",
        "irct",
        "jprn",
        "pactr",
        "umin-ctr",
    }


def _validate_search_response(root: ElementTree.Element) -> None:
    if root.tag != "eSearchResult":
        raise ValueError("PubMed search response root must be eSearchResult")
    count = _first_text(root, "./Count")
    if count is None:
        raise ValueError("PubMed search response is missing Count")
    if int(count) < 0:
        raise ValueError("PubMed search response Count must not be negative")
    if root.find("./IdList") is None:
        raise ValueError("PubMed search response is missing IdList")


def _first_text(node: ElementTree.Element, path: str) -> str | None:
    element = node.find(path)
    if element is None:
        return None
    text = _text_content(element).strip()
    return text or None


def _text_content(node: ElementTree.Element) -> str:
    return "".join(node.itertext())


def _default_urlopen(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where()))
