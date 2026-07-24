from __future__ import annotations

import http.client
from io import BytesIO

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pmc_client import (
    PmcClient,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.errors import (
    SearchRetrievalStageError,
)


class _FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def test_pmc_id_converter_maps_pmid_to_pmcid() -> None:
    payload = b'{"records":[{"requested-id":"101","pmid":"101","pmcid":"PMC123"}]}'
    client = PmcClient(opener=lambda request, timeout: _FakeResponse(payload))

    items = client.resolve_pmcids(pmids=["101"])

    assert items == {"101": "PMC123"}


def test_pmc_fetch_full_text_xml_splits_multi_article_payload() -> None:
    payload = b"""<?xml version="1.0" encoding="UTF-8"?>
<pmc-articleset>
  <article>
    <front><article-meta><article-id pub-id-type="pmcid">PMC123</article-id></article-meta></front>
    <body><sec><title>Results</title><p>Result A</p></sec></body>
  </article>
  <article>
    <front><article-meta><article-id pub-id-type="pmcid">PMC456</article-id></article-meta></front>
    <body><sec><title>Results</title><p>Result B</p></sec></body>
  </article>
</pmc-articleset>
"""
    client = PmcClient(opener=lambda request, timeout: _FakeResponse(payload))

    items = client.fetch_full_text_xml(pmcids=["PMC123", "PMC456"])

    assert set(items) == {"PMC123", "PMC456"}
    assert "Result A" in items["PMC123"]
    assert "Result B" in items["PMC456"]


def test_pmc_id_converter_retries_malformed_json_once(monkeypatch) -> None:
    payloads = [
        b"not-json",
        b'{"records":[{"pmid":"101","pmcid":"PMC123"}]}',
    ]
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        payload = payloads[calls]
        calls += 1
        return _FakeResponse(payload)

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pmc_client.time.sleep",
        lambda _: None,
    )

    result = PmcClient(opener=opener, retries=1).resolve_pmcids(pmids=["101"])

    assert result == {"101": "PMC123"}
    assert calls == 2


def test_pmc_full_text_reports_retry_exhaustion(monkeypatch) -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        return _FakeResponse(b"<not-closed>")

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pmc_client.time.sleep",
        lambda _: None,
    )

    with pytest.raises(SearchRetrievalStageError) as error:
        PmcClient(opener=opener, retries=1).fetch_full_text_xml(pmcids=["PMC123"])

    assert error.value.stage == "pmc_full_text"
    assert error.value.attempts == 2
    assert calls == 2


def test_pmc_full_text_retries_incomplete_response_once(monkeypatch) -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise http.client.IncompleteRead(b"partial")
        return _FakeResponse(
            b'<pmc-articleset><article><front><article-meta>'
            b'<article-id pub-id-type="pmcid">PMC123</article-id>'
            b'</article-meta></front></article></pmc-articleset>'
        )

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pmc_client.time.sleep",
        lambda _: None,
    )

    result = PmcClient(opener=opener, retries=1).fetch_full_text_xml(
        pmcids=["PMC123"]
    )

    assert set(result) == {"PMC123"}
    assert calls == 2


def test_pmc_id_converter_retries_invalid_record_shape_once(monkeypatch) -> None:
    payloads = [
        b'{"records":["invalid"]}',
        b'{"records":[{"pmid":"101","pmcid":"PMC123"}]}',
    ]
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        payload = payloads[calls]
        calls += 1
        return _FakeResponse(payload)

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pmc_client.time.sleep",
        lambda _: None,
    )

    result = PmcClient(opener=opener, retries=1).resolve_pmcids(pmids=["101"])

    assert result == {"101": "PMC123"}
    assert calls == 2
