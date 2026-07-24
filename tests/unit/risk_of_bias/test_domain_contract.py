from __future__ import annotations

import pytest

from ebm_backend.online_pipeline.domain.risk_of_bias import (
    DEFAULT_ROB1_DOMAINS,
    RiskOfBiasDomainConfig,
    RoB1DomainJudgement,
    summarize_rob1_overall,
)


def _judgement(domain: str, value: str) -> RoB1DomainJudgement:
    return RoB1DomainJudgement(domain=domain, judgement=value, rationale="Evidence")


def test_default_domain_config_uses_all_seven_rob1_domains() -> None:
    config = RiskOfBiasDomainConfig()

    assert config.assessed_domains == DEFAULT_ROB1_DOMAINS
    assert config.overall_key_domains == DEFAULT_ROB1_DOMAINS
    assert len(config.assessed_domains) == 7
    assert "selective_reporting" in config.assessed_domains
    assert "other_bias" in config.assessed_domains


@pytest.mark.parametrize(
    ("values", "expected", "drivers"),
    [
        (["low_risk", "low_risk"], "low_risk", []),
        (["low_risk", "unclear_risk"], "unclear_risk", ["d2"]),
        (["high_risk", "unclear_risk"], "high_risk", ["d1"]),
    ],
)
def test_overall_uses_official_key_domain_mapping(values, expected, drivers) -> None:
    domains = ["d1", "d2"]
    result = summarize_rob1_overall(
        judgements=[_judgement(domain, value) for domain, value in zip(domains, values)],
        key_domains=domains,
    )

    assert result.judgement == expected
    assert result.driving_domains == drivers
    assert result.basis == "configured_key_domains"


def test_domain_config_rejects_unknown_duplicate_and_non_subset_domains() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        RiskOfBiasDomainConfig(
            assessed_domains=["unknown"],
            overall_key_domains=["unknown"],
        )
    with pytest.raises(ValueError, match="duplicate"):
        RiskOfBiasDomainConfig(
            assessed_domains=["allocation_concealment", "allocation_concealment"],
            overall_key_domains=["allocation_concealment"],
        )
    with pytest.raises(ValueError, match="subset"):
        RiskOfBiasDomainConfig(
            assessed_domains=["allocation_concealment"],
            overall_key_domains=["random_sequence_generation"],
        )
