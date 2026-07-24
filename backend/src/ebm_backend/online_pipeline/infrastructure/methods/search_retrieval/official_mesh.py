"""Official NLM MeSH lookup shared by search-retrieval methods."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import certifi

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.errors import (
    SearchRetrievalStageError,
)


USER_AGENT = "ebm-online-pipeline-search-retrieval/0.1"
LOOKUP_DESCRIPTOR_URL = "https://id.nlm.nih.gov/mesh/lookup/descriptor"
LOOKUP_DETAILS_URL = "https://id.nlm.nih.gov/mesh/lookup/details"
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 1


@dataclass(frozen=True)
class OfficialMeshDescriptor:
    descriptor_ui: str
    heading: str
    entry_terms: list[str] = field(default_factory=list)


class OfficialMeshLookupClient:
    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        requests_per_second: float = 3.0,
        opener=None,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.requests_per_second = requests_per_second
        self.opener = opener or _default_urlopen
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_request_at = 0.0

    def resolve(self, *, label: str) -> OfficialMeshDescriptor | None:
        descriptor = self._lookup_descriptor(label=label, match="exact")
        if descriptor is None:
            descriptor = self._lookup_descriptor(label=label, match="contains")
            if descriptor is not None and not _labels_compatible(label, descriptor.heading):
                return None
        if descriptor is None:
            return None
        return self._lookup_details(descriptor_ui=descriptor.descriptor_ui)

    def _lookup_descriptor(self, *, label: str, match: str) -> OfficialMeshDescriptor | None:
        params = urllib.parse.urlencode({"label": label, "match": match, "limit": "1"})
        data = self._request_json(f"{LOOKUP_DESCRIPTOR_URL}?{params}", expected_type=list)
        if not data:
            return None
        first = data[0] or {}
        resource = str(first.get("resource") or "")
        heading = str(first.get("label") or "").strip()
        descriptor_ui = resource.rsplit("/", 1)[-1].strip()
        if not descriptor_ui or not heading:
            return None
        return OfficialMeshDescriptor(descriptor_ui=descriptor_ui, heading=heading)

    def _lookup_details(self, *, descriptor_ui: str) -> OfficialMeshDescriptor:
        params = urllib.parse.urlencode({"descriptor": descriptor_ui})
        data = self._request_json(f"{LOOKUP_DETAILS_URL}?{params}", expected_type=dict)
        heading = ""
        entry_terms: list[str] = []
        for term in data.get("terms") or []:
            label = str((term or {}).get("label") or "").strip()
            if not label:
                continue
            if bool((term or {}).get("preferred")) and not heading:
                heading = label
            else:
                entry_terms.append(label)
        return OfficialMeshDescriptor(
            descriptor_ui=descriptor_ui,
            heading=heading or descriptor_ui,
            entry_terms=entry_terms,
        )

    def _request_json(self, url: str, *, expected_type: type) -> Any:
        for attempt in range(self.retries + 1):
            try:
                self._throttle()
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with self.opener(request, self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                if not isinstance(data, expected_type):
                    raise ValueError(
                        f"MeSH lookup response must be {expected_type.__name__}"
                    )
                _validate_mesh_json(data)
                return data
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500 and exc.code != 429:
                    raise SearchRetrievalStageError(
                        stage="mesh_lookup",
                        attempts=attempt + 1,
                    ) from exc
                if attempt >= self.retries:
                    raise SearchRetrievalStageError(
                        stage="mesh_lookup",
                        attempts=attempt + 1,
                    ) from exc
                time.sleep(min(2**attempt, 8))
            except (
                urllib.error.URLError,
                TimeoutError,
                ssl.SSLError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ) as exc:
                if attempt >= self.retries:
                    raise SearchRetrievalStageError(
                        stage="mesh_lookup",
                        attempts=attempt + 1,
                    ) from exc
                time.sleep(min(2**attempt, 8))
        raise AssertionError("unreachable")

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()


def normalize_text_term(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    if "," in text:
        parts = [part.strip() for part in text.split(",") if part.strip()]
        if len(parts) == 2:
            text = f"{parts[1]} {parts[0]}"
    text = text.casefold()
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .;,")
    return text


def _labels_compatible(source: str, heading: str) -> bool:
    source_tokens = set(normalize_text_term(source).split())
    heading_tokens = set(normalize_text_term(heading).split())
    if not source_tokens or not heading_tokens:
        return False
    return source_tokens <= heading_tokens or heading_tokens <= source_tokens


def _validate_mesh_json(data: Any) -> None:
    if isinstance(data, list):
        if any(not isinstance(item, dict) for item in data):
            raise ValueError("MeSH descriptor response items must be objects")
        return
    terms = data.get("terms", [])
    if not isinstance(terms, list) or any(
        not isinstance(term, dict) for term in terms
    ):
        raise ValueError("MeSH details terms must be a list of objects")


def _default_urlopen(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where()))
