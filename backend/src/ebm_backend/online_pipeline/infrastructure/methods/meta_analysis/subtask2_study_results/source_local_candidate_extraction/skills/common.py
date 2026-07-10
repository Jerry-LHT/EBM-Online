"""Common LLM skill caller for targeted extraction."""

from __future__ import annotations

import os
import time
from threading import BoundedSemaphore
from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm import call_llm_json
from ebm_backend.online_pipeline.infrastructure.llm.config import LLMConfig
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.prompt_loader import (
    render_prompt,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subtask2_study_results.source_local_candidate_extraction.tools.json_tools import (
    prompt_json,
)


def call_skill(
    *,
    config: LLMConfig | dict[str, Any],
    template: str,
    payload: dict[str, Any],
    system: str,
    fallback: dict[str, Any],
    timeout_seconds: float | None = 90,
) -> dict[str, Any]:
    prompt = render_prompt(template, input_json=prompt_json(payload))
    started = time.monotonic()
    attempts = _retry_attempts()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with _LLM_SEMAPHORE:
                parsed = call_llm_json(
                    config=config,
                    system=system,
                    prompt=prompt,
                    timeout_seconds=timeout_seconds,
                    temperature=0,
                )
            break
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                return {
                    **fallback,
                    "_duration_ms": int(round((time.monotonic() - started) * 1000)),
                    "_attempts": attempt,
                    "warnings": [f"llm_error:{type(exc).__name__}"],
                }
            time.sleep(_retry_backoff_seconds(attempt))
    if isinstance(parsed, dict):
        parsed["_duration_ms"] = int(round((time.monotonic() - started) * 1000))
        parsed["_attempts"] = attempt
        if last_error is not None:
            warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
            parsed["warnings"] = [*warnings, f"llm_retry_recovered:{type(last_error).__name__}"]
        return parsed
    return {
        **fallback,
        "_duration_ms": int(round((time.monotonic() - started) * 1000)),
        "_attempts": attempt,
        "warnings": ["llm_returned_non_object"],
    }


def _retry_attempts() -> int:
    raw = os.environ.get("SUBTASK2_TARGETED_LLM_RETRY_ATTEMPTS")
    if raw is None or raw.strip() == "":
        return 3
    try:
        return max(1, int(raw))
    except ValueError:
        return 3


def _retry_backoff_seconds(attempt: int) -> float:
    raw = os.environ.get("SUBTASK2_TARGETED_LLM_RETRY_BACKOFF_SECONDS")
    try:
        base = float(raw) if raw is not None and raw.strip() else 1.0
    except ValueError:
        base = 1.0
    return min(8.0, max(0.0, base) * (2 ** max(0, attempt - 1)))


def _llm_max_in_flight() -> int:
    raw = os.environ.get("SUBTASK2_TARGETED_LLM_MAX_IN_FLIGHT")
    if raw is None or raw.strip() == "":
        return 16
    try:
        return max(1, int(raw))
    except ValueError:
        return 16


_LLM_SEMAPHORE = BoundedSemaphore(_llm_max_in_flight())
