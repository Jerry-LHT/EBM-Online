from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_grade import (
    _grade_risk_of_bias_input,
    _summarize_grade_risk_of_bias,
)
from ebm_backend.online_pipeline.domain.grade import (
    GRADERiskOfBiasCoverage,
    GRADERiskOfBiasDomainEvidence,
    GRADERiskOfBiasInput,
    GRADERiskOfBiasSetting,
    GRADERiskOfBiasStudyEvidence,
)
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSubgroup,
    AnalysisTimepoint,
)
from ebm_backend.online_pipeline.domain.risk_of_bias import RiskOfBiasAssessment
from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_evidence_body_llm.errors import (
    GRADERiskOfBiasInvocationError,
    GRADERiskOfBiasJudgementError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_evidence_body_llm.method import (
    build_method,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMAPIError


CORE_FIVE = [
    "random_sequence_generation",
    "allocation_concealment",
    "blinding_participants_personnel",
    "blinding_outcome_assessment",
    "incomplete_outcome_data",
]
FULL_SEVEN = [*CORE_FIVE, "selective_reporting", "other_bias"]


def _study(
    study_id: str,
    *,
    domains: list[str] = CORE_FIVE,
    high_domains: set[str] | None = None,
    weight: float | None = None,
) -> GRADERiskOfBiasStudyEvidence:
    high_domains = high_domains or set()
    profile = "rob1_full_7" if domains == FULL_SEVEN else "rob1_core_5"
    return GRADERiskOfBiasStudyEvidence(
        study_id=study_id,
        contribution_weight=weight,
        rob_available=True,
        assessment_scope="article_level",
        assessment_profile=profile,
        assessed_domains=list(domains),
        unassessed_domains=[domain for domain in FULL_SEVEN if domain not in domains],
        domains=[
            GRADERiskOfBiasDomainEvidence(
                domain=domain,
                judgement="high_risk" if domain in high_domains else "low_risk",
                rationale=f"Evidence for {domain}.",
            )
            for domain in domains
        ],
    )


def _input(
    studies: list[GRADERiskOfBiasStudyEvidence],
    *,
    contribution_basis: str,
    missing: list[str] | None = None,
) -> GRADERiskOfBiasInput:
    missing = missing or []
    assessed = [study.study_id for study in studies]
    missing_studies = [
        GRADERiskOfBiasStudyEvidence(
            study_id=study_id,
            contribution_weight=None,
            rob_available=False,
            assessment_scope="article_level",
            assessment_profile="rob1_custom",
            assessed_domains=[],
            unassessed_domains=list(FULL_SEVEN),
            domains=[],
        )
        for study_id in missing
    ]
    all_studies = [*studies, *missing_studies]
    return GRADERiskOfBiasInput(
        setting=GRADERiskOfBiasSetting(
            setting_id="setting-1",
            population="Adults",
            comparison=AnalysisComparison(
                experimental="Intervention",
                comparator="Control",
            ),
            outcome=AnalysisOutcome(
                label="Patient-reported pain",
                measure="Validated pain scale",
            ),
            timepoint=AnalysisTimepoint(label="12 weeks"),
            subgroup=AnalysisSubgroup(),
        ),
        contribution_basis=contribution_basis,
        contributing_studies=all_studies,
        coverage=GRADERiskOfBiasCoverage(
            expected_study_ids=[*assessed, *missing],
            assessed_study_ids=assessed,
            missing_rob_study_ids=missing,
            weight_status=(
                "complete" if contribution_basis == "meta_analysis_weight" else "unavailable"
            ),
        ),
        summary=_summarize_grade_risk_of_bias(all_studies),
    )


def test_weighted_summary_supports_core_five_and_full_seven_without_filling_missing_domains() -> None:
    grade_input = _input(
        [
            _study(
                "study-high",
                domains=CORE_FIVE,
                high_domains={"allocation_concealment"},
                weight=0.65,
            ),
            _study("study-low", domains=FULL_SEVEN, weight=0.35),
        ],
        contribution_basis="meta_analysis_weight",
    )

    summaries = {item.domain: item for item in grade_input.summary.domain_summaries}
    allocation = summaries["allocation_concealment"]
    reporting = summaries["selective_reporting"]

    assert allocation.assessed_study_count == 2
    assert allocation.high_risk_weight == 0.65
    assert allocation.low_risk_weight == 0.35
    assert reporting.assessed_study_count == 1
    assert reporting.low_risk_weight == 0.35
    assert grade_input.summary.profile_counts == {
        "rob1_core_5": 1,
        "rob1_full_7": 1,
    }


def test_weighted_input_rejects_missing_or_non_normalized_weights() -> None:
    with pytest.raises(ValueError, match="every contributing study weight"):
        _input(
            [_study("A", weight=0.6), _study("B", weight=None)],
            contribution_basis="meta_analysis_weight",
        )
    with pytest.raises(ValueError, match="sum to approximately 1"):
        _input(
            [_study("A", weight=0.4), _study("B", weight=0.4)],
            contribution_basis="meta_analysis_weight",
        )


def test_weighted_input_keeps_missing_rob_study_in_contribution_denominator() -> None:
    assessed = _study("assessed", weight=0.8)
    missing = GRADERiskOfBiasStudyEvidence(
        study_id="missing-rob",
        contribution_weight=0.2,
        rob_available=False,
        assessment_scope="article_level",
        assessment_profile="rob1_custom",
        assessed_domains=[],
        unassessed_domains=list(FULL_SEVEN),
        domains=[],
    )
    grade_input = GRADERiskOfBiasInput(
        setting=_input(
            [_study("setting-source")], contribution_basis="study_count"
        ).setting,
        contribution_basis="meta_analysis_weight",
        contributing_studies=[assessed, missing],
        coverage=GRADERiskOfBiasCoverage(
            expected_study_ids=["assessed", "missing-rob"],
            assessed_study_ids=["assessed"],
            missing_rob_study_ids=["missing-rob"],
            weight_status="complete",
        ),
        summary=_summarize_grade_risk_of_bias([assessed, missing]),
    )

    assert [
        study.contribution_weight for study in grade_input.contributing_studies
    ] == [0.8, 0.2]
    assert grade_input.coverage.missing_rob_study_ids == ["missing-rob"]


def test_method_uses_strict_schema_and_engineering_derives_levels() -> None:
    captured = {}

    def caller(**kwargs):
        captured.update(kwargs)
        return {
            "assessment_status": "completed",
            "severity": "very_serious",
            "rationale": "A dominant high-risk study drives the evidence body.",
            "driving_evidence": [
                {
                    "study_id": "study-high",
                    "domains": ["allocation_concealment"],
                }
            ],
        }

    grade_input = _input(
        [
            _study(
                "study-high",
                high_domains={"allocation_concealment"},
                weight=0.7,
            ),
            _study("study-low", weight=0.3),
        ],
        contribution_basis="meta_analysis_weight",
    )
    result = build_method(config={"model": "fake"}, caller=caller).run(
        grade_input=grade_input
    )

    assert captured["json_schema_name"] == "grade_risk_of_bias_evidence_body"
    assert captured["json_schema"]["additionalProperties"] is False
    assert captured["config"]["sdk_max_retries"] == 0
    assert captured["config"]["json_marker_retry_enabled"] is False
    assert "effect_value" not in captured["prompt"]
    prompt_payload = json.loads(captured["prompt"].split("Input JSON:\n", 1)[1])
    assert prompt_payload["contribution_basis"] == "meta_analysis_weight"
    assert [
        study["contribution_weight"]
        for study in prompt_payload["contributing_studies"]
    ] == [0.7, 0.3]
    allocation_summary = next(
        item
        for item in prompt_payload["summary"]["domain_summaries"]
        if item["domain"] == "allocation_concealment"
    )
    assert allocation_summary["high_risk_weight"] == 0.7
    assert result["downgraded"] == "yes"
    assert result["severity"] == "very_serious"
    assert result["levels"] == 2


def test_method_retries_once_for_invalid_driver_reference() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        study_id = "not-contributing" if calls == 1 else "study-1"
        return {
            "assessment_status": "completed",
            "severity": "serious",
            "rationale": "Important concern.",
            "driving_evidence": [
                {
                    "study_id": study_id,
                    "domains": ["allocation_concealment"],
                }
            ],
        }

    result = build_method(config={"model": "fake"}, caller=caller).run(
        grade_input=_input(
            [_study("study-1", high_domains={"allocation_concealment"})],
            contribution_basis="study_count",
        )
    )

    assert calls == 2
    assert result["levels"] == 1


def test_downgrade_requires_an_exact_driving_evidence_reference() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        return {
            "assessment_status": "completed",
            "severity": "serious",
            "rationale": "Important concern without a traceable driver.",
            "driving_evidence": [],
        }

    with pytest.raises(GRADERiskOfBiasJudgementError):
        build_method(config={"model": "fake"}, caller=caller).run(
            grade_input=_input(
                [_study("study-1", high_domains={"allocation_concealment"})],
                contribution_basis="study_count",
            )
        )

    assert calls == 2


def test_method_fails_after_one_retry_instead_of_returning_not_evaluable() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        return {
            "assessment_status": "completed",
            "severity": "serious",
            "rationale": "Invalid reference.",
            "driving_evidence": [
                {
                    "study_id": "not-contributing",
                    "domains": ["allocation_concealment"],
                }
            ],
        }

    with pytest.raises(GRADERiskOfBiasJudgementError) as raised:
        build_method(config={"model": "fake"}, caller=caller).run(
            grade_input=_input(
                [_study("study-1")],
                contribution_basis="study_count",
            )
        )

    assert calls == 2
    assert raised.value.attempts == 2


def test_method_retries_expected_provider_error_once() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        raise LLMAPIError(
            "temporary provider failure",
            status_code=503,
            request_id="request-1",
            retry_after_seconds=None,
            retryable=True,
            provider_message="temporarily unavailable",
        )

    with pytest.raises(GRADERiskOfBiasInvocationError) as raised:
        build_method(config={"model": "fake"}, caller=caller).run(
            grade_input=_input(
                [_study("study-1")],
                contribution_basis="study_count",
            )
        )

    assert calls == 2
    assert raised.value.attempts == 2


def test_method_does_not_retry_nonretryable_provider_error() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        raise LLMAPIError(
            "invalid provider request",
            status_code=400,
            request_id="request-1",
            retry_after_seconds=None,
            retryable=False,
            provider_message="invalid request",
        )

    with pytest.raises(GRADERiskOfBiasInvocationError) as raised:
        build_method(config={"model": "fake"}, caller=caller).run(
            grade_input=_input(
                [_study("study-1")],
                contribution_basis="study_count",
            )
        )

    assert calls == 1
    assert raised.value.attempts == 1
    assert raised.value.retry_exhausted is False


def test_method_does_not_retry_unexpected_programming_error() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("unexpected implementation defect")

    with pytest.raises(RuntimeError, match="unexpected implementation defect"):
        build_method(config={"model": "fake"}, caller=caller).run(
            grade_input=_input(
                [_study("study-1")],
                contribution_basis="study_count",
            )
        )

    assert calls == 1


def test_method_returns_not_evaluable_without_llm_when_all_rob_is_missing() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("LLM must not be called")

    result = build_method(config={"model": "fake"}, caller=caller).run(
        grade_input=_input(
            [],
            contribution_basis="study_count",
            missing=["study-1"],
        )
    )

    assert calls == 0
    assert result == {
        "domain": "risk_of_bias",
        "assessment_status": "insufficient_evidence",
        "downgraded": "unclear",
        "severity": "unclear",
        "levels": "unclear",
        "level_evaluable": False,
        "rationale": (
            "No study-level risk-of-bias assessment is available for the "
            "studies contributing to this evidence body."
        ),
        "source_spans": [],
    }


def test_empty_upstream_assessment_is_treated_as_missing_rob() -> None:
    grade_input = _grade_risk_of_bias_input(
        setting=SimpleNamespace(
            setting_id="setting-empty-rob",
            population_scope="Adults",
            comparison=AnalysisComparison(
                experimental="Intervention",
                comparator="Control",
            ),
            outcome=AnalysisOutcome(label="Outcome"),
            timepoint=AnalysisTimepoint(),
            subgroup=AnalysisSubgroup(),
        ),
        estimate=SimpleNamespace(
            included_study_ids=["study-1"],
            estimation_status="computed",
        ),
        data_rows=[],
        risk_of_bias=[RiskOfBiasAssessment(study_id="study-1")],
    )

    assert grade_input.coverage.assessed_study_ids == []
    assert grade_input.coverage.missing_rob_study_ids == ["study-1"]
    assert grade_input.contributing_studies[0].rob_available is False

    result = build_method(
        config={"model": "fake"},
        caller=lambda **_kwargs: pytest.fail("LLM must not be called"),
    ).run(grade_input=grade_input)

    assert result["downgraded"] == "unclear"
    assert result["level_evaluable"] is False
