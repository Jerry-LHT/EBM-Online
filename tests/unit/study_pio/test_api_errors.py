from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException

from ebm_backend.online_pipeline.application.use_cases.run_study_pio import (
    StudyPIOArticleContentMissingError,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.errors import (
    StudyPIOConfigurationError,
    StudyPIOInvocationError,
)
from ebm_backend.online_pipeline.interfaces.api import routes_modules
from ebm_backend.online_pipeline.interfaces.api.request_schemas import (
    StudyPIOExtractionRequest,
)


class _UseCase:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def execute(self, **kwargs):
        if self.error is not None:
            raise self.error
        return []


def _request() -> StudyPIOExtractionRequest:
    return StudyPIOExtractionRequest(
        question_pico={"P": ["Adults"]},
        included_studies=[],
        articles=[],
    )


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (
            ValueError("invalid"),
            400,
            "study_pio_invalid_input",
        ),
        (
            StudyPIOArticleContentMissingError(study_ids=["study-1"]),
            400,
            "study_pio_article_content_missing",
        ),
        (
            StudyPIOConfigurationError("missing config"),
            503,
            "study_pio_configuration_unavailable",
        ),
        (
            StudyPIOInvocationError(
                stage="outcome",
                study_id="study-1",
                attempts=2,
            ),
            502,
            "study_pio_stage_retry_exhausted",
        ),
    ],
)
def test_study_pio_route_maps_stable_errors(monkeypatch, error, status, code) -> None:
    monkeypatch.setattr(
        routes_modules,
        "get_study_pio_use_case_for_api",
        lambda: _UseCase(error),
    )

    with pytest.raises(HTTPException) as raised:
        routes_modules.run_study_pio_extraction(_request())

    assert raised.value.status_code == status
    assert raised.value.detail["code"] == code


def test_study_pio_request_schema_declares_five_hundred_item_limits() -> None:
    schema = StudyPIOExtractionRequest.model_json_schema()["properties"]

    assert schema["included_studies"]["maxItems"] == 500
    assert schema["articles"]["maxItems"] == 500
