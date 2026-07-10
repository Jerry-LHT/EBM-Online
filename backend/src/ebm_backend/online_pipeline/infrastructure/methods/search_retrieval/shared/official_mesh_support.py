"""Official NLM MeSH lookup helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import certifi


USER_AGENT = "ebm-online-pipeline-search-retrieval/0.1"
LOOKUP_DESCRIPTOR_URL = "https://id.nlm.nih.gov/mesh/lookup/descriptor"
LOOKUP_DETAILS_URL = "https://id.nlm.nih.gov/mesh/lookup/details"
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 2


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
        if descriptor is None:
            return None
        return self._lookup_details(descriptor_ui=descriptor.descriptor_ui)

    def _lookup_descriptor(self, *, label: str, match: str) -> OfficialMeshDescriptor | None:
        params = urllib.parse.urlencode({"label": label, "match": match, "limit": "1"})
        payload = self._request_text(f"{LOOKUP_DESCRIPTOR_URL}?{params}")
        data = json.loads(payload)
        if not isinstance(data, list) or not data:
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
        payload = self._request_text(f"{LOOKUP_DETAILS_URL}?{params}")
        data = json.loads(payload)
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

    def _request_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self._throttle()
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with self.opener(request, self.timeout) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if 400 <= exc.code < 500 and exc.code != 429:
                    raise
                if attempt >= self.retries:
                    raise
                time.sleep(min(2**attempt, 8))
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise RuntimeError(f"MeSH lookup request failed: {url}") from exc
                time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"Unreachable MeSH lookup failure: {last_error}")

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


def _default_urlopen(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where()))
