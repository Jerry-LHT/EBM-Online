"""Failure contracts for production Study Screening methods."""

from __future__ import annotations


class StudyScreeningConfigurationError(RuntimeError):
    """A screening method cannot obtain usable LLM configuration."""


class StudyScreeningInvocationError(RuntimeError):
    """A required screening LLM stage exhausted its retry budget."""

    def __init__(
        self,
        *,
        stage: str,
        attempts: int,
        article_id: str | None = None,
        evidence_scope: str | None = None,
    ) -> None:
        super().__init__(
            f"Study Screening stage '{stage}' failed after {attempts} attempts"
        )
        self.stage = stage
        self.attempts = attempts
        self.article_id = article_id
        self.evidence_scope = evidence_scope
