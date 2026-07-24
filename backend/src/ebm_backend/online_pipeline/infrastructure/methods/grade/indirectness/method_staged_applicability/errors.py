"""Stable failures for staged GRADE indirectness assessment."""

from __future__ import annotations


class GRADEIndirectnessConfigurationError(RuntimeError):
    """The method cannot load its required LLM configuration."""


class GRADEIndirectnessInvocationError(RuntimeError):
    """One bounded LLM stage failed at the provider boundary."""

    def __init__(
        self,
        *,
        setting_id: str,
        stage: str,
        attempts: int,
        retry_exhausted: bool,
    ) -> None:
        suffix = " after retry exhaustion" if retry_exhausted else ""
        super().__init__(
            f"GRADE indirectness stage '{stage}' failed for setting "
            f"'{setting_id}' after {attempts} attempt(s){suffix}"
        )
        self.setting_id = setting_id
        self.stage = stage
        self.attempts = attempts
        self.retry_exhausted = retry_exhausted


class GRADEIndirectnessClassificationError(RuntimeError):
    """The result-blind classifier repeatedly returned invalid output."""

    def __init__(self, *, setting_id: str, attempts: int) -> None:
        super().__init__(
            "GRADE indirectness classification output was invalid for "
            f"setting '{setting_id}' after {attempts} attempts"
        )
        self.setting_id = setting_id
        self.attempts = attempts


class GRADEIndirectnessThresholdError(RuntimeError):
    """The conditional threshold generator repeatedly returned invalid output."""

    def __init__(self, *, setting_id: str, attempts: int) -> None:
        super().__init__(
            "GRADE indirectness threshold output was invalid for "
            f"setting '{setting_id}' after {attempts} attempts"
        )
        self.setting_id = setting_id
        self.attempts = attempts


class GRADEIndirectnessJudgementError(RuntimeError):
    """The evidence-body judge repeatedly returned invalid output."""

    def __init__(self, *, setting_id: str, attempts: int) -> None:
        super().__init__(
            "GRADE indirectness judgement output was invalid for "
            f"setting '{setting_id}' after {attempts} attempts"
        )
        self.setting_id = setting_id
        self.attempts = attempts
