"""Bounded evidence navigation for staged screening.

This module selects source material; it does not parse result values or decide
eligibility. Raw table XML remains intact for the LLM within each bounded block.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.meta_analysis import MetaAnalysisSynthesisPlan
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_GENERIC_SCREENING_TERMS = {
    "randomized",
    "randomised",
    "trial",
    "participants",
    "patients",
    "intervention",
    "control",
    "placebo",
    "methods",
    "results",
    "outcome",
    "endpoint",
}
_NUMERIC_RESULT_TERMS = {
    "mean",
    "standard",
    "deviation",
    "events",
    "total",
    "confidence",
    "interval",
    "adjusted",
    "change",
    "baseline",
    "follow-up",
    "followup",
    "percent",
}


@dataclass(frozen=True)
class EvidenceBlock:
    source_id: str
    kind: str
    label: str
    text: str
    coverage: str = "complete"
    start_char: int = 0
    end_char: int | None = None
    total_chars: int | None = None


@dataclass(frozen=True)
class EvidenceBundle:
    blocks: list[EvidenceBlock]

    @property
    def sources(self) -> dict[str, str]:
        return {block.source_id: block.text for block in self.blocks}

    @property
    def char_count(self) -> int:
        return sum(len(block.text) for block in self.blocks)

    def format(self) -> str:
        if not self.blocks:
            return "[No usable article evidence was available]"
        return "\n\n".join(
            (
                f"[SOURCE {block.source_id} | {block.kind} | {block.coverage} | "
                f"chars {block.start_char}:{block.end_char or len(block.text)}/"
                f"{block.total_chars or len(block.text)} | {block.label}]\n{block.text}"
            )
            for block in self.blocks
        )


def build_coarse_evidence(
    *,
    article: CleanedArticle,
    criteria: ScreeningCriteria,
    synthesis_plan: MetaAnalysisSynthesisPlan,
    max_section_blocks: int = 4,
    max_chars: int = 18_000,
    section_chunk_chars: int = 4_000,
) -> EvidenceBundle:
    """Return title, abstract, and a few relevant prose windows.

    Empty or uninformative headings are not a problem because section content
    also participates in ranking. Tables are deliberately excluded here.
    """
    _validate_limits(max_section_blocks, max_chars, section_chunk_chars)
    terms = _task_terms(criteria=criteria, synthesis_plan=synthesis_plan)
    blocks: list[EvidenceBlock] = []
    if article.metadata.title.strip():
        blocks.append(
            EvidenceBlock(
                source_id="title",
                kind="title",
                label="article title",
                text=article.metadata.title.strip(),
            )
        )
    section_blocks = _section_blocks(article, chunk_chars=section_chunk_chars)
    abstracts = [block for block in section_blocks if _is_abstract(block)]
    if abstracts:
        blocks.append(abstracts[0])
    used = {block.source_id for block in blocks}
    ranked = sorted(
        (block for block in section_blocks if block.source_id not in used),
        key=lambda block: (-_score(block, terms | _GENERIC_SCREENING_TERMS), block.source_id),
    )
    blocks.extend(ranked[:max_section_blocks])
    return _fit_blocks(blocks, max_chars=max_chars)


def build_final_evidence(
    *,
    article: CleanedArticle,
    criteria: ScreeningCriteria,
    synthesis_plan: MetaAnalysisSynthesisPlan,
    max_section_blocks: int = 10,
    max_table_blocks: int = 5,
    max_chars: int = 64_000,
    section_chunk_chars: int = 5_000,
    table_block_chars: int = 14_000,
) -> EvidenceBundle:
    """Return targeted prose plus the most relevant raw table sources."""
    _validate_limits(max_section_blocks, max_chars, section_chunk_chars)
    if max_table_blocks <= 0 or table_block_chars <= 0:
        raise ValueError("final screening table limits must be positive")
    terms = _task_terms(criteria=criteria, synthesis_plan=synthesis_plan)
    ranked_sections = sorted(
        _section_blocks(article, chunk_chars=section_chunk_chars),
        key=lambda block: (
            -_score(block, terms | _GENERIC_SCREENING_TERMS | _NUMERIC_RESULT_TERMS),
            block.source_id,
        ),
    )
    ranked_tables = sorted(
        _table_blocks(article, block_chars=table_block_chars),
        key=lambda block: (
            -_score(block, terms | _NUMERIC_RESULT_TERMS),
            block.source_id,
        ),
    )
    # Interleave prose and tables so one source class cannot consume the full
    # character budget before the other is represented.
    selected_sections = ranked_sections[:max_section_blocks]
    selected_tables = ranked_tables[:max_table_blocks]
    blocks: list[EvidenceBlock] = []
    if article.metadata.title.strip():
        blocks.append(
            EvidenceBlock(
                source_id="title",
                kind="title",
                label="article title",
                text=article.metadata.title.strip(),
            )
        )
    for index in range(max(len(selected_sections), len(selected_tables))):
        if index < len(selected_sections):
            blocks.append(selected_sections[index])
        if index < len(selected_tables):
            blocks.append(selected_tables[index])
    return _fit_blocks(blocks, max_chars=max_chars)


def _section_blocks(article: CleanedArticle, *, chunk_chars: int) -> list[EvidenceBlock]:
    blocks: list[EvidenceBlock] = []
    for section_index, section in enumerate(article.xml_content.sections, start=1):
        text = section.text.strip()
        if not text:
            continue
        section_id = section.section_id.strip() or f"section_{section_index}"
        title = section.title.strip() or "untitled section"
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", text)
            if paragraph.strip()
        ]
        if len(text) <= chunk_chars or len(paragraphs) <= 1:
            paragraphs = [text]
        cursor = 0
        for chunk_index, paragraph in enumerate(paragraphs, start=1):
            start = max(cursor, text.find(paragraph, cursor))
            cursor = start + len(paragraph)
            if len(paragraph) <= chunk_chars:
                chunk = paragraph
                coverage = (
                    "complete_section" if len(paragraphs) == 1 else "complete_paragraph"
                )
                kind = "section"
            else:
                chunk = paragraph[:chunk_chars]
                coverage = "partial_section_excerpt"
                kind = "section_excerpt"
            blocks.append(
                EvidenceBlock(
                    source_id=f"section:{section_id}:part:{chunk_index}",
                    kind=kind,
                    label=title,
                    text=chunk,
                    coverage=coverage,
                    start_char=start,
                    end_char=start + len(chunk),
                    total_chars=len(text),
                )
            )
    return blocks


def _table_blocks(article: CleanedArticle, *, block_chars: int) -> list[EvidenceBlock]:
    blocks: list[EvidenceBlock] = []
    for table_index, table in enumerate(article.tables, start=1):
        raw = str(table.raw_xml or "").strip()
        if not raw:
            # Older cached articles may retain the source in a compatibility
            # row. This is source recovery, not deterministic table parsing.
            raw = next(
                (
                    str(row.get("_raw_xml") or "").strip()
                    for row in table.rows
                    if isinstance(row, dict) and row.get("_raw_xml")
                ),
                "",
            )
        if not raw:
            continue
        table_id = table.table_id.strip() or f"table_{table_index}"
        label = table.caption.strip() or "caption unavailable"
        for chunk_index, chunk in enumerate(_chunks(raw, block_chars), start=1):
            start = (chunk_index - 1) * block_chars
            complete = len(raw) <= block_chars
            blocks.append(
                EvidenceBlock(
                    source_id=f"table:{table_id}:part:{chunk_index}",
                    kind="raw_table_xml",
                    label=label,
                    text=chunk,
                    coverage=("complete_table" if complete else "partial_table_slice"),
                    start_char=start,
                    end_char=start + len(chunk),
                    total_chars=len(raw),
                )
            )
    return blocks


def _task_terms(
    *,
    criteria: ScreeningCriteria,
    synthesis_plan: MetaAnalysisSynthesisPlan,
) -> set[str]:
    target_text = " ".join(
        " ".join(
            (
                target.population_scope,
                target.comparison.experimental,
                target.comparison.comparator,
                target.outcome.label,
                target.outcome.measure or "",
                target.timepoint.label or "",
            )
        )
        for target in synthesis_plan.targets
    )
    return _tokens(
        " ".join(
            [
                *criteria.inclusion_criteria,
                *criteria.exclusion_criteria,
                target_text,
            ]
        )
    )


def _tokens(value: str) -> set[str]:
    return {match.group(0).casefold() for match in _WORD_RE.finditer(value)}


def _score(block: EvidenceBlock, terms: set[str]) -> int:
    block_tokens = _tokens(f"{block.label} {block.text}")
    overlap = len(block_tokens & terms)
    numeric_signal = 2 if re.search(r"\b\d+(?:\.\d+)?\b", block.text) else 0
    result_signal = len(block_tokens & _NUMERIC_RESULT_TERMS)
    return overlap * 4 + result_signal + numeric_signal


def _is_abstract(block: EvidenceBlock) -> bool:
    text = f"{block.source_id} {block.label}".casefold()
    return "abstract" in text


def _chunks(text: str, size: int) -> list[str]:
    return [text[start : start + size] for start in range(0, len(text), size)]


def _fit_blocks(blocks: list[EvidenceBlock], *, max_chars: int) -> EvidenceBundle:
    fitted: list[EvidenceBlock] = []
    remaining = max_chars
    for block in blocks:
        if remaining <= 0:
            break
        if len(block.text) <= remaining:
            fitted.append(block)
            remaining -= len(block.text)
            continue
        if remaining < 400:
            continue
        text = block.text[:remaining]
        fitted.append(
            EvidenceBlock(
                source_id=f"{block.source_id}:budget_slice",
                kind=(
                    "raw_table_xml_slice"
                    if block.kind.startswith("raw_table")
                    else "section_excerpt"
                ),
                label=block.label,
                text=text,
                coverage=(
                    "partial_table_slice"
                    if block.kind.startswith("raw_table")
                    else "partial_section_excerpt"
                ),
                start_char=block.start_char,
                end_char=block.start_char + len(text),
                total_chars=block.total_chars or len(block.text),
            )
        )
        remaining -= len(text)
    return EvidenceBundle(blocks=fitted)


def _validate_limits(max_blocks: int, max_chars: int, chunk_chars: int) -> None:
    if max_blocks <= 0 or max_chars <= 0 or chunk_chars <= 0:
        raise ValueError("screening evidence limits must be positive")
