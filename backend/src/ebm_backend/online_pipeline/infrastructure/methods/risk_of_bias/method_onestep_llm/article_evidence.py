"""Article evidence preparation for the one-step RoB method."""

from __future__ import annotations

import json

from ebm_backend.online_pipeline.domain.article import ArticleTable, CleanedArticle


ARTICLE_EVIDENCE_VERSION = "rob1_article_evidence_v1"


def build_article_evidence(article: CleanedArticle) -> str:
    front: list[str] = []
    methods: list[str] = []
    results: list[str] = []
    other: list[str] = []
    for section in article.xml_content.sections:
        title = section.title or "Section"
        block = f"### {title}\n{section.text}"
        normalized = title.lower()
        if normalized in {"front", "abstract"} or "abstract" in normalized:
            front.append(block)
        elif "method" in normalized or "material" in normalized or "participant" in normalized:
            methods.append(block)
        elif "result" in normalized:
            results.append(block)
        else:
            other.append(block)

    parts = [f"Study: {article.study_id}", "\n## Abstract / Front matter", *front[:3]]
    if methods:
        parts.extend(["\n## Methods", *methods])
    if results:
        parts.extend(["\n## Results", *results])
    table_text = _tables_text(article.tables)
    if table_text:
        parts.extend(["\n## Tables", table_text])
    if other:
        parts.extend(["\n## Other sections", *[item[:5000] for item in other[:8]]])
    text = "\n\n".join(part for part in parts if part)
    max_chars = 180_000
    if len(text) > max_chars:
        table_marker = "\n\n## Tables"
        table_part = ""
        if table_marker in text:
            prefix, _, suffix = text.partition(table_marker)
            table_part = table_marker + suffix
            text = prefix
        text = text[: max_chars - len(table_part) - 2000] + "\n\n[... truncated ...]" + table_part[:80_000]
    return text


def _tables_text(tables: list[ArticleTable]) -> str:
    chunks = []
    prioritized = sorted(tables, key=lambda table: 0 if _table_is_high_priority(table) else 1)
    for index, table in enumerate(prioritized[:12], start=1):
        rows_text = _rows_text(table.rows)
        chunks.append(f"### Table {index}: {table.caption or table.table_id}\n{rows_text[:8000]}")
    return "\n\n".join(chunks)


def _table_is_high_priority(table: ArticleTable) -> bool:
    text = f"{table.caption} {json.dumps(table.rows, ensure_ascii=False)[:1000]}".lower()
    return any(keyword in text for keyword in ("flow", "attrition", "withdraw", "lost", "baseline", "outcome", "adverse", "protocol"))


def _rows_text(rows: list[dict[str, str]]) -> str:
    lines = []
    for row in rows[:80]:
        if "_raw_xml" in row:
            section_path = row.get("_section_path") or ""
            lines.append(f"Section path: {section_path}\nRaw XML: {row.get('_raw_xml', '')}")
        else:
            lines.append(" | ".join(f"{key}: {value}" for key, value in row.items()))
    return "\n".join(lines)
