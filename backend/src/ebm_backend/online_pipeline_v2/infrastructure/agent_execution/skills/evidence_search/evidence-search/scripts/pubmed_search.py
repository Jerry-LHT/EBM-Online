#!/usr/bin/env python3
"""Execute one PubMed search and write a source-result.v2 artifact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree


EUTILS_ROOT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_PUBMED_TOOL_EMAIL = "ebm-online-pipeline@example.com"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query-file", required=True, type=Path)
    parser.add_argument("--narrative-file", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--platform", default="PubMed")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-records", type=int, default=10_000)
    args = parser.parse_args()

    query = args.query_file.read_text(encoding="utf-8").strip()
    narrative = (
        args.narrative_file.read_text(encoding="utf-8").strip()
        if args.narrative_file
        else "PubMed query executed through E-utilities."
    )
    if not query:
        raise SystemExit("query file is empty")
    if not narrative:
        raise SystemExit("narrative file is empty")
    if args.page_size < 1 or args.page_size > 10_000:
        raise SystemExit("page-size must be between 1 and 10000")
    if args.max_records < 1:
        raise SystemExit("max-records must be positive")

    client = PubMedClient(
        email=os.getenv("PUBMED_TOOL_EMAIL", DEFAULT_PUBMED_TOOL_EMAIL).strip(),
        api_key=os.getenv("NCBI_API_KEY", "").strip() or None,
    )
    result = client.search(
        query=query,
        search_narrative=narrative,
        run_id=args.run_id,
        source_name=args.source_name,
        platform=args.platform,
        page_size=args.page_size,
        max_records=args.max_records,
    )
    _write_json(args.output, result)
    return 0


class PubMedClient:
    def __init__(self, *, email: str, api_key: str | None) -> None:
        if not email or "@" not in email:
            raise SystemExit("PUBMED_TOOL_EMAIL must contain a valid contact email")
        self.email = email
        self.api_key = api_key
        self._last_request_at = 0.0

    def search(
        self,
        *,
        query: str,
        search_narrative: str = "PubMed query executed through E-utilities.",
        run_id: str,
        source_name: str,
        platform: str,
        page_size: int,
        max_records: int,
    ) -> dict[str, object]:
        digest = sha256()
        count_body = self._request(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": query,
                "retmode": "xml",
                "retmax": "0",
            },
        )
        digest.update(count_body)
        count_root = ElementTree.fromstring(count_body)
        total = _required_nonnegative_int(
            count_root.findtext("./Count"),
            "PubMed Count",
        )
        query_translation = _node_text(count_root.find("./QueryTranslation"))
        warnings = [
            value
            for node in count_root.findall("./WarningList/*")
            if (value := _node_text(node))
        ]
        target = min(total, max_records)
        records: list[dict[str, object]] = []

        for start in range(0, target, page_size):
            requested = min(page_size, target - start)
            page_body = self._request(
                "esearch.fcgi",
                {
                    "db": "pubmed",
                    "term": query,
                    "retmode": "xml",
                    "retstart": str(start),
                    "retmax": str(requested),
                },
            )
            digest.update(page_body)
            page_root = ElementTree.fromstring(page_body)
            pmids = [
                (node.text or "").strip()
                for node in page_root.findall("./IdList/Id")
                if (node.text or "").strip()
            ]
            if not pmids:
                break
            fetch_body = self._request(
                "efetch.fcgi",
                {
                    "db": "pubmed",
                    "id": ",".join(pmids),
                    "retmode": "xml",
                },
            )
            digest.update(fetch_body)
            records.extend(
                _parse_records(
                    fetch_body,
                    run_id=run_id,
                    source_name=source_name,
                    platform=platform,
                )
            )

        status = "succeeded" if len(records) == total else "partial"
        status_reason = _incomplete_export_reason(
            retrieved=len(records),
            total=total,
            target=target,
            max_records=max_records,
        )
        locator = f"{EUTILS_ROOT}/esearch.fcgi"
        response_digest = f"sha256:{digest.hexdigest()}"
        provenance = [
            {
                "source_id": "pubmed",
                "source_type": f"search_source:{platform}",
                "locator": locator,
                "excerpt": (f"result_count={total};retrieved_count={len(records)}"),
            },
            {
                "source_id": response_digest,
                "source_type": "search_source_response_digest",
                "locator": locator,
                "excerpt": None,
            },
        ]
        return {
            "schema_version": "source-result.v2",
            "search_run": {
                "search_run_id": run_id,
                "source_name": source_name,
                "platform": platform,
                "query": query,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "status": status,
                "result_count": total,
                "retrieved_count": len(records),
                "status_reason": status_reason,
                "search_narrative": search_narrative,
                "provenance": provenance,
            },
            "records": records,
            "tool_observation": {
                "tool": "pubmed-eutilities",
                "retrieved_count": len(records),
                "truncated": len(records) < total,
                "limited_by_safety_ceiling": total > max_records,
                "incomplete_export": len(records) < target,
                "query_translation": query_translation,
                "warnings": warnings,
                "response_digest": response_digest,
            },
        }

    def _request(self, endpoint: str, params: dict[str, str]) -> bytes:
        interval = 0.1 if self.api_key else 1 / 3
        remaining = interval - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        payload = {
            **params,
            "tool": "ebm_online_pipeline_v2",
            "email": self.email,
        }
        if self.api_key:
            payload["api_key"] = self.api_key
        request = Request(
            f"{EUTILS_ROOT}/{endpoint}",
            data=urlencode(payload).encode("utf-8"),
            headers={
                "Accept": "application/xml",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": (f"ebm_online_pipeline_v2/1.0 ({self.email})"),
            },
            method="POST",
        )
        with urlopen(request, timeout=45.0) as response:
            body = response.read()
        self._last_request_at = time.monotonic()
        return body


def _parse_records(
    body: bytes,
    *,
    run_id: str,
    source_name: str,
    platform: str,
) -> list[dict[str, object]]:
    root = ElementTree.fromstring(body)
    records: list[dict[str, object]] = []
    for article in root.findall("./PubmedArticle"):
        pmid = _text(article, "./MedlineCitation/PMID")
        if not pmid:
            continue
        records.append(
            {
                "record_id": f"pubmed:{pmid}",
                "source_name": source_name,
                "platform": platform,
                "source_record_id": pmid,
                "source_record_type": "bibliographic_record",
                "source_data": {},
                "title": _node_text(
                    article.find("./MedlineCitation/Article/ArticleTitle")
                ),
                "citation": _citation(article),
                "abstract": _abstract(article),
                "external_identifiers": _identifiers(
                    article,
                    pmid,
                    ("./PubmedData/ArticleIdList/ArticleId",),
                ),
                "publication_types": _publication_types(article),
                "related_records": _related_records(article),
                "locators": [f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"],
                "search_run_ids": [run_id],
                "provenance": [
                    {
                        "source_id": "pubmed",
                        "source_type": f"search_source:{platform}",
                        "locator": (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"),
                        "excerpt": f"pmid={pmid}",
                    }
                ],
            }
        )
    for article in root.findall("./PubmedBookArticle"):
        document = article.find("./BookDocument")
        pmid = _text(article, "./BookDocument/PMID")
        if document is None or not pmid:
            continue
        book_title = _text(document, "./Book/BookTitle")
        source_data: dict[str, object] = {
            "pubmed_record_kind": "pubmed_book_article",
        }
        if book_title:
            source_data["book_title"] = book_title
        location_labels = [
            value
            for node in document.findall("./LocationLabel")
            if (value := _node_text(node))
        ]
        if location_labels:
            source_data["location_labels"] = location_labels
        records.append(
            {
                "record_id": f"pubmed:{pmid}",
                "source_name": source_name,
                "platform": platform,
                "source_record_id": pmid,
                "source_record_type": "pubmed_book_article",
                "source_data": source_data,
                "title": _text(document, "./ArticleTitle") or book_title,
                "citation": _book_citation(document),
                "abstract": _abstract(document, "./Abstract/AbstractText"),
                "external_identifiers": _identifiers(
                    article,
                    pmid,
                    (
                        "./BookDocument/ArticleIdList/ArticleId",
                        "./PubmedBookData/ArticleIdList/ArticleId",
                    ),
                ),
                "publication_types": _book_publication_types(document),
                "related_records": [],
                "locators": [f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"],
                "search_run_ids": [run_id],
                "provenance": [
                    {
                        "source_id": "pubmed",
                        "source_type": f"search_source:{platform}",
                        "locator": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "excerpt": f"pmid={pmid}",
                    }
                ],
            }
        )
    return records


def _incomplete_export_reason(
    *,
    retrieved: int,
    total: int,
    target: int,
    max_records: int,
) -> str | None:
    if retrieved == total:
        return None
    if total > max_records and retrieved == target:
        return (
            f"Retrieved the configured safety ceiling of {max_records} from "
            f"{total} source results."
        )
    if total > max_records:
        return (
            f"PubMed reported {total} source results; the configured safety "
            f"ceiling limited the requested export to {target}, and the paged "
            f"E-utilities export produced {retrieved} parseable Records."
        )
    return (
        f"PubMed reported {total} source results, but the complete paged "
        f"E-utilities export produced {retrieved} parseable Records."
    )


def _identifiers(
    element: ElementTree.Element,
    pmid: str,
    paths: tuple[str, ...],
) -> list[dict[str, str]]:
    identifiers = [{"scheme": "pmid", "value": pmid}]
    seen = {("pmid", pmid)}
    for path in paths:
        for node in element.findall(path):
            value = _node_text(node)
            scheme = str(node.attrib.get("IdType") or "").strip().lower()
            if scheme == "pubmed":
                scheme = "pmid"
            key = (scheme, value or "")
            if not value or not scheme or key in seen:
                continue
            seen.add(key)
            identifiers.append({"scheme": scheme, "value": value})
    return identifiers


def _text(element: ElementTree.Element, path: str) -> str | None:
    return _node_text(element.find(path))


def _node_text(node: ElementTree.Element | None) -> str | None:
    if node is None:
        return None
    value = " ".join("".join(node.itertext()).split())
    return value or None


def _abstract(
    element: ElementTree.Element,
    path: str = "./MedlineCitation/Article/Abstract/AbstractText",
) -> str | None:
    parts = [_node_text(node) for node in element.findall(path)]
    value = " ".join(part for part in parts if part)
    return value or None


def _publication_types(element: ElementTree.Element) -> list[str]:
    values = [
        _node_text(node)
        for node in element.findall(
            "./MedlineCitation/Article/PublicationTypeList/PublicationType"
        )
    ]
    return list(dict.fromkeys(value for value in values if value))


def _book_publication_types(document: ElementTree.Element) -> list[str]:
    values = [_node_text(node) for node in document.findall("./PublicationType")]
    return list(dict.fromkeys(value for value in values if value))


def _related_records(element: ElementTree.Element) -> list[dict[str, str | None]]:
    values: list[dict[str, str | None]] = []
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for node in element.findall(
        "./MedlineCitation/CommentsCorrectionsList/CommentsCorrections"
    ):
        relation_type = str(node.attrib.get("RefType") or "").strip()
        if not relation_type:
            continue
        related_source_record_id = _text(node, "./PMID")
        citation = _text(node, "./RefSource")
        note = _text(node, "./Note")
        key = (relation_type, related_source_record_id, citation, note)
        if key in seen:
            continue
        seen.add(key)
        values.append(
            {
                "relation_type": relation_type,
                "related_source_record_id": related_source_record_id,
                "citation": citation,
                "note": note,
            }
        )
    return values


def _citation(element: ElementTree.Element) -> str | None:
    journal = _text(element, "./MedlineCitation/Article/Journal/Title")
    year = _text(
        element,
        "./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year",
    ) or _text(
        element,
        "./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate",
    )
    volume = _text(
        element,
        "./MedlineCitation/Article/Journal/JournalIssue/Volume",
    )
    issue = _text(
        element,
        "./MedlineCitation/Article/Journal/JournalIssue/Issue",
    )
    pages = _text(element, "./MedlineCitation/Article/Pagination/MedlinePgn")
    parts = [part for part in (journal, year) if part]
    if volume:
        parts.append(volume + (f"({issue})" if issue else ""))
    if pages:
        parts.append(pages)
    return "; ".join(parts) or None


def _book_citation(document: ElementTree.Element) -> str | None:
    book = document.find("./Book")
    if book is None:
        return None
    book_title = _text(book, "./BookTitle")
    year = _text(book, "./PubDate/Year") or _text(book, "./PubDate/MedlineDate")
    volume = _text(book, "./Volume")
    edition = _text(book, "./Edition")
    pages = _text(document, "./Pagination/MedlinePgn")
    if not pages:
        start = _text(document, "./Pagination/StartPage")
        end = _text(document, "./Pagination/EndPage")
        pages = f"{start}-{end}" if start and end else start
    publisher = _text(book, "./Publisher/PublisherName")
    parts = [value for value in (book_title, year) if value]
    if volume:
        parts.append(f"volume {volume}")
    if edition:
        parts.append(edition)
    if pages:
        parts.append(pages)
    if publisher:
        parts.append(publisher)
    return "; ".join(parts) or None


def _required_nonnegative_int(value: str | None, label: str) -> int:
    try:
        parsed = int(value or "")
    except ValueError as exc:
        raise ValueError(f"{label} is missing or invalid") from exc
    if parsed < 0:
        raise ValueError(f"{label} must not be negative")
    return parsed


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
