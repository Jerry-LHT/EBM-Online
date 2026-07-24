from __future__ import annotations

import http.client
from io import BytesIO
import urllib.parse

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pubmed_client import (
    PubMedClient,
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


def test_pubmed_search_parses_count_pmids_and_query_translation() -> None:
    seen_urls: list[str] = []
    payload = b"""<?xml version="1.0" encoding="UTF-8"?>
<eSearchResult>
  <Count>42</Count>
  <IdList>
    <Id>101</Id>
    <Id>202</Id>
  </IdList>
  <QueryTranslation>("depression"[MeSH Terms]) AND ssri</QueryTranslation>
</eSearchResult>
"""

    def opener(request, timeout):
        seen_urls.append(request.full_url)
        return _FakeResponse(payload)

    client = PubMedClient(opener=opener)
    result = client.search(query="depression ssri", max_candidates=5)

    assert result.total_hits == 42
    assert result.pmids == ["101", "202"]
    assert "depression" in result.query_translation
    assert urllib.parse.urlparse(seen_urls[0]).path.endswith("/esearch.fcgi")


def test_pubmed_search_pages_until_the_configured_inventory_limit() -> None:
    seen_starts: list[int] = []

    def opener(request, timeout):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        start = int(query["retstart"][0])
        size = int(query["retmax"][0])
        seen_starts.append(start)
        ids = "".join(f"<Id>{value}</Id>" for value in range(start + 1, start + size + 1))
        return _FakeResponse(
            f"<eSearchResult><Count>700</Count><IdList>{ids}</IdList></eSearchResult>".encode()
        )

    result = PubMedClient(opener=opener).search(
        query="depression",
        max_candidates=650,
    )

    assert len(result.pmids) == 650
    assert seen_starts == [0, 500]


def test_pubmed_fetch_metadata_parses_title_year_doi_and_mesh_terms() -> None:
    payload = b"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>101</PMID>
      <Article>
        <ArticleTitle>Trial of SSRI in Depression</ArticleTitle>
        <Language>eng</Language>
        <Journal>
          <JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue>
        </Journal>
        <PublicationTypeList>
          <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
      </Article>
      <MeshHeadingList>
        <MeshHeading><DescriptorName>Depressive Disorder</DescriptorName></MeshHeading>
      </MeshHeadingList>
      <DataBankList>
        <DataBank>
          <DataBankName>ClinicalTrials.gov</DataBankName>
          <AccessionNumberList><AccessionNumber>NCT01234567</AccessionNumber></AccessionNumberList>
        </DataBank>
      </DataBankList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1000/example</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

    client = PubMedClient(opener=lambda request, timeout: _FakeResponse(payload))
    items = client.fetch_metadata(pmids=["101"])

    assert items["101"].title == "Trial of SSRI in Depression"
    assert items["101"].publication_year == "2021"
    assert items["101"].doi == "10.1000/example"
    assert items["101"].mesh_terms == ["Depressive Disorder"]
    assert items["101"].publication_types == ["Randomized Controlled Trial"]
    assert items["101"].languages == ["eng"]
    assert items["101"].trial_registration_ids == ["NCT01234567"]


def test_pubmed_search_retries_malformed_xml_once(monkeypatch) -> None:
    payloads = [
        b"<not-closed>",
        b"<eSearchResult><Count>1</Count><IdList><Id>101</Id></IdList></eSearchResult>",
    ]
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        payload = payloads[calls]
        calls += 1
        return _FakeResponse(payload)

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pubmed_client.time.sleep",
        lambda _: None,
    )

    result = PubMedClient(opener=opener, retries=1).search(
        query="depression",
        max_candidates=5,
    )

    assert result.pmids == ["101"]
    assert calls == 2


def test_pubmed_search_retries_remote_disconnect_once(monkeypatch) -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise http.client.RemoteDisconnected("remote closed connection")
        return _FakeResponse(
            b"<eSearchResult><Count>1</Count><IdList><Id>101</Id></IdList></eSearchResult>"
        )

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pubmed_client.time.sleep",
        lambda _: None,
    )

    result = PubMedClient(opener=opener, retries=1).search(
        query="depression",
        max_candidates=5,
    )

    assert result.pmids == ["101"]
    assert calls == 2


def test_pubmed_search_reports_retry_exhaustion(monkeypatch) -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        return _FakeResponse(b"<not-closed>")

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pubmed_client.time.sleep",
        lambda _: None,
    )

    with pytest.raises(SearchRetrievalStageError) as error:
        PubMedClient(opener=opener, retries=1).search(
            query="depression",
            max_candidates=5,
        )

    assert error.value.stage == "pubmed_search"
    assert error.value.attempts == 2
    assert calls == 2


def test_pubmed_search_retries_structurally_invalid_xml_once(monkeypatch) -> None:
    payloads = [
        b"<eSearchResult><Count>not-an-integer</Count><IdList /></eSearchResult>",
        b"<eSearchResult><Count>0</Count><IdList /></eSearchResult>",
    ]
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        payload = payloads[calls]
        calls += 1
        return _FakeResponse(payload)

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pubmed_client.time.sleep",
        lambda _: None,
    )

    result = PubMedClient(opener=opener, retries=1).search(
        query="depression",
        max_candidates=5,
    )

    assert result.total_hits == 0
    assert calls == 2
