"""Source catalog helpers for targeted extraction."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.tools.text_source_packer import (
    list_text_sources,
)


def build_source_catalog(article: dict[str, Any]) -> list[dict[str, Any]]:
    return [*list_table_sources(article), *list_text_sources(article)]


def list_table_sources(article: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for index, table in enumerate(article.get("tables") or []):
        if not isinstance(table, dict):
            continue
        raw_xml = table.get("raw_xml")
        if not isinstance(raw_xml, str) or not raw_xml.strip():
            continue
        table_id = _text(table.get("table_id")) or f"t{index + 1}"
        sources.append(
            {
                "source_id": f"table::{table_id}",
                "source_type": "table",
                "table_id": table_id,
                "raw_xml": raw_xml.strip(),
                "char_count": len(raw_xml),
            }
        )
    return sources


def source_payload(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("source_type") == "table":
        return {
            "source_id": source.get("source_id"),
            "source_type": "table",
            "raw_xml": source.get("raw_xml"),
        }
    return {
        "source_id": source.get("source_id"),
        "source_type": "text",
        "text": source.get("text"),
    }


def source_summary(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "char_count": source.get("char_count"),
        "section_id": source.get("section_id"),
        "section_ids": source.get("section_ids"),
        "text_unit_ids": source.get("text_unit_ids"),
        "paragraph_start": source.get("paragraph_start"),
        "paragraph_end": source.get("paragraph_end"),
        "piece_index": source.get("piece_index"),
        "text_hash": source.get("text_hash"),
        "coverage_unit_count": source.get("coverage_unit_count"),
        "table_id": source.get("table_id"),
    }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
