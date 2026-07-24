"""Stable errors for the product Risk of Bias method."""

from __future__ import annotations


class RiskOfBiasConfigurationError(RuntimeError):
    """The Risk of Bias LLM configuration is unavailable."""


class RiskOfBiasDomainInvocationError(RuntimeError):
    """One configured RoB 1 domain exhausted its business retry budget."""

    def __init__(
        self,
        *,
        study_id: str,
        domain: str,
        attempts: int,
    ) -> None:
        super().__init__(
            f"Risk of Bias domain '{domain}' failed for study_id '{study_id}' "
            f"after {attempts} attempts"
        )
        self.study_id = study_id
        self.domain = domain
        self.attempts = attempts
