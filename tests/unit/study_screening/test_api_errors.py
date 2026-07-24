from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException

from ebm_backend.online_pipeline.domain.screening import (
    ScreeningEvidenceScope,
    StudyScreeningResult,
    ScreeningCriteria,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.errors import (
    StudyScreeningConfigurationError,
    StudyScreeningInvocationError,
)
from ebm_backend.online_pipeline.interfaces.api import routes_modules
from ebm_backend.online_pipeline.interfaces.api.request_schemas import (
    StudyScreeningRequest,
)


class _UseCase:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.kwargs = None

    def execute(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return StudyScreeningResult(screening_criteria=ScreeningCriteria())


def _request(**kwargs) -> StudyScreeningRequest:
    return StudyScreeningRequest(
        question_text="Question",
        question_pico={"P": ["Adults"]},
        articles=[],
        **kwargs,
    )


def test_screening_request_defaults_to_final_full_text_primary_rct() -> None:
    request = _request()

    assert request.rct_only is True
    assert request.evidence_scope == ScreeningEvidenceScope.FULL_TEXT
    assert request.report_scope.value == "primary_results_report"
    assert request.outcome_eligibility_enabled is False


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (
            StudyScreeningConfigurationError("missing config"),
            503,
            "study_screening_configuration_unavailable",
        ),
        (
            StudyScreeningInvocationError(
                stage="criteria_planning",
                attempts=2,
                evidence_scope="full_text",
            ),
            502,
            "study_screening_criteria_retry_exhausted",
        ),
        (
            StudyScreeningInvocationError(
                stage="article_screening",
                attempts=2,
                article_id="article-1",
                evidence_scope="full_text",
            ),
            502,
            "study_screening_article_retry_exhausted",
        ),
    ],
)
def test_screening_route_maps_stable_errors(monkeypatch, error, status, code) -> None:
    monkeypatch.setattr(
        routes_modules,
        "get_study_screening_use_case_for_api",
        lambda **kwargs: _UseCase(error),
    )

    with pytest.raises(HTTPException) as raised:
        routes_modules.run_study_screening(_request())

    assert raised.value.status_code == status
    assert raised.value.detail["code"] == code


def test_screening_route_builds_structured_policy(monkeypatch) -> None:
    use_case = _UseCase()
    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return use_case

    monkeypatch.setattr(
        routes_modules,
        "get_study_screening_use_case_for_api",
        factory,
    )

    routes_modules.run_study_screening(
        _request(
            evidence_scope="abstract",
            rct_only=False,
            publication_year_start=2000,
            publication_year_end=2024,
            allowed_languages=["eng"],
        )
    )

    assert captured["evidence_scope"] == ScreeningEvidenceScope.ABSTRACT
    assert use_case.kwargs["policy"].rct_only is False
    assert use_case.kwargs["policy"].publication_year_start == 2000
    assert use_case.kwargs["policy"].allowed_languages == ["eng"]
