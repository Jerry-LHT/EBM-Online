"""Text source packing for targeted extraction.

This module partitions article text into non-overlapping text bundles.
It preserves raw titles/body only and performs no semantic filtering.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any


DEFAULT_TEXT_BUNDLE_MAX_CHARS = 5000
DEFAULT_TEXT_BUNDLE_TARGET_CHARS = 3000
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.;:!?])\s+")


@dataclass(frozen=True)
class TextSourceUnit:
    section_id: str
    title: str | None
    paragraph_start: int
    paragraph_end: int
    piece_index: int
    text: str


def list_text_sources(article: dict[str, Any]) -> list[dict[str, Any]]:
    units = _text_source_units(article)
    sources: list[dict[str, Any]] = []
    for index, unit in enumerate(units, start=1):
        text = _unit_prompt_text(unit)
        sources.append(
            {
                "source_id": f"text::{index}",
                "source_type": "text",
                "section_id": unit.section_id,
                "text": text,
                "char_count": len(text),
                "section_ids": [unit.section_id],
                "text_unit_ids": [f"{unit.section_id}#p{unit.paragraph_start}-{unit.paragraph_end}#{unit.piece_index}"],
                "paragraph_start": unit.paragraph_start,
                "paragraph_end": unit.paragraph_end,
                "piece_index": unit.piece_index,
                "text_hash": _hash_text(text),
                "coverage_unit_count": max(1, unit.paragraph_end - unit.paragraph_start + 1),
            }
        )
    return sources


def _text_source_units(article: dict[str, Any]) -> list[TextSourceUnit]:
    raw_sections = _raw_sections(article)
    units: list[TextSourceUnit] = []
    for section_position, (section_id, title, body) in enumerate(raw_sections, start=1):
        chunks = _section_chunks(
            _paragraphs(body),
            target_chars=_target_chars(),
            limit=_limit_chars(),
        )
        for paragraph_start, paragraph_end, chunk in chunks:
            for piece_index, piece in enumerate(_split_long_text(chunk, limit=_limit_chars()), start=1):
                clean_piece = piece.strip()
                if not clean_piece:
                    continue
                units.append(
                    TextSourceUnit(
                        section_id=section_id or f"s{section_position}",
                        title=title,
                        paragraph_start=paragraph_start,
                        paragraph_end=paragraph_end,
                        piece_index=piece_index,
                        text=clean_piece,
                    )
                )
    return units


def _raw_sections(article: dict[str, Any]) -> list[tuple[str, str | None, str]]:
    sections = ((article.get("xml_content") or {}).get("sections")) or []
    raw_sections: list[tuple[str, str | None, str]] = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        body = _text(section.get("text"))
        if not body:
            continue
        section_id = _text(section.get("section_id")) or f"s{index + 1}"
        title = _text(section.get("title"))
        raw_sections.append((section_id, title, body))
    if raw_sections:
        return raw_sections
    fallback = _fallback_text(article)
    return [("text", None, fallback)] if fallback else []


def _paragraphs(text: str) -> list[str]:
    clean = _normalize_newlines(text)
    if not clean:
        return []
    paragraphs = re.split(r"\n\s*\n+", clean)
    if len(paragraphs) == 1:
        paragraphs = clean.split("\n")
    return [paragraph.strip() for paragraph in paragraphs if paragraph and paragraph.strip()]


def _section_chunks(paragraphs: list[str], *, target_chars: int, limit: int) -> list[tuple[int, int, str]]:
    chunks: list[tuple[int, int, str]] = []
    current: list[str] = []
    start_index = 1
    current_chars = 0
    for paragraph_index, paragraph in enumerate(paragraphs, start=1):
        paragraph_chars = len(paragraph)
        if current and (current_chars + paragraph_chars + 2 > target_chars):
            chunks.append((start_index, paragraph_index - 1, "\n\n".join(current).strip()))
            current = []
            current_chars = 0
            start_index = paragraph_index
        if paragraph_chars > limit:
            if current:
                chunks.append((start_index, paragraph_index - 1, "\n\n".join(current).strip()))
                current = []
                current_chars = 0
            chunks.append((paragraph_index, paragraph_index, paragraph))
            start_index = paragraph_index + 1
            continue
        current.append(paragraph)
        current_chars += paragraph_chars + 2
    if current:
        chunks.append((start_index, start_index + len(current) - 1, "\n\n".join(current).strip()))
    return [chunk for chunk in chunks if chunk[2]]


def _unit_prompt_text(unit: TextSourceUnit) -> str:
    if unit.title:
        return f"{unit.title}\n{unit.text}".strip()
    return unit.text


def _split_long_text(text: str, *, limit: int) -> list[str]:
    clean = _normalize_newlines(text)
    if len(clean) <= limit:
        return [clean]
    return _pack_segments(_recursive_segments(clean, limit=limit), limit=limit)


def _recursive_segments(text: str, *, limit: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    for pattern in (r"\n\s*\n+", r"\n+", _SENTENCE_BOUNDARY_RE):
        parts = _split_by_pattern(text, pattern)
        if len(parts) > 1:
            segments: list[str] = []
            for part in parts:
                segments.extend(_recursive_segments(part, limit=limit))
            return segments
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def _split_by_pattern(text: str, pattern: str | re.Pattern[str]) -> list[str]:
    if isinstance(pattern, str):
        pieces = re.split(pattern, text)
    else:
        pieces = pattern.split(text)
    return [piece.strip() for piece in pieces if piece and piece.strip()]


def _pack_segments(segments: list[str], *, limit: int) -> list[str]:
    packed: list[str] = []
    current: list[str] = []
    current_chars = 0
    for segment in segments:
        if not segment:
            continue
        if current and current_chars + len(segment) + 2 > limit:
            packed.append("\n\n".join(current).strip())
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += len(segment) + 2
    if current:
        packed.append("\n\n".join(current).strip())
    return packed


def _fallback_text(article: dict[str, Any]) -> str | None:
    candidates = [
        article.get("text"),
        article.get("full_text"),
        (article.get("xml_content") or {}).get("text") if isinstance(article.get("xml_content"), dict) else None,
        (article.get("metadata") or {}).get("abstract") if isinstance(article.get("metadata"), dict) else None,
    ]
    for candidate in candidates:
        text = _text(candidate)
        if text:
            return text
    return None


def _normalize_newlines(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _limit_chars() -> int:
    raw = os.environ.get("SUBTASK2_TARGETED_TEXT_BUNDLE_MAX_CHARS")
    if raw and raw.strip():
        try:
            return max(1000, int(raw))
        except ValueError:
            pass
    return DEFAULT_TEXT_BUNDLE_MAX_CHARS


def _target_chars() -> int:
    raw = os.environ.get("SUBTASK2_TARGETED_TEXT_BUNDLE_TARGET_CHARS")
    if raw and raw.strip():
        try:
            return max(800, int(raw))
        except ValueError:
            pass
    return DEFAULT_TEXT_BUNDLE_TARGET_CHARS


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
