"""Shared bounded LLM invocation support for Study Screening methods."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.errors import (
    StudyScreeningConfigurationError,
    StudyScreeningInvocationError,
)


MAX_ATTEMPTS_PER_STAGE = 2
T = TypeVar("T")


def screening_llm_config(
    configured: LLMConfig | dict | None,
) -> LLMConfig | dict:
    try:
        config = configured if configured is not None else load_llm_config()
        if config is None:
            raise RuntimeError("Missing required LLM config")
        api_mode = (
            config.api_mode
            if isinstance(config, LLMConfig)
            else str(config.get("api_mode") or "")
        )
        normalized = config.to_dict() if isinstance(config, LLMConfig) else dict(config)
        if api_mode.strip().lower() == "auto":
            normalized["api_mode"] = "responses"
        # The stage wrapper owns the complete retry budget: initial request
        # plus one retry. Disable hidden SDK and JSON-marker network retries.
        normalized["sdk_max_retries"] = 0
        normalized["json_marker_retry_enabled"] = False
        return normalized
    except (FileNotFoundError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise StudyScreeningConfigurationError(
            "Study Screening LLM configuration is unavailable"
        ) from exc


def call_with_one_retry(
    *,
    stage: str,
    action: Callable[[], T],
    article_id: str | None = None,
    evidence_scope: str | None = None,
) -> T:
    for attempt in range(1, MAX_ATTEMPTS_PER_STAGE + 1):
        try:
            return action()
        except Exception as exc:
            if attempt == MAX_ATTEMPTS_PER_STAGE:
                raise StudyScreeningInvocationError(
                    stage=stage,
                    attempts=attempt,
                    article_id=article_id,
                    evidence_scope=evidence_scope,
                ) from exc
    raise AssertionError("unreachable")
