"""Immutable raw-source workspace used by the article evidence agent.

This module deliberately does not parse table structure or extract values.  It
only provides stable handles, exact transport windows, lexical navigation over
article prose, and source hashes used for trace/cache validity.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import html
import json
import re
from typing import Any, Iterable


DEFAULT_SOURCE_WINDOW_CHARS = 48_000
DEFAULT_SOURCE_OVERLAP_CHARS = 2_000
DEFAULT_SEARCH_WINDOW_CHARS = 1_600
DEFAULT_MAX_SEARCH_RESULTS = 12
_SCOPE_LINKAGE_MARKUP = (
    "<fn",
    "<table-wrap-foot",
    'ref-type="table-fn"',
    "ref-type='table-fn'",
)


@dataclass(frozen=True)
class RawSource:
    source_ref: str
    source_kind: str
    upstream_id: str
    title: str
    content: str
    source_hash: str
    order: int

    @property
    def char_count(self) -> int:
        return len(self.content)

    @property
    def has_scope_linkage_markup(self) -> bool:
        """Report source structure that warrants semantic scope review.

        This is only a routing signal.  It does not parse a footnote, bind it to
        a cell, or give it precedence over a header.
        """

        if self.source_kind != "table":
            return False
        lowered = self.content.casefold()
        return any(marker in lowered for marker in _SCOPE_LINKAGE_MARKUP)

    def manifest_row(self) -> dict[str, Any]:
        return {
            "source_ref": self.source_ref,
            "source_kind": self.source_kind,
            "upstream_id": self.upstream_id,
            "title": self.title,
            "char_count": self.char_count,
            "source_hash": self.source_hash,
            "order": self.order,
        }


@dataclass(frozen=True)
class SourceWindow:
    source_ref: str
    source_kind: str
    source_hash: str
    title: str
    start: int
    end: int
    content: str
    complete_source: bool
    window_index: int
    window_count: int

    def to_payload(self) -> dict[str, Any]:
        key = "raw_xml" if self.source_kind == "table" else "text"
        return {
            "source_ref": self.source_ref,
            "source_kind": self.source_kind,
            "source_hash": self.source_hash,
            "title": self.title,
            "transport": {
                "kind": "complete_source" if self.complete_source else "exact_window",
                "start": self.start,
                "end": self.end,
                "window_index": self.window_index,
                "window_count": self.window_count,
            },
            key: self.content,
        }


class SourceWorkspace:
    """Read-only article sources with stable, re-readable handles."""

    def __init__(
        self,
        *,
        study_id: str,
        tables: list[RawSource],
        sections: list[RawSource],
        warnings: list[str] | None = None,
    ) -> None:
        self.study_id = study_id
        self.tables = list(tables)
        self.sections = list(sections)
        self.warnings = list(warnings or [])
        all_sources = [*self.tables, *self.sections]
        refs = [row.source_ref for row in all_sources]
        if len(refs) != len(set(refs)):
            raise ValueError("Article source refs must be unique")
        self._by_ref = {row.source_ref: row for row in all_sources}

    @classmethod
    def from_article(
        cls,
        *,
        study_id: str,
        article: dict[str, Any],
    ) -> "SourceWorkspace":
        if str(article.get("study_id") or "") != study_id:
            raise ValueError("Article study_id does not match the evidence task")

        warnings: list[str] = []
        tables: list[RawSource] = []
        seen_table_ids: dict[str, int] = {}
        for index, raw in enumerate(article.get("tables") or []):
            if not isinstance(raw, dict):
                continue
            upstream_id = str(raw.get("table_id") or f"table-{index + 1}")
            count = seen_table_ids.get(upstream_id, 0) + 1
            seen_table_ids[upstream_id] = count
            source_ref = upstream_id if count == 1 else f"{upstream_id}-{count}"
            # `raw_xml` is the canonical article contract.  The row-level
            # escape is retained only for articles produced before that field
            # was formalized.
            content = str(raw.get("raw_xml") or _raw_xml_from_rows(raw) or "")
            if not content.strip():
                warnings.append(f"empty_raw_table:{source_ref}")
            tables.append(
                _source(
                    source_ref=source_ref,
                    source_kind="table",
                    upstream_id=upstream_id,
                    title=str(raw.get("caption") or ""),
                    content=content,
                    order=index,
                )
            )

        xml = (
            article.get("xml_content")
            if isinstance(article.get("xml_content"), dict)
            else {}
        )
        sections: list[RawSource] = []
        metadata = article.get("metadata") if isinstance(article.get("metadata"), dict) else {}
        article_title = str(metadata.get("title") or "").strip()
        if article_title:
            sections.append(
                _source(
                    source_ref=f"{study_id}::front::title",
                    source_kind="section",
                    upstream_id="article-title",
                    title=article_title,
                    content=article_title,
                    order=-1,
                )
            )
        for index, raw in enumerate(xml.get("sections") or []):
            if not isinstance(raw, dict):
                continue
            content = str(raw.get("text") or "")
            if not content.strip():
                continue
            upstream_id = str(raw.get("section_id") or f"section-{index + 1}")
            sections.append(
                _source(
                    source_ref=f"{study_id}::section::{index:04d}",
                    source_kind="section",
                    upstream_id=upstream_id,
                    title=str(raw.get("title") or ""),
                    content=content,
                    order=index,
                )
            )
        # A metadata title is useful semantic context but is not article evidence.
        # Keep the upstream full-text gate based on at least one real section or table.
        has_article_evidence = any(
            row.content.strip()
            for row in [*tables, *sections]
            if row.upstream_id != "article-title"
        )
        if not has_article_evidence:
            raise ValueError("Article contains no readable section or raw table source")
        return cls(
            study_id=study_id,
            tables=tables,
            sections=sections,
            warnings=warnings,
        )

    @property
    def table_refs(self) -> list[str]:
        return [row.source_ref for row in self.tables]

    @property
    def section_refs(self) -> list[str]:
        return [row.source_ref for row in self.sections]

    @property
    def front_matter_refs(self) -> list[str]:
        refs: list[str] = []
        for source in self.sections:
            normalized_id = source.upstream_id.strip().casefold()
            normalized_title = source.title.strip().casefold()
            if normalized_id == "article-title" or normalized_id == "abstract":
                refs.append(source.source_ref)
                continue
            if normalized_title == "abstract":
                refs.append(source.source_ref)
        return refs

    @property
    def article_hash(self) -> str:
        payload = [
            (row.source_ref, row.source_hash)
            for row in [*self.tables, *self.sections]
        ]
        return sha256(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

    def manifest(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "article_hash": self.article_hash,
            "tables": [row.manifest_row() for row in self.tables],
            "sections": [row.manifest_row() for row in self.sections],
            "warnings": list(self.warnings),
        }

    def source(self, source_ref: str) -> RawSource:
        try:
            return self._by_ref[source_ref]
        except KeyError as exc:
            raise ValueError(f"Unknown article source ref: {source_ref}") from exc

    def table_windows(
        self,
        *,
        max_window_chars: int = DEFAULT_SOURCE_WINDOW_CHARS,
        overlap_chars: int = DEFAULT_SOURCE_OVERLAP_CHARS,
        max_tables: int = 32,
    ) -> tuple[list[SourceWindow], list[str]]:
        selected = self.tables[:max_tables]
        omitted = [row.source_ref for row in self.tables[max_tables:]]
        windows = [
            window
            for source in selected
            if source.content.strip()
            for window in _windows(
                source,
                max_window_chars=max_window_chars,
                overlap_chars=overlap_chars,
            )
        ]
        return windows, omitted

    def bundle_windows(
        self,
        windows: Iterable[SourceWindow],
        *,
        max_sources: int,
        max_bundle_chars: int,
    ) -> list[list[SourceWindow]]:
        bundles: list[list[SourceWindow]] = []
        current: list[SourceWindow] = []
        used = 0
        for window in windows:
            size = len(window.content)
            if current and (
                len(current) >= max_sources or used + size > max_bundle_chars
            ):
                bundles.append(current)
                current = []
                used = 0
            current.append(window)
            used += size
        if current:
            bundles.append(current)
        return bundles

    def search_sections(
        self,
        queries: list[str],
        *,
        max_results: int = DEFAULT_MAX_SEARCH_RESULTS,
        window_chars: int = DEFAULT_SEARCH_WINDOW_CHARS,
        max_total_chars: int | None = None,
    ) -> list[dict[str, Any]]:
        if max_results <= 0:
            return []
        if max_total_chars is not None and max_total_chars <= 0:
            return []
        scored: list[tuple[float, int, int, str, dict[str, Any]]] = []
        for query_order, query in enumerate(_unique_text(queries)):
            query_tokens = _tokens(query)
            if not query_tokens:
                continue
            phrase = " ".join(str(query).casefold().split())
            for source in self.sections:
                lowered = source.content.casefold()
                positions = [lowered.find(token) for token in query_tokens]
                positions = [value for value in positions if value >= 0]
                if not positions:
                    continue
                matched = sum(lowered.count(token) for token in query_tokens)
                exact_position = lowered.find(phrase) if phrase else -1
                score = float(matched) + (8.0 if exact_position >= 0 else 0.0)
                anchor = exact_position if exact_position >= 0 else min(positions)
                start = max(0, anchor - window_chars // 2)
                end = min(len(source.content), start + window_chars)
                start = max(0, end - window_chars)
                row = {
                    "source_ref": source.source_ref,
                    "source_kind": "section",
                    "source_hash": source.source_hash,
                    "title": source.title,
                    "query": query,
                    "score": score,
                    "transport": {
                        "kind": "exact_search_window",
                        "start": start,
                        "end": end,
                        "complete_source": start == 0 and end == len(source.content),
                    },
                    "text": source.content[start:end],
                }
                scored.append((-score, query_order, source.order, source.source_ref, row))
        scored.sort(key=lambda item: item[:4])
        ranked: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()
        for _, _, _, _, row in scored:
            transport = row["transport"]
            key = (
                str(row["source_ref"]),
                int(transport["start"]),
                int(transport["end"]),
            )
            if key in seen:
                continue
            seen.add(key)
            ranked.append(row)

        result: list[dict[str, Any]] = []
        used_chars = 0
        limit_reason: str | None = None
        for index, row in enumerate(ranked):
            content = str(row.get("text") or "")
            if max_total_chars is not None and used_chars + len(content) > max_total_chars:
                limit_reason = "char_budget_limited"
                break
            result.append(row)
            used_chars += len(content)
            if len(result) >= max_results:
                if index + 1 < len(ranked):
                    limit_reason = "search_result_limited"
                break
        if limit_reason and result:
            _mark_transport_limit(result[-1], limit_reason)
        return result

    def read_sources(
        self,
        source_refs: list[str],
        *,
        max_window_chars: int = DEFAULT_SOURCE_WINDOW_CHARS,
        overlap_chars: int = DEFAULT_SOURCE_OVERLAP_CHARS,
        max_windows: int = 8,
        max_total_chars: int | None = None,
    ) -> list[dict[str, Any]]:
        if max_windows <= 0:
            return []
        if max_total_chars is not None and max_total_chars <= 0:
            return []
        payloads: list[dict[str, Any]] = []
        used_chars = 0
        char_budget_limited = False
        unique_refs = _unique_text(source_refs)
        for source_index, source_ref in enumerate(unique_refs):
            source = self.source(source_ref)
            for window in _windows(
                source,
                max_window_chars=max_window_chars,
                overlap_chars=overlap_chars,
            ):
                payload = window.to_payload()
                content = str(payload.get("raw_xml") or payload.get("text") or "")
                if max_total_chars is not None and used_chars + len(content) > max_total_chars:
                    # Do not cut a raw XML window in the middle of a tag.  The
                    # caller receives an explicit budget signal and can report
                    # incomplete supporting-source coverage.
                    char_budget_limited = True
                    break
                payloads.append(payload)
                used_chars += len(content)
                if len(payloads) >= max_windows:
                    more_windows_exist = (
                        window.window_index + 1 < window.window_count
                        or source_index + 1 < len(unique_refs)
                    )
                    if more_windows_exist:
                        _mark_transport_limit(
                            payloads[-1], "source_window_limited"
                        )
                    return payloads
        if char_budget_limited and payloads:
            _mark_transport_limit(payloads[-1], "char_budget_limited")
        return payloads

    def evidence_windows(
        self,
        *,
        evidence_locators: list[dict[str, Any]],
        max_window_chars: int = 12_000,
        max_windows: int | None = None,
        max_total_chars: int | None = None,
    ) -> list[dict[str, Any]]:
        """Re-read raw evidence around grounded transport windows.

        A quote copied from a rendered XML table is not necessarily a literal
        substring of the XML.  Locators therefore retain the exact transport
        window originally shown to the model.  Within that bounded window this
        method maps visible quote tokens back to raw offsets.  It performs no
        row/column interpretation or value extraction.
        """

        if max_window_chars < 1_000:
            raise ValueError("max_window_chars must be at least 1000")
        if max_windows is not None and max_windows <= 0:
            return []
        if max_total_chars is not None and max_total_chars <= 0:
            return []
        grouped: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for locator in evidence_locators:
            if not isinstance(locator, dict):
                continue
            source_ref = str(locator.get("source_ref") or "")
            if source_ref not in self._by_ref:
                continue
            if source_ref not in grouped:
                grouped[source_ref] = []
                order.append(source_ref)
            grouped[source_ref].append(locator)

        result: list[dict[str, Any]] = []
        used_chars = 0
        char_budget_limited = False
        for source_index, source_ref in enumerate(order):
            source = self.source(source_ref)
            intervals: list[tuple[int, int]] = []
            for locator in grouped[source_ref]:
                transport = locator.get("transport")
                if not isinstance(transport, dict):
                    transport = {}
                bound_start = _bounded_int(
                    transport.get("start"), lower=0, upper=len(source.content)
                )
                bound_end = _bounded_int(
                    transport.get("end"), lower=bound_start, upper=len(source.content)
                )
                if bound_end <= bound_start:
                    bound_start, bound_end = 0, len(source.content)
                quote = str(locator.get("source_quote") or "").strip()
                spans = _visible_quote_spans(
                    source.content[bound_start:bound_end],
                    quote=quote,
                    source_kind=source.source_kind,
                )
                if spans:
                    intervals.extend(
                        _window_around_span(
                            start=bound_start + start,
                            end=bound_start + end,
                            source_length=len(source.content),
                            max_window_chars=max_window_chars,
                        )
                        for start, end in spans
                    )
                else:
                    intervals.extend(
                        _split_interval(
                            start=bound_start,
                            end=bound_end,
                            max_window_chars=max_window_chars,
                        )
                    )
            merged = _merge_intervals(intervals)
            for index, (start, end) in enumerate(merged):
                payload = SourceWindow(
                        source_ref=source.source_ref,
                        source_kind=source.source_kind,
                        source_hash=source.source_hash,
                        title=source.title,
                        start=start,
                        end=end,
                        content=source.content[start:end],
                        complete_source=start == 0 and end == len(source.content),
                        window_index=index,
                        window_count=len(merged),
                    ).to_payload()
                content = str(payload.get("raw_xml") or payload.get("text") or "")
                if max_total_chars is not None and used_chars + len(content) > max_total_chars:
                    char_budget_limited = True
                    break
                result.append(payload)
                used_chars += len(content)
                if max_windows is not None and len(result) >= max_windows:
                    more_windows_exist = (
                        index + 1 < len(merged) or source_index + 1 < len(order)
                    )
                    if more_windows_exist:
                        _mark_transport_limit(
                            result[-1], "source_window_limited"
                        )
                    return result
            if char_budget_limited:
                break
        if char_budget_limited and result:
            _mark_transport_limit(result[-1], "char_budget_limited")
        return result

    def scope_audit_windows(
        self,
        *,
        source_refs: list[str],
        evidence_locators: list[dict[str, Any]],
        max_window_chars: int = DEFAULT_SOURCE_WINDOW_CHARS,
        overlap_chars: int = DEFAULT_SOURCE_OVERLAP_CHARS,
        max_windows: int = 24,
        max_total_chars: int = 160_000,
    ) -> list[dict[str, Any]]:
        """Assemble bounded raw context for one semantic scope audit.

        Complete sources are preferred.  When the group cannot fit, windows
        overlapping grounded evidence are selected first, followed by the first
        and last windows of each source and then remaining windows.  Selecting
        transport windows does not interpret table rows, columns, or values.
        """

        if max_windows <= 0 or max_total_chars <= 0:
            return []
        effective_overlap = min(
            max(0, overlap_chars), max(0, max_window_chars - 1)
        )
        unique_refs = [
            source_ref
            for source_ref in _unique_text(source_refs)
            if source_ref in self._by_ref
        ]
        windows_by_ref = {
            source_ref: _windows(
                self.source(source_ref),
                max_window_chars=max_window_chars,
                overlap_chars=effective_overlap,
            )
            for source_ref in unique_refs
        }
        all_windows = [
            window
            for source_ref in unique_refs
            for window in windows_by_ref[source_ref]
        ]
        if (
            len(all_windows) <= max_windows
            and sum(len(window.content) for window in all_windows) <= max_total_chars
        ):
            return [window.to_payload() for window in all_windows]

        locators_by_ref: dict[str, list[dict[str, Any]]] = {}
        for locator in evidence_locators:
            if not isinstance(locator, dict):
                continue
            source_ref = str(locator.get("source_ref") or "")
            if source_ref in windows_by_ref:
                locators_by_ref.setdefault(source_ref, []).append(locator)

        ranked: list[SourceWindow] = []
        seen: set[tuple[str, int, int]] = set()

        def add(window: SourceWindow) -> None:
            key = (window.source_ref, window.start, window.end)
            if key not in seen:
                seen.add(key)
                ranked.append(window)

        for source_ref in unique_refs:
            source = self.source(source_ref)
            for locator in locators_by_ref.get(source_ref, []):
                start, end = _locator_interval(source=source, locator=locator)
                for window in windows_by_ref[source_ref]:
                    if window.start < end and start < window.end:
                        add(window)
        for source_ref in unique_refs:
            source_windows = windows_by_ref[source_ref]
            if not source_windows:
                continue
            add(source_windows[0])
            add(source_windows[-1])
        for source_ref in unique_refs:
            for window in windows_by_ref[source_ref]:
                add(window)

        selected: list[SourceWindow] = []
        used_chars = 0
        char_budget_limited = False
        window_budget_limited = False
        for window in ranked:
            if len(selected) >= max_windows:
                window_budget_limited = True
                break
            if used_chars + len(window.content) > max_total_chars:
                char_budget_limited = True
                continue
            selected.append(window)
            used_chars += len(window.content)
        selected.sort(
            key=lambda row: (unique_refs.index(row.source_ref), row.window_index)
        )
        payloads = [window.to_payload() for window in selected]
        if len(selected) < len(all_windows) and payloads:
            if window_budget_limited:
                _mark_transport_limit(payloads[-1], "source_window_limited")
            if char_budget_limited:
                _mark_transport_limit(payloads[-1], "char_budget_limited")
        return payloads

    def source_bundle_coverage(
        self,
        *,
        source_refs: list[str],
        payloads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Describe raw transport coverage without judging evidence meaning."""

        requested = [
            source_ref
            for source_ref in _unique_text(source_refs)
            if source_ref in self._by_ref
        ]
        intervals_by_ref: dict[str, list[tuple[int, int]]] = {}
        for payload in payloads:
            source_ref = str(payload.get("source_ref") or "")
            if source_ref not in requested:
                continue
            transport = payload.get("transport")
            if not isinstance(transport, dict):
                continue
            source = self.source(source_ref)
            start = _bounded_int(
                transport.get("start"), lower=0, upper=len(source.content)
            )
            end = _bounded_int(
                transport.get("end"), lower=start, upper=len(source.content)
            )
            if end > start:
                intervals_by_ref.setdefault(source_ref, []).append((start, end))

        complete: list[str] = []
        partial: list[str] = []
        omitted: list[str] = []
        for source_ref in requested:
            intervals = _merge_intervals(intervals_by_ref.get(source_ref, []))
            if not intervals:
                omitted.append(source_ref)
                continue
            source_length = len(self.source(source_ref).content)
            cursor = 0
            for start, end in intervals:
                if start > cursor:
                    break
                cursor = max(cursor, end)
            if cursor >= source_length:
                complete.append(source_ref)
            else:
                partial.append(source_ref)
        limit_reasons = _payload_limit_reasons(payloads)
        return {
            "requested_source_refs": requested,
            "complete_source_refs": complete,
            "partial_source_refs": partial,
            "omitted_source_refs": omitted,
            "context_budget_exceeded": bool(partial or omitted)
            or any(bool(row.get("context_budget_exceeded")) for row in payloads),
            "char_budget_limited": "char_budget_limited" in limit_reasons,
            "source_window_limited": "source_window_limited" in limit_reasons,
            "search_result_limited": "search_result_limited" in limit_reasons,
            "source_content_partial": bool(partial or omitted),
            "transport_limit_reasons": limit_reasons,
        }


def _mark_transport_limit(payload: dict[str, Any], reason: str) -> None:
    reasons = [
        str(value)
        for value in payload.get("transport_limit_reasons") or []
        if str(value)
    ]
    if reason not in reasons:
        reasons.append(reason)
    payload["transport_limit_reasons"] = reasons
    # Retain the established transport flag for serialized compatibility.
    # Runtime routing reads the typed reasons instead of treating every cap as
    # a provider context-window overflow.
    payload["context_budget_exceeded"] = True


def _payload_limit_reasons(payloads: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for payload in payloads:
        for reason in payload.get("transport_limit_reasons") or []:
            normalized = str(reason or "").strip()
            if normalized and normalized not in result:
                result.append(normalized)
    return result


def _source(
    *,
    source_ref: str,
    source_kind: str,
    upstream_id: str,
    title: str,
    content: str,
    order: int,
) -> RawSource:
    return RawSource(
        source_ref=source_ref,
        source_kind=source_kind,
        upstream_id=upstream_id,
        title=title,
        content=content,
        source_hash=sha256(content.encode("utf-8")).hexdigest(),
        order=order,
    )


def _raw_xml_from_rows(table: dict[str, Any]) -> str | None:
    for row in table.get("rows") or []:
        if isinstance(row, dict) and row.get("_raw_xml"):
            return str(row["_raw_xml"])
    return None


def _locator_interval(
    *,
    source: RawSource,
    locator: dict[str, Any],
) -> tuple[int, int]:
    transport = locator.get("transport")
    if not isinstance(transport, dict):
        transport = {}
    bound_start = _bounded_int(
        transport.get("start"), lower=0, upper=len(source.content)
    )
    bound_end = _bounded_int(
        transport.get("end"), lower=bound_start, upper=len(source.content)
    )
    if bound_end <= bound_start:
        bound_start, bound_end = 0, len(source.content)
    spans = _visible_quote_spans(
        source.content[bound_start:bound_end],
        quote=str(locator.get("source_quote") or "").strip(),
        source_kind=source.source_kind,
    )
    if not spans:
        return bound_start, bound_end
    return (
        bound_start + min(start for start, _ in spans),
        bound_start + max(end for _, end in spans),
    )


def _visible_quote_spans(
    content: str,
    *,
    quote: str,
    source_kind: str,
) -> list[tuple[int, int]]:
    """Locate rendered quote fragments while preserving raw offsets."""

    if not quote:
        return []
    exact = content.find(quote)
    if exact >= 0:
        return [(exact, exact + len(quote))]

    rendered, raw_offsets = _visible_text_with_raw_offsets(
        content, source_kind=source_kind
    )
    source_tokens = [
        (match.group(0).casefold(), match.start(), match.end())
        for match in re.finditer(r"[A-Za-z0-9]+", rendered)
    ]
    fragments = [
        [token.casefold() for token in re.findall(r"[A-Za-z0-9]+", fragment)]
        for fragment in re.split(r"\s*(?:\.\.\.|\u2026)\s*", html.unescape(quote))
    ]
    fragments = [fragment for fragment in fragments if fragment]
    if not source_tokens or not fragments:
        return []

    spans: list[tuple[int, int]] = []
    cursor = 0
    token_values = [token for token, _, _ in source_tokens]
    for fragment in fragments:
        found = _find_token_sequence(token_values, fragment, start=cursor)
        if found is not None:
            first_index = found
            last_index = found + len(fragment) - 1
            cursor = last_index + 1
        else:
            ordered = _find_ordered_token_sequence(
                token_values, fragment, start=cursor
            )
            if ordered is None:
                return []
            first_index, last_index = ordered
            cursor = last_index + 1
        first = source_tokens[first_index]
        last = source_tokens[last_index]
        raw_start = raw_offsets[first[1]]
        raw_end = raw_offsets[last[2] - 1] + 1
        spans.append((raw_start, raw_end))
    return spans


def _visible_text_with_raw_offsets(
    content: str,
    *,
    source_kind: str,
) -> tuple[str, list[int]]:
    if source_kind != "table":
        return content, list(range(len(content)))

    characters: list[str] = []
    offsets: list[int] = []
    index = 0
    while index < len(content):
        if content[index] == "<":
            end = content.find(">", index + 1)
            if end >= 0:
                characters.append(" ")
                offsets.append(index)
                index = end + 1
                continue
        if content[index] == "&":
            end = content.find(";", index + 1, min(len(content), index + 32))
            if end >= 0:
                decoded = html.unescape(content[index : end + 1])
                if decoded != content[index : end + 1]:
                    characters.extend(decoded)
                    offsets.extend([index] * len(decoded))
                    index = end + 1
                    continue
        characters.append(content[index])
        offsets.append(index)
        index += 1
    return "".join(characters), offsets


def _find_token_sequence(
    source: list[str],
    expected: list[str],
    *,
    start: int,
) -> int | None:
    limit = len(source) - len(expected) + 1
    for index in range(start, max(start, limit)):
        if source[index : index + len(expected)] == expected:
            return index
    return None


def _find_ordered_token_sequence(
    source: list[str],
    expected: list[str],
    *,
    start: int,
) -> tuple[int, int] | None:
    if not expected:
        return None
    first_index: int | None = None
    cursor = start
    for token in expected:
        try:
            index = source.index(token, cursor)
        except ValueError:
            return None
        if first_index is None:
            first_index = index
        cursor = index + 1
    return first_index, cursor - 1


def _window_around_span(
    *,
    start: int,
    end: int,
    source_length: int,
    max_window_chars: int,
) -> tuple[int, int]:
    if end - start >= max_window_chars:
        return start, min(source_length, start + max_window_chars)
    window_start = max(0, start - max_window_chars // 3)
    window_end = min(source_length, window_start + max_window_chars)
    window_start = max(0, window_end - max_window_chars)
    return window_start, window_end


def _split_interval(
    *,
    start: int,
    end: int,
    max_window_chars: int,
) -> list[tuple[int, int]]:
    return [
        (offset, min(end, offset + max_window_chars))
        for offset in range(start, end, max_window_chars)
    ]


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(set(intervals)):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _bounded_int(value: Any, *, lower: int, upper: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return lower
    return min(upper, max(lower, number))


def _windows(
    source: RawSource,
    *,
    max_window_chars: int,
    overlap_chars: int,
) -> list[SourceWindow]:
    if max_window_chars < 1_000:
        raise ValueError("max_window_chars must be at least 1000")
    if not 0 <= overlap_chars < max_window_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than the window")
    content = source.content
    if len(content) <= max_window_chars:
        return [
            SourceWindow(
                source_ref=source.source_ref,
                source_kind=source.source_kind,
                source_hash=source.source_hash,
                title=source.title,
                start=0,
                end=len(content),
                content=content,
                complete_source=True,
                window_index=0,
                window_count=1,
            )
        ]
    step = max_window_chars - overlap_chars
    starts = list(range(0, len(content), step))
    if starts and starts[-1] + max_window_chars >= len(content):
        pass
    windows: list[SourceWindow] = []
    for index, start in enumerate(starts):
        end = min(len(content), start + max_window_chars)
        windows.append(
            SourceWindow(
                source_ref=source.source_ref,
                source_kind=source.source_kind,
                source_hash=source.source_hash,
                title=source.title,
                start=start,
                end=end,
                content=content[start:end],
                complete_source=False,
                window_index=index,
                window_count=len(starts),
            )
        )
        if end == len(content):
            break
    count = len(windows)
    return [
        SourceWindow(
            source_ref=row.source_ref,
            source_kind=row.source_kind,
            source_hash=row.source_hash,
            title=row.title,
            start=row.start,
            end=row.end,
            content=row.content,
            complete_source=row.complete_source,
            window_index=row.window_index,
            window_count=count,
        )
        for row in windows
    ]


def _tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(value).casefold())
        if len(token) >= 2
    ]


def _unique_text(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
