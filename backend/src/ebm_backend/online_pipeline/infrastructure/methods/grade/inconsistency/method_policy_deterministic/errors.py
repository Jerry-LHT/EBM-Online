"""Stable failures for the policy-driven GRADE inconsistency method."""

from __future__ import annotations


class GRADEInconsistencyConfigurationError(RuntimeError):
    """The method cannot load its required LLM configuration."""


class GRADEInconsistencyInvocationError(RuntimeError):
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
            f"GRADE inconsistency stage '{stage}' failed for "
            f"setting '{setting_id}' after {attempts} attempt(s){suffix}"
        )
        self.setting_id = setting_id
        self.stage = stage
        self.attempts = attempts
        self.retry_exhausted = retry_exhausted


class GRADEInconsistencyPolicyError(RuntimeError):
    """The policy LLM repeatedly returned an invalid executable policy."""

    def __init__(self, *, setting_id: str, attempts: int) -> None:
        super().__init__(
            "GRADE inconsistency policy output was invalid for "
            f"setting '{setting_id}' after {attempts} attempts"
        )
        self.setting_id = setting_id
        self.attempts = attempts


class GRADEInconsistencyJudgementError(RuntimeError):
    """The judge repeatedly returned an invalid structured judgement."""

    def __init__(self, *, setting_id: str, attempts: int) -> None:
        super().__init__(
            "GRADE inconsistency judgement output was invalid for "
            f"setting '{setting_id}' after {attempts} attempts"
        )
        self.setting_id = setting_id
        self.attempts = attempts
