#!/usr/bin/env python3
"""Look up candidate terms in the official NLM MeSH vocabulary."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


LOOKUP_DESCRIPTOR_URL = "https://id.nlm.nih.gov/mesh/lookup/descriptor"
LOOKUP_DETAILS_URL = "https://id.nlm.nih.gov/mesh/lookup/details"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terms-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    terms = [
        line.strip()
        for line in args.terms_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not terms:
        raise SystemExit("terms file is empty")

    client = MeshLookupClient()
    mappings = [
        {"input_term": term, "descriptor": client.resolve(term)}
        for term in dict.fromkeys(terms)
    ]
    _write_json(
        args.output,
        {
            "schema_version": "nlm-mesh-observation.v1",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "source": LOOKUP_DESCRIPTOR_URL,
            "mappings": mappings,
        },
    )
    return 0


class MeshLookupClient:
    def __init__(self, *, opener=urlopen) -> None:
        self._opener = opener
        self._last_request_at = 0.0

    def resolve(self, term: str) -> dict[str, object] | None:
        candidates = self._get_json(
            LOOKUP_DESCRIPTOR_URL,
            {"label": term, "match": "exact", "limit": "1"},
        )
        if not candidates:
            candidates = self._get_json(
                LOOKUP_DESCRIPTOR_URL,
                {"label": term, "match": "contains", "limit": "1"},
            )
        if not candidates:
            return None
        candidate = candidates[0]
        resource = str(candidate.get("resource") or "").strip()
        descriptor_ui = resource.rsplit("/", 1)[-1]
        if not descriptor_ui:
            return None
        details = self._get_json(
            LOOKUP_DETAILS_URL,
            {"descriptor": descriptor_ui},
        )
        terms = details.get("terms") or []
        preferred = next(
            (
                str(item.get("label") or "").strip()
                for item in terms
                if item.get("preferred") and str(item.get("label") or "").strip()
            ),
            str(candidate.get("label") or "").strip(),
        )
        entry_terms = list(
            dict.fromkeys(
                str(item.get("label") or "").strip()
                for item in terms
                if not item.get("preferred") and str(item.get("label") or "").strip()
            )
        )
        return {
            "descriptor_ui": descriptor_ui,
            "heading": preferred,
            "entry_terms": entry_terms,
        }

    def _get_json(self, endpoint: str, params: dict[str, str]):
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < 1 / 3:
            time.sleep(1 / 3 - elapsed)
        request = Request(
            f"{endpoint}?{urlencode(params)}",
            headers={"Accept": "application/json", "User-Agent": "ebm-online-v2/1.0"},
        )
        with self._opener(request, timeout=30.0) as response:
            value = json.loads(response.read().decode("utf-8"))
        self._last_request_at = time.monotonic()
        if not isinstance(value, (list, dict)):
            raise ValueError("NLM MeSH response must be an object or array")
        return value


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
