"""Stable technical failures for the evidence-body GRADE RoB method."""

from __future__ import annotations


class GRADERiskOfBiasConfigurationError(RuntimeError):
    """The method cannot load its required LLM configuration."""


class GRADERiskOfBiasInvocationError(RuntimeError):
    """The provider failed within the method's bounded business retry."""

    def __init__(
        self,
        *,
        setting_id: str,
        attempts: int,
        retry_exhausted: bool = True,
    ) -> None:
        suffix = " after retry exhaustion" if retry_exhausted else ""
        super().__init__(
            "GRADE risk-of-bias assessment failed for "
            f"setting '{setting_id}' after {attempts} attempt(s){suffix}"
        )
        self.setting_id = setting_id
        self.stage = "evidence_body_judgement"
        self.attempts = attempts
        self.retry_exhausted = retry_exhausted


class GRADERiskOfBiasJudgementError(RuntimeError):
    """The model repeatedly returned an invalid evidence-body judgement."""

    def __init__(self, *, setting_id: str, attempts: int) -> None:
        super().__init__(
            "GRADE risk-of-bias judgement output was invalid for "
            f"setting '{setting_id}' after {attempts} attempt(s)"
        )
        self.setting_id = setting_id
        self.stage = "evidence_body_judgement"
        self.attempts = attempts
