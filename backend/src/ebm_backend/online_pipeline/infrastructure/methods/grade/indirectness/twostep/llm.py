"""LLM call helpers for the two-step indirectness method."""

from __future__ import annotations

import json
import time
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm.client import call_llm_json


LLM_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0)


def call_json_with_retries(**kwargs: Any) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(len(LLM_RETRY_DELAYS_SECONDS) + 1):
        try:
            return call_llm_json(**kwargs)
        except Exception as exc:  # pragma: no cover - provider/network dependent
            last_exc = exc
            if attempt >= len(LLM_RETRY_DELAYS_SECONDS):
                break
            if not should_retry_llm_error(exc):
                break
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])
    if last_exc is None:
        raise RuntimeError("LLM call failed without an exception")
    raise last_exc


def should_retry_llm_error(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, json.JSONDecodeError):
        return True
    code = getattr(exc, "code", None)
    if code in {408, 409, 429, 500, 502, 503, 504}:
        return True
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "429",
            "too many requests",
            "timeout",
            "temporarily",
            "rate limit",
            "remote end closed connection",
            "connection",
            "ssl",
            "eof",
            "reset by peer",
            "urlopen error",
        )
    )
