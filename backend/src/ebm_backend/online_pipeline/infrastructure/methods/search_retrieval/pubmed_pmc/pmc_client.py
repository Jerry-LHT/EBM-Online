"""PMC ID conversion and full-text XML client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import http.client
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree

import certifi

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.errors import (
    SearchRetrievalStageError,
)


USER_AGENT = "ebm-online-pipeline-search-retrieval/0.1"
PMC_IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
PMC_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 1

Urlopen = Callable[[urllib.request.Request, float], object]


@dataclass
class PmcClient:
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    requests_per_second: float = 3.0
    opener: Urlopen | None = None

    def __post_init__(self) -> None:
        self.opener = self.opener or _default_urlopen
        self._min_interval = 1.0 / self.requests_per_second if self.requests_per_second > 0 else 0.0
        self._last_request_at = 0.0

    def resolve_pmcids(self, *, pmids: list[str]) -> dict[str, str]:
        if not pmids:
            return {}
        params = urllib.parse.urlencode(
            {
                "format": "json",
                "ids": ",".join(pmids),
                "idtype": "pmid",
            }
        )
        data = self._request_json(
            f"{PMC_IDCONV_URL}?{params}",
            stage="pmcid_resolution",
        )
        resolved: dict[str, str] = {}
        for record in data.get("records") or []:
            pmid = str(record.get("pmid") or "").strip()
            pmcid = str(record.get("pmcid") or "").strip()
            if pmid and pmcid:
                resolved[pmid] = pmcid
        return resolved

    def fetch_full_text_xml(self, *, pmcids: list[str]) -> dict[str, str]:
        if not pmcids:
            return {}
        params = urllib.parse.urlencode(
            {
                "db": "pmc",
                "id": ",".join(pmcids),
                "retmode": "xml",
            }
        )
        root = self._request_xml(
            f"{PMC_EFETCH_URL}?{params}",
            stage="pmc_full_text",
        )
        results: dict[str, str] = {}
        for article in root.findall("./article"):
            pmcid = _article_pmcid(article)
            if not pmcid:
                continue
            results[pmcid] = ElementTree.tostring(article, encoding="unicode")
        return results

    def _request_json(self, url: str, *, stage: str) -> dict:
        return self._request_parsed(
            url,
            stage=stage,
            parser=lambda payload: _parse_json_object(payload),
        )

    def _request_xml(self, url: str, *, stage: str) -> ElementTree.Element:
        return self._request_parsed(
            url,
            stage=stage,
            parser=_parse_pmc_articleset,
        )

    def _request_parsed(self, url: str, *, stage: str, parser):
        for attempt in range(self.retries + 1):
            try:
                self._throttle()
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with self.opener(request, self.timeout) as response:
                    payload = response.read().decode("utf-8")
                return parser(payload)
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
                json.JSONDecodeError,
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


def _article_pmcid(article: ElementTree.Element) -> str | None:
    for node in article.findall(".//article-id"):
        if str(node.attrib.get("pub-id-type") or "").lower() == "pmcid":
            text = "".join(node.itertext()).strip()
            if text:
                return text
    return None


def _parse_json_object(payload: str) -> dict:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("PMC response JSON must be an object")
    records = data.get("records", [])
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise ValueError("PMC response records must be a list of objects")
    return data


def _parse_pmc_articleset(payload: str) -> ElementTree.Element:
    root = ElementTree.fromstring(payload)
    if root.tag != "pmc-articleset":
        raise ValueError("PMC full-text response root must be pmc-articleset")
    return root


def _default_urlopen(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where()))
