from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException

from ebm_backend.online_pipeline.application.use_cases.run_risk_of_bias import (
    RiskOfBiasArticleContentMissingError,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.errors import (
    RiskOfBiasConfigurationError,
    RiskOfBiasDomainInvocationError,
)
from ebm_backend.online_pipeline.interfaces.api import routes_modules
from ebm_backend.online_pipeline.interfaces.api.request_schemas import RiskOfBiasRequest


class _UseCase:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def execute(self, **kwargs):
        if self.error is not None:
            raise self.error
        return []


def _request() -> RiskOfBiasRequest:
    return RiskOfBiasRequest(included_studies=[], articles=[])


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ValueError("invalid"), 400, "risk_of_bias_invalid_input"),
        (
            RiskOfBiasArticleContentMissingError(study_ids=["study-1"]),
            400,
            "risk_of_bias_article_content_missing",
        ),
        (
            RiskOfBiasConfigurationError("missing"),
            503,
            "risk_of_bias_configuration_unavailable",
        ),
        (
            RiskOfBiasDomainInvocationError(
                study_id="study-1",
                domain="allocation_concealment",
                attempts=2,
            ),
            502,
            "risk_of_bias_domain_retry_exhausted",
        ),
    ],
)
def test_risk_of_bias_route_maps_stable_errors(monkeypatch, error, status, code) -> None:
    monkeypatch.setattr(
        routes_modules,
        "get_risk_of_bias_use_case_for_api",
        lambda: _UseCase(error),
    )

    with pytest.raises(HTTPException) as raised:
        routes_modules.run_risk_of_bias(_request())

    assert raised.value.status_code == status
    assert raised.value.detail["code"] == code


def test_request_schema_declares_limits_and_seven_default_domains() -> None:
    request = _request()
    schema = RiskOfBiasRequest.model_json_schema()["properties"]

    assert schema["included_studies"]["maxItems"] == 500
    assert schema["articles"]["maxItems"] == 500
    assert len(request.domain_config.assessed_domains) == 7
    assert request.domain_config.assessed_domains == request.domain_config.overall_key_domains
