from __future__ import annotations

import pytest
from fastapi import HTTPException

from ebm_backend.online_pipeline.interfaces.api.routes_modules import (
    _run_grade_module,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_evidence_body_llm.errors import (
    GRADERiskOfBiasConfigurationError,
    GRADERiskOfBiasInvocationError,
    GRADERiskOfBiasJudgementError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.errors import (
    GRADEInconsistencyConfigurationError,
    GRADEInconsistencyInvocationError,
    GRADEInconsistencyJudgementError,
    GRADEInconsistencyPolicyError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.errors import (
    GRADEIndirectnessClassificationError,
    GRADEIndirectnessConfigurationError,
    GRADEIndirectnessInvocationError,
    GRADEIndirectnessJudgementError,
    GRADEIndirectnessThresholdError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.errors import (
    GRADEImprecisionConfigurationError,
    GRADEImprecisionInvocationError,
    GRADEImprecisionThresholdError,
)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (
            GRADERiskOfBiasConfigurationError("missing config"),
            503,
            "grade_risk_of_bias_configuration_unavailable",
        ),
        (
            GRADERiskOfBiasInvocationError(
                setting_id="setting-1",
                attempts=2,
            ),
            502,
            "grade_risk_of_bias_retry_exhausted",
        ),
        (
            GRADERiskOfBiasInvocationError(
                setting_id="setting-1",
                attempts=1,
                retry_exhausted=False,
            ),
            502,
            "grade_risk_of_bias_invocation_failed",
        ),
        (
            GRADERiskOfBiasJudgementError(
                setting_id="setting-1",
                attempts=2,
            ),
            502,
            "grade_risk_of_bias_invalid_judgement_output",
        ),
        (
            GRADEInconsistencyConfigurationError("missing config"),
            503,
            "grade_inconsistency_configuration_unavailable",
        ),
        (
            GRADEInconsistencyInvocationError(
                setting_id="setting-1",
                stage="judgement",
                attempts=2,
                retry_exhausted=True,
            ),
            502,
            "grade_inconsistency_retry_exhausted",
        ),
        (
            GRADEInconsistencyInvocationError(
                setting_id="setting-1",
                stage="policy_generation",
                attempts=1,
                retry_exhausted=False,
            ),
            502,
            "grade_inconsistency_invocation_failed",
        ),
        (
            GRADEInconsistencyPolicyError(
                setting_id="setting-1",
                attempts=2,
            ),
            502,
            "grade_inconsistency_invalid_policy_output",
        ),
        (
            GRADEInconsistencyJudgementError(
                setting_id="setting-1",
                attempts=2,
            ),
            502,
            "grade_inconsistency_invalid_judgement_output",
        ),
        (
            GRADEIndirectnessConfigurationError("missing config"),
            503,
            "grade_indirectness_configuration_unavailable",
        ),
        (
            GRADEIndirectnessInvocationError(
                setting_id="setting-1",
                stage="study_classification",
                attempts=2,
                retry_exhausted=True,
            ),
            502,
            "grade_indirectness_retry_exhausted",
        ),
        (
            GRADEIndirectnessInvocationError(
                setting_id="setting-1",
                stage="evidence_body_judgement",
                attempts=1,
                retry_exhausted=False,
            ),
            502,
            "grade_indirectness_invocation_failed",
        ),
        (
            GRADEIndirectnessClassificationError(
                setting_id="setting-1",
                attempts=2,
            ),
            502,
            "grade_indirectness_invalid_classification_output",
        ),
        (
            GRADEIndirectnessJudgementError(
                setting_id="setting-1",
                attempts=2,
            ),
            502,
            "grade_indirectness_invalid_judgement_output",
        ),
        (
            GRADEIndirectnessThresholdError(
                setting_id="setting-1",
                attempts=2,
            ),
            502,
            "grade_indirectness_invalid_threshold_output",
        ),
        (
            GRADEImprecisionConfigurationError("missing config"),
            503,
            "grade_imprecision_configuration_unavailable",
        ),
        (
            GRADEImprecisionInvocationError(
                setting_id="setting-1",
                attempts=2,
                retry_exhausted=True,
            ),
            502,
            "grade_imprecision_retry_exhausted",
        ),
        (
            GRADEImprecisionInvocationError(
                setting_id="setting-1",
                attempts=1,
                retry_exhausted=False,
            ),
            502,
            "grade_imprecision_invocation_failed",
        ),
        (
            GRADEImprecisionThresholdError(
                setting_id="setting-1",
                attempts=2,
            ),
            502,
            "grade_imprecision_invalid_threshold_output",
        ),
    ],
)
def test_grade_risk_of_bias_errors_have_stable_api_codes(
    error: Exception,
    status: int,
    code: str,
) -> None:
    def fail():
        raise error

    with pytest.raises(HTTPException) as raised:
        _run_grade_module(fail)

    assert raised.value.status_code == status
    assert raised.value.detail["code"] == code
