"""Bounded, lossless evidence packing for article-type qualification.

No table values are parsed or normalized here.  Complete raw table XML or an
explicitly labelled exact substring is passed to the model.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleEvidenceCoverage,
)


EVIDENCE_PACK_VERSION = "article_type_evidence_v1"
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_TYPE_TERMS = {
    "allocation",
    "arms",
    "assigned",
    "baseline",
    "control",
    "enrollment",
    "flow",
    "intervention",
    "methods",
    "outcomes",
    "participants",
    "randomized",
    "randomised",
    "results",
    "trial",
}


@dataclass(frozen=True)
class QualificationEvidenceBlock:
    source_id: str
    kind: str
    label: str
    text: str
    coverage: str
    start_char: int
    end_char: int
    total_chars: int


@dataclass(frozen=True)
class QualificationEvidenceBundle:
    blocks: list[QualificationEvidenceBlock]
    coverage: ArticleEvidenceCoverage

    @property
    def sources(self) -> dict[str, str]:
        return {block.source_id: block.text for block in self.blocks}

    def format(self) -> str:
        if not self.blocks:
            return "[No usable article content]"
        return "\n\n".join(
            (
                f"[SOURCE {block.source_id} | {block.kind} | {block.coverage} | "
                f"chars {block.start_char}:{block.end_char}/{block.total_chars} | "
                f"{block.label}]\n{block.text}"
            )
            for block in self.blocks
        )


def estimate_tokens(value: str) -> int:
    """Conservative dependency-free estimate for predominantly English XML."""

    if not value:
        return 0
    return max(1, (len(value.encode("utf-8")) + 3) // 4)


def resolve_input_token_budget(config: object) -> int:
    if isinstance(config, dict):
        context = int(config.get("context_window_tokens") or 128_000)
        configured = int(config.get("screening_input_token_budget") or 48_000)
    else:
        context = int(getattr(config, "context_window_tokens", 128_000))
        configured = int(
            getattr(config, "screening_input_token_budget", 48_000)
        )
    # Reserve response, schema/system prompt, and provider headroom.
    return max(4_000, min(configured, context - 16_000))


def build_qualification_evidence(
    *,
    article: CleanedArticle,
    input_token_budget: int,
) -> QualificationEvidenceBundle:
    if input_token_budget <= 0:
        raise ValueError("input_token_budget must be positive")

    blocks: list[QualificationEvidenceBlock] = []
    remaining = input_token_budget
    title = article.metadata.title.strip()
    if title:
        remaining = _append_if_fits(
            blocks,
            QualificationEvidenceBlock(
                source_id="title",
                kind="title",
                label="article title",
                text=title,
                coverage="complete",
                start_char=0,
                end_char=len(title),
                total_chars=len(title),
            ),
            remaining,
        )

    ranked_tables = sorted(
        _raw_tables(article),
        key=lambda item: (-_score(item[1], item[2]), item[0]),
    )
    # Article typing can require both design prose and results tables. Reserve
    # one third of the shared budget when raw tables exist so prose cannot
    # silently consume the whole context.
    table_reserve = remaining // 3 if ranked_tables else 0
    prose_remaining = remaining - table_reserve
    section_units = _section_units(article)
    abstracts = [unit for unit in section_units if _is_abstract(unit)]
    ranked_sections = sorted(
        (unit for unit in section_units if unit not in abstracts),
        key=lambda unit: (-_score(unit.label, unit.text), unit.source_id),
    )
    for unit in [*abstracts, *ranked_sections]:
        if prose_remaining <= 0:
            break
        prose_remaining = _append_or_excerpt(blocks, unit, prose_remaining)

    remaining = prose_remaining + table_reserve

    complete_tables: list[str] = []
    partial_tables: list[str] = []
    unread_tables: list[str] = []
    for table_id, caption, raw_xml in ranked_tables:
        if remaining <= 0:
            unread_tables.append(table_id)
            continue
        complete = QualificationEvidenceBlock(
            source_id=f"table:{table_id}",
            kind="raw_table_xml",
            label=caption or "caption unavailable",
            text=raw_xml,
            coverage="complete_table",
            start_char=0,
            end_char=len(raw_xml),
            total_chars=len(raw_xml),
        )
        if estimate_tokens(raw_xml) <= remaining:
            blocks.append(complete)
            remaining -= estimate_tokens(raw_xml)
            complete_tables.append(table_id)
            continue
        slice_block = _best_exact_table_slice(
            table_id=table_id,
            caption=caption,
            raw_xml=raw_xml,
            token_budget=remaining,
        )
        if slice_block is None:
            unread_tables.append(table_id)
            continue
        blocks.append(slice_block)
        remaining -= estimate_tokens(slice_block.text)
        partial_tables.append(table_id)

    selected_section_ids = {
        block.source_id.split(":part:", 1)[0].removeprefix("section:")
        for block in blocks
        if block.kind in {"section", "section_excerpt"}
    }
    complete_sections = sorted(
        {
            block.source_id.split(":part:", 1)[0].removeprefix("section:")
            for block in blocks
            if block.kind == "section" and block.coverage == "complete_section"
        }
    )
    partial_sections = sorted(selected_section_ids - set(complete_sections))
    used_tokens = input_token_budget - remaining
    return QualificationEvidenceBundle(
        blocks=blocks,
        coverage=ArticleEvidenceCoverage(
            complete_section_ids=complete_sections,
            partial_section_ids=partial_sections,
            complete_table_ids=complete_tables,
            partial_table_ids=partial_tables,
            unread_table_ids=unread_tables,
            input_token_estimate=used_tokens,
            input_token_budget=input_token_budget,
        ),
    )


def _section_units(article: CleanedArticle) -> list[QualificationEvidenceBlock]:
    units: list[QualificationEvidenceBlock] = []
    for index, section in enumerate(article.xml_content.sections, start=1):
        text = section.text.strip()
        if not text:
            continue
        section_id = section.section_id.strip() or f"section_{index}"
        label = section.title.strip() or "untitled section"
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if len(paragraphs) <= 1:
            units.append(
                QualificationEvidenceBlock(
                    source_id=f"section:{section_id}",
                    kind="section",
                    label=label,
                    text=text,
                    coverage="complete_section",
                    start_char=0,
                    end_char=len(text),
                    total_chars=len(text),
                )
            )
            continue
        cursor = 0
        for paragraph_index, paragraph in enumerate(paragraphs, start=1):
            start = text.find(paragraph, cursor)
            start = max(start, cursor)
            end = start + len(paragraph)
            cursor = end
            units.append(
                QualificationEvidenceBlock(
                    source_id=f"section:{section_id}:part:{paragraph_index}",
                    kind="section",
                    label=label,
                    text=paragraph,
                    coverage="complete_paragraph",
                    start_char=start,
                    end_char=end,
                    total_chars=len(text),
                )
            )
    return units


def _raw_tables(article: CleanedArticle) -> list[tuple[str, str, str]]:
    tables: list[tuple[str, str, str]] = []
    for index, table in enumerate(article.tables, start=1):
        raw_xml = str(table.raw_xml or "").strip()
        if not raw_xml:
            continue
        tables.append(
            (
                table.table_id.strip() or f"table_{index}",
                table.caption.strip(),
                raw_xml,
            )
        )
    return tables


def _append_if_fits(
    blocks: list[QualificationEvidenceBlock],
    block: QualificationEvidenceBlock,
    remaining: int,
) -> int:
    cost = estimate_tokens(block.text)
    if cost <= remaining:
        blocks.append(block)
        return remaining - cost
    return remaining


def _append_or_excerpt(
    blocks: list[QualificationEvidenceBlock],
    block: QualificationEvidenceBlock,
    remaining: int,
) -> int:
    cost = estimate_tokens(block.text)
    if cost <= remaining:
        blocks.append(block)
        return remaining - cost
    char_budget = remaining * 4
    if char_budget < 400:
        return remaining
    text = block.text[:char_budget]
    blocks.append(
        QualificationEvidenceBlock(
            source_id=f"{block.source_id}:excerpt",
            kind="section_excerpt",
            label=block.label,
            text=text,
            coverage="partial_section_excerpt",
            start_char=block.start_char,
            end_char=block.start_char + len(text),
            total_chars=block.total_chars,
        )
    )
    return remaining - estimate_tokens(text)


def _best_exact_table_slice(
    *,
    table_id: str,
    caption: str,
    raw_xml: str,
    token_budget: int,
) -> QualificationEvidenceBlock | None:
    char_budget = token_budget * 4
    if char_budget < 800:
        return None
    if len(raw_xml) <= char_budget:
        start = 0
    else:
        terms = sorted(_TYPE_TERMS)
        positions = [raw_xml.casefold().find(term) for term in terms]
        positions = [position for position in positions if position >= 0]
        center = min(positions) if positions else 0
        start = max(0, min(center - char_budget // 4, len(raw_xml) - char_budget))
    end = min(len(raw_xml), start + char_budget)
    text = raw_xml[start:end]
    return QualificationEvidenceBlock(
        source_id=f"table:{table_id}:slice:{start}:{end}",
        kind="raw_table_xml_slice",
        label=caption or "caption unavailable",
        text=text,
        coverage="partial_table_slice",
        start_char=start,
        end_char=end,
        total_chars=len(raw_xml),
    )


def _is_abstract(block: QualificationEvidenceBlock) -> bool:
    return "abstract" in f"{block.source_id} {block.label}".casefold()


def _score(label: str, text: str) -> int:
    tokens = {match.group(0).casefold() for match in _WORD_RE.finditer(f"{label} {text}")}
    return len(tokens & _TYPE_TERMS) * 4 + int(bool(re.search(r"\b\d+\b", text)))
