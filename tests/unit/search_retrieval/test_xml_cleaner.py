from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.models import PubMedArticleMetadata
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.xml_cleaner import (
    clean_article_xml,
)


def test_xml_cleaner_keeps_abstract_body_and_raw_tables() -> None:
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<pmc-articleset>
  <article>
    <front>
      <article-meta>
        <title-group><article-title>Example Trial</article-title></title-group>
        <abstract><p>This is the abstract.</p></abstract>
      </article-meta>
    </front>
    <body>
      <sec>
        <title>Methods</title>
        <p>Participants were randomized.</p>
      </sec>
      <sec>
        <title>Results</title>
        <table-wrap id="T1">
          <label>Table 1</label>
          <caption><title>Baseline characteristics</title></caption>
          <table><tr><td>A</td></tr></table>
        </table-wrap>
      </sec>
    </body>
  </article>
</pmc-articleset>
"""
    article = clean_article_xml(
        xml_text=xml_text,
        metadata=PubMedArticleMetadata(pmid="101", title="Example Trial", publication_year="2021"),
        pmcid="PMC123",
        retrieval_rank=1,
    )

    assert article is not None
    assert [section.title for section in article.xml_content.sections] == ["Abstract", "Methods"]
    assert "This is the abstract." in article.xml_content.sections[0].text
    assert "Participants were randomized." in article.xml_content.sections[1].text
    assert article.tables
    assert article.tables[0].table_id == "T1"
    assert article.tables[0].rows[0]["_section_path"] == "Results"
    assert "<table-wrap" in article.tables[0].rows[0]["_raw_xml"]
