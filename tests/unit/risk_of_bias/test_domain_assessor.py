from __future__ import annotations

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.errors import (
    RiskOfBiasDomainInvocationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.domain_assessor import (
    assess_domain,
)


def test_domain_assessor_uses_strict_schema_and_normalizes_exact_judgement() -> None:
    calls: list[dict] = []

    def caller(**kwargs):
        calls.append(kwargs)
        return {
            "domain": "Allocation concealment (selection bias)",
            "judgement": "Unclear risk",
            "support_text": "The article did not report a concealment mechanism.",
        }

    result = assess_domain(
        config=object(),  # type: ignore[arg-type]
        domain_id="allocation_concealment",
        evidence="Methods text",
        study_id="study-1",
        caller=caller,
    )

    assert result.judgement == "unclear_risk"
    assert result.rationale.startswith("The article")
    assert len(calls) == 1
    assert calls[0]["json_schema_name"] == "risk_of_bias_allocation_concealment"
    assert calls[0]["json_schema"]["additionalProperties"] is False
    assert calls[0]["json_schema"]["required"] == [
        "domain",
        "judgement",
        "support_text",
    ]


def test_domain_validation_failure_retries_only_once_then_recovers() -> None:
    attempts = 0

    def caller(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {
                "domain": "Random sequence generation (selection bias)",
                "judgement": "probably low",
                "support_text": "Evidence",
            }
        return {
            "domain": "Random sequence generation (selection bias)",
            "judgement": "Low risk",
            "support_text": "A computer-generated random sequence was used.",
        }

    result = assess_domain(
        config=object(),  # type: ignore[arg-type]
        domain_id="random_sequence_generation",
        evidence="Methods text",
        study_id="study-1",
        caller=caller,
    )

    assert attempts == 2
    assert result.judgement == "low_risk"


def test_domain_failure_after_two_attempts_is_not_converted_to_unclear() -> None:
    attempts = 0

    def caller(**kwargs):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("provider unavailable")

    with pytest.raises(RiskOfBiasDomainInvocationError) as raised:
        assess_domain(
            config=object(),  # type: ignore[arg-type]
            domain_id="incomplete_outcome_data",
            evidence="Results text",
            study_id="study-9",
            caller=caller,
        )

    assert attempts == 2
    assert raised.value.study_id == "study-9"
    assert raised.value.domain == "incomplete_outcome_data"
    assert raised.value.attempts == 2
