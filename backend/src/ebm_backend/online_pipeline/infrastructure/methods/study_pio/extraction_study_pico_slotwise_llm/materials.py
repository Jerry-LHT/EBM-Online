"""Build bounded, stage-specific article materials for Study PICO extraction."""

from __future__ import annotations

import re
from typing import Any, Literal

from ebm_backend.online_pipeline.domain.article import ArticleTable, CleanedArticle
from ebm_backend.online_pipeline.domain.question import QuestionPICO


StageName = Literal["population", "intervention_comparator", "outcome"]

MAX_SECTION_SNIPPETS = 18
MAX_SECTION_CHARS = 36_000
MAX_TABLE_SNIPPETS = 5

_STAGE_KEYWORDS: dict[StageName, tuple[str, ...]] = {
    "population": (
        "participant",
        "patient",
        "population",
        "eligibility",
        "inclusion",
        "exclusion",
        "baseline",
        "recruit",
        "setting",
    ),
    "intervention_comparator": (
        "intervention",
        "treatment",
        "control",
        "comparator",
        "placebo",
        "usual care",
        "sham",
        "random",
        "allocated",
        "dose",
        "duration",
    ),
    "outcome": (
        "outcome",
        "endpoint",
        "primary",
        "secondary",
        "measure",
        "assess",
        "follow-up",
        "adverse",
        "harm",
        "efficacy",
    ),
}


def build_stage_materials(
    *,
    stage: StageName,
    article: CleanedArticle,
    question_pico: QuestionPICO,
) -> dict[str, object]:
    query_terms = _pico_terms(question_pico)
    stage_terms = _stage_pico_terms(stage=stage, question_pico=question_pico)
    return {
        "article_title": article.metadata.title,
        "sections": _section_snippets(
            article=article,
            stage=stage,
            query_terms=query_terms,
            stage_terms=stage_terms,
        ),
        "tables": _table_snippets(article.tables, stage=stage),
    }


def _section_snippets(
    *,
    article: CleanedArticle,
    stage: StageName,
    query_terms: set[str],
    stage_terms: set[str],
) -> list[dict[str, str]]:
    scored: list[tuple[int, int, dict[str, str]]] = []
    for section_index, section in enumerate(article.xml_content.sections):
        title = _clean_text(section.title or "Section")
        for chunk_index, chunk in enumerate(_section_chunks(str(section.text or ""))):
            text = _clean_text(chunk)
            if not text:
                continue
            score = _score_text(
                stage=stage,
                title=title,
                text=text,
                query_terms=query_terms,
                stage_terms=stage_terms,
            )
            scored.append(
                (
                    score,
                    -(section_index * 1000 + chunk_index),
                    {
                        "section_id": section.section_id or f"section-{section_index + 1}",
                        "title": title,
                        "text": _truncate(text, 3500),
                    },
                )
            )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    selected: list[dict[str, str]] = []
    total_chars = 0
    for _, _, snippet in scored[:MAX_SECTION_SNIPPETS]:
        remaining = MAX_SECTION_CHARS - total_chars
        if remaining <= 0:
            break
        if len(snippet["text"]) > remaining:
            snippet = {**snippet, "text": _truncate(snippet["text"], remaining)}
        selected.append(snippet)
        total_chars += len(snippet["text"])
    return selected


def _score_text(
    *,
    stage: StageName,
    title: str,
    text: str,
    query_terms: set[str],
    stage_terms: set[str],
) -> int:
    lowered_title = title.casefold()
    lowered_text = text.casefold()
    score = 0
    for keyword in _STAGE_KEYWORDS[stage]:
        if keyword in lowered_title:
            score += 20
        if keyword in lowered_text:
            score += 6
    for term in query_terms:
        if len(term) >= 4 and term in lowered_text:
            score += 2
    for term in stage_terms:
        if len(term) >= 4:
            if term in lowered_title:
                score += 16
            if term in lowered_text:
                score += 8
    return score


def _table_snippets(
    tables: list[ArticleTable],
    *,
    stage: StageName,
) -> list[dict[str, str]]:
    scored: list[tuple[int, int, dict[str, str]]] = []
    for index, table in enumerate(tables):
        caption = _clean_text(table.caption)
        raw_text = _rows_text(table.rows)
        text = "\n".join(part for part in (caption, raw_text) if part)
        if not text:
            continue
        lowered = text.casefold()
        score = sum(10 for keyword in _STAGE_KEYWORDS[stage] if keyword in lowered)
        scored.append(
            (
                score,
                -index,
                {
                    "table_id": table.table_id or f"table-{index + 1}",
                    "caption": caption,
                    "text": _truncate(text, 5000),
                },
            )
        )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [snippet for _, _, snippet in scored[:MAX_TABLE_SNIPPETS]]


def _rows_text(rows: list[Any]) -> str:
    lines: list[str] = []
    for row in rows[:20]:
        if isinstance(row, dict):
            line = " | ".join(
                f"{key}: {value}" for key, value in row.items() if str(value).strip()
            )
        elif isinstance(row, list):
            line = " | ".join(str(value) for value in row if str(value).strip())
        else:
            line = str(row)
        cleaned = _clean_text(line)
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def _section_chunks(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for paragraph in paragraphs:
        if current and current_length + len(paragraph) > 2600:
            chunks.append("\n\n".join(current))
            current = []
            current_length = 0
        current.append(paragraph)
        current_length += len(paragraph)
    if current:
        chunks.append("\n\n".join(current))
    return chunks or ([text.strip()] if text.strip() else [])


def _stage_pico_terms(*, stage: StageName, question_pico: QuestionPICO) -> set[str]:
    if stage == "population":
        values = question_pico.P
    elif stage == "intervention_comparator":
        values = [*question_pico.I, *question_pico.C]
    else:
        values = question_pico.O
    return _terms(values)


def _pico_terms(question_pico: QuestionPICO) -> set[str]:
    return _terms([*question_pico.P, *question_pico.I, *question_pico.C, *question_pico.O])


def _terms(values: list[str]) -> set[str]:
    terms: set[str] = set()
    for value in values:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()
        if normalized:
            terms.add(normalized)
        terms.update(
            token.strip("-")
            for token in re.findall(r"[a-z][a-z0-9-]{2,}", normalized)
            if token.strip("-")
        )
    return terms


def _clean_text(value: Any) -> str:
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", str(value or ""), flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    suffix = " [... truncated]"
    return text[: max(0, max_chars - len(suffix))].rstrip() + suffix
