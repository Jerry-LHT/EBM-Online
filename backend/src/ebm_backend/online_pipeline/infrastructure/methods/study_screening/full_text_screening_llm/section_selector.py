"""Deterministic section selection owned by the full-text screening method."""

from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.domain.article import ArticleSection, CleanedArticle


SECTION_PRIORITY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("abstract", ("abstract",)),
    ("methods", ("method", "design", "materials and methods")),
    ("participants", ("participant", "patient", "subject", "population", "baseline characteristic")),
    ("intervention", ("intervention", "treatment", "exposure", "procedure", "therapy")),
    ("outcomes", ("outcome", "endpoint")),
    ("results", ("result", "finding")),
    ("discussion", ("discussion", "conclusion")),
)


@dataclass(frozen=True)
class SelectedSection:
    label: str
    title: str
    text: str


def select_screening_sections(article: CleanedArticle, *, max_sections: int = 8) -> list[SelectedSection]:
    if max_sections <= 0:
        raise ValueError("max_sections must be positive")
    source_sections = article.xml_content.sections
    selected: list[SelectedSection] = []
    used_ids: set[str] = set()
    for label, keywords in SECTION_PRIORITY_RULES:
        match = _find_first_matching_section(source_sections, keywords=keywords, used_ids=used_ids)
        if match is None:
            continue
        selected.append(SelectedSection(label=label, title=match.title, text=match.text.strip()))
        used_ids.add(match.section_id)
        if len(selected) >= max_sections:
            return selected
    for section in source_sections:
        if section.section_id in used_ids:
            continue
        clean_text = section.text.strip()
        if not clean_text:
            continue
        selected.append(SelectedSection(label="other", title=section.title, text=clean_text))
        used_ids.add(section.section_id)
        if len(selected) >= max_sections:
            break
    return selected


def _find_first_matching_section(
    sections: list[ArticleSection],
    *,
    keywords: tuple[str, ...],
    used_ids: set[str],
) -> ArticleSection | None:
    for section in sections:
        if section.section_id in used_ids:
            continue
        title = (section.title or "").strip().casefold()
        if title and section.text.strip() and any(keyword in title for keyword in keywords):
            return section
    return None
