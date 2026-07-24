"""Stable failures for the production GRADE imprecision method."""

from __future__ import annotations


class GRADEImprecisionConfigurationError(RuntimeError):
    """The threshold-research LLM is not configured for this method."""


class GRADEImprecisionInvocationError(RuntimeError):
    """A provider call failed within the bounded threshold retry policy."""

    def __init__(
        self,
        *,
        setting_id: str,
        attempts: int,
        retry_exhausted: bool,
    ) -> None:
        suffix = " after retry exhaustion" if retry_exhausted else ""
        super().__init__(
            "GRADE imprecision threshold generation failed for setting "
            f"'{setting_id}' after {attempts} attempt(s){suffix}"
        )
        self.setting_id = setting_id
        self.stage = "threshold_generation"
        self.attempts = attempts
        self.retry_exhausted = retry_exhausted


class GRADEImprecisionThresholdError(RuntimeError):
    """The model failed to return a valid threshold contract."""

    def __init__(self, *, setting_id: str, attempts: int) -> None:
        super().__init__(
            "GRADE imprecision threshold output was invalid for setting "
            f"'{setting_id}' after {attempts} attempt(s)"
        )
        self.setting_id = setting_id
        self.attempts = attempts

