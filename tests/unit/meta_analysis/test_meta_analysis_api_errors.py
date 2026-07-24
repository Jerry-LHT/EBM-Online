from __future__ import annotations

import pytest
from fastapi import HTTPException

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.errors import (
    MetaAnalysisConfigurationError,
    MetaAnalysisInvocationError,
    MetaAnalysisOutputError,
)
from ebm_backend.online_pipeline.interfaces.api.routes_modules import (
    _run_meta_analysis_module,
)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (
            MetaAnalysisConfigurationError(stage="synthesis_planning"),
            503,
            "meta_analysis_configuration_unavailable",
        ),
        (
            MetaAnalysisInvocationError(
                stage="candidate_resolution",
                attempts=2,
                retry_exhausted=True,
                context_id="setting-1::study-1",
            ),
            502,
            "meta_analysis_stage_retry_exhausted",
        ),
        (
            MetaAnalysisInvocationError(
                stage="candidate_resolution",
                attempts=1,
                retry_exhausted=False,
            ),
            502,
            "meta_analysis_stage_invocation_failed",
        ),
        (
            MetaAnalysisOutputError(
                stage="study_result_extraction",
                attempts=2,
            ),
            502,
            "meta_analysis_invalid_method_output",
        ),
        (
            ValueError("included_studies contains duplicates"),
            400,
            "meta_analysis_invalid_input",
        ),
    ],
)
def test_meta_analysis_errors_have_stable_api_codes(
    error: Exception,
    status: int,
    code: str,
) -> None:
    def fail():
        raise error

    with pytest.raises(HTTPException) as raised:
        _run_meta_analysis_module(fail)

    assert raised.value.status_code == status
    assert raised.value.detail["code"] == code


def test_meta_analysis_api_preserves_provider_failure_diagnostics() -> None:
    error = MetaAnalysisInvocationError(
        stage="source_workspace_verification",
        attempts=2,
        retry_exhausted=True,
        context_id="review-1::study-1",
        failure_code="provider_timeout",
        request_id="request-1",
        failure_detail="Request timed out.",
    )

    with pytest.raises(HTTPException) as raised:
        _run_meta_analysis_module(lambda: (_ for _ in ()).throw(error))

    assert raised.value.detail["failure_code"] == "provider_timeout"
    assert raised.value.detail["request_id"] == "request-1"
    assert raised.value.detail["failure_detail"] == "Request timed out."
