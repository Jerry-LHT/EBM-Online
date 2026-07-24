"""Abstract selection owned by the abstract-screening method."""

from __future__ import annotations

from ebm_backend.online_pipeline.domain.article import CleanedArticle


def select_abstract_text(article: CleanedArticle) -> str | None:
    """Return the available abstract text without falling back to full text."""
    abstract_parts: list[str] = []
    seen: set[str] = set()
    for section in article.xml_content.sections:
        section_id = (section.section_id or "").strip().casefold()
        title = (section.title or "").strip().casefold()
        if section_id != "abstract" and title != "abstract":
            continue
        text = section.text.strip()
        if not text or text in seen:
            continue
        abstract_parts.append(text)
        seen.add(text)
    if not abstract_parts:
        return None
    return "\n\n".join(abstract_parts)
