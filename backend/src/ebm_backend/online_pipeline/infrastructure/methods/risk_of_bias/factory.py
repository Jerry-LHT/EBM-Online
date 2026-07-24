"""Factory for Risk of Bias methods."""

from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.method import (
    build_method as build_onestep_llm_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.cache import (
    RoBDomainJudgementCache,
)


def build_production_risk_of_bias(
    *,
    domain_cache: RoBDomainJudgementCache | None = None,
):
    """Build the Risk of Bias adapter approved for the product API."""
    return build_onestep_llm_method(domain_cache=domain_cache)
