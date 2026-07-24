"""Clean PMC article XML into the backend article contract."""

from __future__ import annotations

from xml.etree import ElementTree

from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleSource,
    ArticleTable,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.models import PubMedArticleMetadata


SKIP_TAGS = {"fig", "ref-list", "supplementary-material"}
BACK_SECTION_TAGS = {"ack", "app-group", "app", "glossary", "fn-group"}
XML_CLEANER_VERSION = "pmc_xml_cleaner_v1"


def clean_article_xml(
    *,
    xml_text: str,
    metadata: PubMedArticleMetadata,
    pmcid: str,
    retrieval_rank: int,
) -> CleanedArticle:
    root = ElementTree.fromstring(xml_text)
    article = _find_article_root(root)

    sections: list[ArticleSection] = []
    abstract_text = _extract_abstract(article) or metadata.abstract.strip()
    if abstract_text:
        sections.append(ArticleSection(section_id="abstract", title="Abstract", text=abstract_text))

    tables: list[ArticleTable] = []
    _collect_sections_and_tables(article, sections=sections, tables=tables)
    tables = _dedupe_tables(tables)

    return CleanedArticle(
        study_id=f"pmc::{pmcid}",
        metadata=ArticleMetadata(
            title=metadata.title,
            pmid=metadata.pmid,
            pmc_id=pmcid,
            source_type="pmc",
            publication_year=metadata.publication_year,
            mesh_terms=list(metadata.mesh_terms),
            doi=metadata.doi,
            publication_types=list(metadata.publication_types),
            languages=list(metadata.languages),
            trial_registration_ids=list(metadata.trial_registration_ids),
            related_article_types=list(metadata.related_article_types),
            is_retracted=metadata.is_retracted,
            is_retraction_notice=metadata.is_retraction_notice,
            is_correction=metadata.is_correction,
        ),
        xml_content=ArticleXmlContent(sections=sections),
        tables=tables,
        source=ArticleSource(database="pubmed", retrieval_rank=retrieval_rank, raw_record_id=pmcid),
    )


def _find_article_root(root: ElementTree.Element) -> ElementTree.Element:
    if _local_name(root.tag) == "article":
        return root
    article = root.find(".//article")
    return article if article is not None else root


def _extract_abstract(article: ElementTree.Element) -> str:
    abstract = article.find("./front/article-meta/abstract")
    if abstract is None:
        abstract = article.find(".//abstract")
    if abstract is None:
        return ""
    parts = _block_texts(abstract)
    return "\n\n".join(part for part in parts if part)


def _collect_sections_and_tables(
    article: ElementTree.Element,
    *,
    sections: list[ArticleSection],
    tables: list[ArticleTable],
) -> None:
    body = article.find("./body")
    if body is not None:
        _walk_container(body, path=[], sections=sections, tables=tables)

    back = article.find("./back")
    if back is not None:
        for child in list(back):
            local = _local_name(child.tag)
            if local in BACK_SECTION_TAGS or local == "sec":
                _walk_container(child, path=["Back"], sections=sections, tables=tables)

    floats_group = article.find("./floats-group")
    if floats_group is not None:
        for table_wrap in floats_group.findall("./table-wrap"):
            parsed = _parse_table(table_wrap, section_path=["Floats"])
            if parsed is not None:
                tables.append(parsed)


def _walk_container(
    node: ElementTree.Element,
    *,
    path: list[str],
    sections: list[ArticleSection],
    tables: list[ArticleTable],
) -> None:
    local = _local_name(node.tag)
    if local in SKIP_TAGS:
        return

    if local == "sec":
        title = _first_child_text(node, "title") or "Section"
        next_path = [*path, title]
        text_blocks: list[str] = []
        for child in list(node):
            child_local = _local_name(child.tag)
            if child_local == "title":
                continue
            if child_local == "sec":
                _walk_container(child, path=next_path, sections=sections, tables=tables)
                continue
            if child_local == "table-wrap":
                parsed = _parse_table(child, section_path=next_path)
                if parsed is not None:
                    tables.append(parsed)
                continue
            if child_local in SKIP_TAGS:
                continue
            _collect_nested_tables(child, section_path=next_path, tables=tables)
            text_blocks.extend(_block_texts(child))
        body_text = "\n\n".join(part for part in text_blocks if part)
        if body_text:
            sections.append(ArticleSection(section_id=_section_id(next_path), title=title, text=body_text))
        return

    if local == "table-wrap":
        parsed = _parse_table(node, section_path=path)
        if parsed is not None:
            tables.append(parsed)
        return

    for child in list(node):
        _walk_container(child, path=path, sections=sections, tables=tables)


def _parse_table(node: ElementTree.Element, *, section_path: list[str]) -> ArticleTable | None:
    table = _first_descendant(node, "table")
    if table is None:
        return None
    label = _first_child_text(node, "label")
    caption = _text_of(_first_child(node, "caption"))
    return ArticleTable(
        table_id=str(node.attrib.get("id") or label or caption or "table"),
        caption=caption,
        rows=[
            {
                "_raw_xml": ElementTree.tostring(node, encoding="unicode"),
                "_section_path": " / ".join(section_path),
            }
        ],
        raw_xml=ElementTree.tostring(node, encoding="unicode"),
    )


def _block_texts(node: ElementTree.Element) -> list[str]:
    texts: list[str] = []
    local = _local_name(node.tag)
    if local in SKIP_TAGS or local == "table-wrap":
        return texts
    if local in {"p", "title", "label"}:
        text = _text_excluding_tables(node)
        if text:
            texts.append(text)
        return texts
    for child in list(node):
        texts.extend(_block_texts(child))
    if not texts:
        text = _text_excluding_tables(node)
        if text:
            texts.append(text)
    return texts


def _collect_nested_tables(
    node: ElementTree.Element,
    *,
    section_path: list[str],
    tables: list[ArticleTable],
) -> None:
    local = _local_name(node.tag)
    if local in SKIP_TAGS:
        return
    if local == "table-wrap":
        parsed = _parse_table(node, section_path=section_path)
        if parsed is not None:
            tables.append(parsed)
        return
    for child in list(node):
        _collect_nested_tables(child, section_path=section_path, tables=tables)


def _text_excluding_tables(node: ElementTree.Element) -> str:
    parts: list[str] = []

    def visit(current: ElementTree.Element) -> None:
        if current.text:
            parts.append(current.text)
        for child in list(current):
            local = _local_name(child.tag)
            if local not in SKIP_TAGS and local != "table-wrap":
                visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(node)
    return " ".join(" ".join(parts).split()).strip()


def _dedupe_tables(tables: list[ArticleTable]) -> list[ArticleTable]:
    results: list[ArticleTable] = []
    seen_raw_xml: set[str] = set()
    for table in tables:
        raw_xml = next(
            (
                str(row.get("_raw_xml"))
                for row in table.rows
                if isinstance(row, dict) and row.get("_raw_xml")
            ),
            "",
        )
        if raw_xml and raw_xml in seen_raw_xml:
            continue
        if raw_xml:
            seen_raw_xml.add(raw_xml)
        results.append(table)
    return results


def _first_child_text(node: ElementTree.Element, tag_name: str) -> str | None:
    for child in list(node):
        if _local_name(child.tag) == tag_name:
            text = _text_of(child)
            if text:
                return text
    return None


def _first_child(
    node: ElementTree.Element,
    tag_name: str,
) -> ElementTree.Element | None:
    return next(
        (child for child in list(node) if _local_name(child.tag) == tag_name),
        None,
    )


def _first_descendant(
    node: ElementTree.Element,
    tag_name: str,
) -> ElementTree.Element | None:
    return next(
        (descendant for descendant in node.iter() if _local_name(descendant.tag) == tag_name),
        None,
    )


def _text_of(node: ElementTree.Element | None) -> str:
    if node is None:
        return ""
    text = "".join(node.itertext())
    return " ".join(text.split()).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _section_id(section_path: list[str]) -> str:
    return "/".join(part.strip().lower().replace(" ", "_") for part in section_path if part.strip()) or "section"
