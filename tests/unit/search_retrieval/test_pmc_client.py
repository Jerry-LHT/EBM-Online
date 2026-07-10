from __future__ import annotations

from io import BytesIO

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pmc_client import (
    PmcClient,
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
