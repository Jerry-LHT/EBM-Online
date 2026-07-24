"""Stable technical failures exposed by production Meta-analysis methods."""

from __future__ import annotations

from typing import Any


class MetaAnalysisConfigurationError(RuntimeError):
    """A Meta-analysis method cannot load its required configuration or assets."""

    def __init__(self, *, stage: str) -> None:
        super().__init__(
            f"Meta-analysis stage '{stage}' cannot load its required configuration"
        )
        self.stage = stage


class MetaAnalysisInvocationError(RuntimeError):
    """A provider call failed within one Meta-analysis method stage."""

    def __init__(
        self,
        *,
        stage: str,
        attempts: int,
        retry_exhausted: bool,
        context_id: str | None = None,
        failure_code: str = "provider_error",
        status_code: int | None = None,
        request_id: str | None = None,
        failure_detail: str | None = None,
        attempt_history: list[dict[str, Any]] | None = None,
    ) -> None:
        suffix = " after retry exhaustion" if retry_exhausted else ""
        context = f" for '{context_id}'" if context_id else ""
        super().__init__(
            f"Meta-analysis stage '{stage}' failed{context} after "
            f"{attempts} attempt(s){suffix}"
        )
        self.stage = stage
        self.attempts = attempts
        self.retry_exhausted = retry_exhausted
        self.context_id = context_id
        self.failure_code = failure_code
        self.status_code = status_code
        self.request_id = request_id
        self.failure_detail = _bounded_detail(failure_detail)
        self.attempt_history = list(attempt_history or [])


class MetaAnalysisOutputError(RuntimeError):
    """A Meta-analysis LLM stage repeatedly returned an invalid contract."""

    def __init__(
        self,
        *,
        stage: str,
        attempts: int,
        context_id: str | None = None,
        validation_error: str | None = None,
        failure_code: str = "invalid_model_output",
        attempt_history: list[dict[str, Any]] | None = None,
    ) -> None:
        context = f" for '{context_id}'" if context_id else ""
        normalized_error = " ".join(str(validation_error or "").split())
        detail = (
            f"; validation error: {normalized_error[:300]}"
            if normalized_error
            else ""
        )
        super().__init__(
            f"Meta-analysis stage '{stage}' returned invalid output{context} "
            f"after {attempts} attempt(s){detail}"
        )
        self.stage = stage
        self.attempts = attempts
        self.context_id = context_id
        self.validation_error = normalized_error or None
        self.failure_code = failure_code
        self.failure_detail = self.validation_error
        self.attempt_history = list(attempt_history or [])


def _bounded_detail(value: str | None, *, limit: int = 500) -> str | None:
    normalized = " ".join(str(value or "").split())
    return normalized[:limit] or None
