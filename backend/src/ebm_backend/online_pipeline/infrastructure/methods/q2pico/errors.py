"""Failure contracts for the production Q2PICO adapter."""

from __future__ import annotations


class Q2PICOConfigurationError(RuntimeError):
    """The adapter cannot obtain a usable LLM configuration."""


class Q2PICOInvocationError(RuntimeError):
    """One required Q2PICO LLM stage exhausted its bounded retry budget."""

    def __init__(self, *, stage: str, attempts: int) -> None:
        super().__init__(f"Q2PICO stage '{stage}' failed after {attempts} attempts")
        self.stage = stage
        self.attempts = attempts
