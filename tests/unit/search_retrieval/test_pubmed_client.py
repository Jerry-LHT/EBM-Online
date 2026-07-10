from __future__ import annotations

from io import BytesIO
import urllib.parse

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pubmed_client import (
    PubMedClient,
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
    result = client.search(query="depression ssri", max_results=5)

    assert result.total_hits == 42
    assert result.pmids == ["101", "202"]
    assert "depression" in result.query_translation
    assert urllib.parse.urlparse(seen_urls[0]).path.endswith("/esearch.fcgi")


def test_pubmed_fetch_metadata_parses_title_year_doi_and_mesh_terms() -> None:
    payload = b"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>101</PMID>
      <Article>
        <ArticleTitle>Trial of SSRI in Depression</ArticleTitle>
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
