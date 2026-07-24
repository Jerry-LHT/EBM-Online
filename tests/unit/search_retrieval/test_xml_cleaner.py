from __future__ import annotations

from ebm_backend.online_pipeline.domain.article import ArticleTable
from ebm_backend.online_pipeline.domain.serialization import from_jsonable, to_jsonable
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
        metadata=PubMedArticleMetadata(
            pmid="101",
            title="Example Trial",
            publication_year="2021",
            publication_types=["Randomized Controlled Trial"],
            languages=["eng"],
            trial_registration_ids=["NCT01234567"],
        ),
        pmcid="PMC123",
        retrieval_rank=1,
    )

    assert article is not None
    assert [section.title for section in article.xml_content.sections] == ["Abstract", "Methods"]
    assert "This is the abstract." in article.xml_content.sections[0].text
    assert "Participants were randomized." in article.xml_content.sections[1].text
    assert article.metadata.publication_types == ["Randomized Controlled Trial"]
    assert article.metadata.languages == ["eng"]
    assert article.metadata.trial_registration_ids == ["NCT01234567"]
    assert article.tables
    assert article.tables[0].table_id == "T1"
    assert article.tables[0].rows[0]["_section_path"] == "Results"
    assert "<table-wrap" in article.tables[0].rows[0]["_raw_xml"]
    assert article.tables[0].raw_xml == article.tables[0].rows[0]["_raw_xml"]


def test_article_table_raw_xml_survives_domain_serialization() -> None:
    table = ArticleTable(
        table_id="T-contract",
        caption="Outcome",
        rows=[],
        raw_xml="<table-wrap id=\"T-contract\"><table/></table-wrap>",
    )

    restored = from_jsonable(to_jsonable(table), ArticleTable)

    assert restored.raw_xml == table.raw_xml


def test_xml_cleaner_extracts_nested_tables_without_flattening_them_into_text() -> None:
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><abstract><p>Trial abstract.</p></abstract></article-meta></front>
  <body>
    <sec>
      <title>Results</title>
      <p>Results before the nested table.</p>
      <table-wrap-group>
        <table-wrap id="T2">
          <label>Table 2</label>
          <caption><title>Outcome results</title></caption>
          <table><tr><td>Mean 12.3</td></tr></table>
        </table-wrap>
      </table-wrap-group>
      <p>Results after the nested table.</p>
    </sec>
  </body>
</article>
"""

    article = clean_article_xml(
        xml_text=xml_text,
        metadata=PubMedArticleMetadata(pmid="102", title="Nested Table Trial"),
        pmcid="PMC124",
        retrieval_rank=2,
    )

    assert len(article.tables) == 1
    assert article.tables[0].table_id == "T2"
    assert article.tables[0].caption == "Outcome results"
    assert article.tables[0].rows[0]["_section_path"] == "Results"
    assert "Mean 12.3" in article.tables[0].rows[0]["_raw_xml"]
    results = next(section for section in article.xml_content.sections if section.title == "Results")
    assert "Results before the nested table." in results.text
    assert "Results after the nested table." in results.text
    assert "Mean 12.3" not in results.text


def test_xml_cleaner_extracts_table_nested_inside_paragraph_and_keeps_tail_text() -> None:
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <body>
    <sec>
      <title>Results</title>
      <p>Before<table-wrap id="T3"><caption><title>Pain</title></caption>
        <table><tr><td>Hidden table value</td></tr></table></table-wrap>after.</p>
    </sec>
  </body>
</article>
"""

    article = clean_article_xml(
        xml_text=xml_text,
        metadata=PubMedArticleMetadata(pmid="103", title="Paragraph Table Trial"),
        pmcid="PMC125",
        retrieval_rank=3,
    )

    assert [table.table_id for table in article.tables] == ["T3"]
    assert article.xml_content.sections[0].text == "Before after."
    assert "Hidden table value" not in article.xml_content.sections[0].text
