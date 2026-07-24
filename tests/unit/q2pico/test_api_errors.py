from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException

from ebm_backend.online_pipeline.infrastructure.methods.q2pico.errors import (
    Q2PICOConfigurationError,
    Q2PICOInvocationError,
)
from ebm_backend.online_pipeline.interfaces.api import routes_modules
from ebm_backend.online_pipeline.interfaces.api.request_schemas import Q2PICORequest


class _FailingUseCase:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def execute(self, **kwargs):
        raise self.error


def test_q2pico_api_expands_outcomes_by_default() -> None:
    request = Q2PICORequest(question_text="Should adults receive treatment?")

    assert request.expand_outcomes is True


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            Q2PICOConfigurationError("configuration unavailable"),
            503,
            {"code": "q2pico_configuration_unavailable"},
        ),
        (
            Q2PICOInvocationError(stage="O", attempts=2),
            502,
            {
                "code": "q2pico_stage_retry_exhausted",
                "stage": "O",
                "attempts": 2,
            },
        ),
    ],
)
def test_q2pico_route_maps_execution_failures_to_stable_http_errors(
    monkeypatch,
    error: Exception,
    status_code: int,
    detail: dict[str, object],
) -> None:
    monkeypatch.setattr(routes_modules, "get_q2pico_use_case_for_api", lambda: _FailingUseCase(error))

    with pytest.raises(HTTPException) as raised:
        routes_modules.run_q2pico(Q2PICORequest(question_text="Should adults receive treatment?"))

    assert raised.value.status_code == status_code
    assert isinstance(raised.value.detail, dict)
    for key, value in detail.items():
        assert raised.value.detail[key] == value


def test_q2pico_route_keeps_invalid_business_input_as_bad_request(monkeypatch) -> None:
    monkeypatch.setattr(
        routes_modules,
        "get_q2pico_use_case_for_api",
        lambda: _FailingUseCase(ValueError("question_text is required")),
    )

    with pytest.raises(HTTPException) as raised:
        routes_modules.run_q2pico(Q2PICORequest(question_text="   "))

    assert raised.value.status_code == 400
    assert raised.value.detail == "question_text is required"
