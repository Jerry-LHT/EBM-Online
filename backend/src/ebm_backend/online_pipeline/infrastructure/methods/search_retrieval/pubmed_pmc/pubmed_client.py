"""PubMed ESearch and EFetch client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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


USER_AGENT = "ebm-online-pipeline-search-retrieval/0.1"
PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 2

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

    def search(self, *, query: str, max_results: int) -> PubMedSearchResult:
        params = urllib.parse.urlencode(
            {
                "db": "pubmed",
                "retmode": "xml",
                "term": query,
                "retmax": str(max(0, max_results)),
            }
        )
        payload = self._request_text(f"{PUBMED_ESEARCH_URL}?{params}")
        root = ElementTree.fromstring(payload)
        count = int(_first_text(root, "./Count") or 0)
        pmids = [_text_content(node).strip() for node in root.findall("./IdList/Id") if _text_content(node).strip()]
        return PubMedSearchResult(
            total_hits=count,
            pmids=pmids,
            query_translation=_first_text(root, "./QueryTranslation"),
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
        payload = self._request_text(f"{PUBMED_EFETCH_URL}?{params}")
        root = ElementTree.fromstring(payload)
        metadata_by_pmid: dict[str, PubMedArticleMetadata] = {}
        for article in root.findall(".//PubmedArticle"):
            metadata = _parse_pubmed_article(article)
            if metadata is not None:
                metadata_by_pmid[metadata.pmid] = metadata
        return metadata_by_pmid

    def _request_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self._throttle()
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with self.opener(request, self.timeout) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if 400 <= exc.code < 500 and exc.code != 429:
                    raise
                if attempt >= self.retries:
                    raise
                time.sleep(min(2**attempt, 8))
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, UnicodeDecodeError, ElementTree.ParseError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise RuntimeError(f"PubMed request failed: {url}") from exc
                time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"Unreachable PubMed failure: {last_error}")

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
    return PubMedArticleMetadata(
        pmid=pmid,
        title=title or pmid,
        publication_year=publication_year,
        abstract="\n\n".join(part for part in abstract_parts if part),
        doi=doi,
        mesh_terms=mesh_terms,
        publication_types=publication_types,
    )


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
