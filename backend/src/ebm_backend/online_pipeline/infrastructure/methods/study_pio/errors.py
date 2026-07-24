"""Failure contracts for the production Study PIO method."""

from __future__ import annotations


class StudyPIOConfigurationError(RuntimeError):
    """The Study PIO method cannot obtain usable LLM configuration."""


class StudyPIOInvocationError(RuntimeError):
    """One required Study PIO stage exhausted its retry budget."""

    def __init__(self, *, stage: str, study_id: str, attempts: int) -> None:
        super().__init__(
            f"Study PIO stage '{stage}' for study '{study_id}' failed after "
            f"{attempts} attempts"
        )
        self.stage = stage
        self.study_id = study_id
        self.attempts = attempts
