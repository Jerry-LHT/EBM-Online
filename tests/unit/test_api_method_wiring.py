from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ebm_backend.online_pipeline.interfaces.api import dependencies
from ebm_backend.online_pipeline.interfaces.api.request_schemas import (
    GradeAssessmentRequest,
    MetaAnalysisRequest,
    OnlineEBMWorkflowRequest,
    Q2PICORequest,
    RiskOfBiasRequest,
    StudyScreeningRequest,
)


@pytest.mark.parametrize(
    "request_type",
    [
        Q2PICORequest,
        StudyScreeningRequest,
        RiskOfBiasRequest,
        MetaAnalysisRequest,
        GradeAssessmentRequest,
        OnlineEBMWorkflowRequest,
    ],
)
def test_formal_api_requests_do_not_expose_method_name(request_type) -> None:
    assert "method_name" not in request_type.model_fields


def test_meta_analysis_request_requires_frozen_screening_scope() -> None:
    assert MetaAnalysisRequest.model_fields["screening_criteria"].is_required()


def test_meta_analysis_and_grade_requests_enforce_workflow_size_limits() -> None:
    with pytest.raises(ValidationError):
        MetaAnalysisRequest(
            review_id="review-1",
            question_text="question",
            question_pico={},
            screening_criteria={},
            included_studies=[f"study-{index}" for index in range(501)],
            articles=[],
        )

    with pytest.raises(ValidationError):
        GradeAssessmentRequest(
            review_id="review-1",
            question_text="question",
            question_pico={},
            screening_criteria={},
            study_characteristics=[{} for _ in range(501)],
            risk_of_bias=[],
            meta_analysis_result={},
        )


@pytest.mark.parametrize(
    ("dependency_name", "factory_name"),
    [
        ("get_q2pico_use_case_for_api", "build_production_q2pico"),
        ("get_study_pio_use_case_for_api", "build_production_study_pio"),
        ("get_risk_of_bias_use_case_for_api", "build_production_risk_of_bias"),
    ],
)
def test_composition_root_uses_business_production_factory(
    monkeypatch,
    dependency_name: str,
    factory_name: str,
) -> None:
    calls: list[dict] = []
    adapter = object()
    monkeypatch.setattr(
        dependencies,
        factory_name,
        lambda **kwargs: calls.append(kwargs) or adapter,
    )

    use_case = getattr(dependencies, dependency_name)()

    assert len(calls) == 1
    if factory_name == "build_production_risk_of_bias":
        assert calls[0]["domain_cache"] is not None
    else:
        assert calls[0] == {}
    assert adapter in vars(use_case).values()


def test_study_screening_composition_root_uses_paired_production_factory(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    planner = object()
    screener = object()
    monkeypatch.setattr(
        dependencies,
        "build_production_study_screening",
        lambda **kwargs: calls.append(kwargs)
        or SimpleNamespace(criteria_planner=planner, article_screener=screener),
    )

    use_case = dependencies.get_study_screening_use_case_for_api()

    assert calls == [{"evidence_scope": dependencies.ScreeningEvidenceScope.FULL_TEXT}]
    assert use_case.criteria_planner is planner
    assert use_case.article_screener is screener


def test_meta_analysis_composition_root_injects_explicit_capabilities(monkeypatch) -> None:
    adapters = {
        "synthesis_planner": object(),
        "study_evidence_agent": object(),
        "analysis_methods_selector": object(),
        "subgroup_analyzer": object(),
        "overall_estimates_calculator": object(),
    }
    llm_config = object()
    seen_configs: list[object] = []
    monkeypatch.setattr(dependencies, "load_llm_config", lambda: llm_config)
    monkeypatch.setattr(
        dependencies,
        "build_production_synthesis_planner",
        lambda *, config: seen_configs.append(config) or adapters["synthesis_planner"],
    )
    monkeypatch.setattr(
        dependencies,
        "build_production_study_evidence_agent",
        lambda *, config: seen_configs.append(config) or adapters["study_evidence_agent"],
    )
    monkeypatch.setattr(dependencies, "build_production_analysis_methods_selector", lambda: adapters["analysis_methods_selector"])
    monkeypatch.setattr(dependencies, "build_production_subgroup_analyzer", lambda: adapters["subgroup_analyzer"])
    monkeypatch.setattr(dependencies, "build_production_overall_estimates_calculator", lambda: adapters["overall_estimates_calculator"])

    use_case = dependencies.get_meta_analysis_use_case_for_api()

    for name, adapter in adapters.items():
        assert getattr(use_case, name) is adapter
    assert seen_configs == [llm_config, llm_config]


def test_grade_composition_root_injects_explicit_domain_capabilities(monkeypatch) -> None:
    adapters = {
        "risk_of_bias": object(),
        "inconsistency": object(),
        "indirectness": object(),
        "imprecision": object(),
    }
    monkeypatch.setattr(dependencies, "build_production_grade_risk_of_bias_assessor", lambda: adapters["risk_of_bias"])
    monkeypatch.setattr(dependencies, "build_production_grade_inconsistency_assessor", lambda: adapters["inconsistency"])
    monkeypatch.setattr(dependencies, "build_production_grade_indirectness_assessor", lambda: adapters["indirectness"])
    monkeypatch.setattr(dependencies, "build_production_grade_imprecision_assessor", lambda: adapters["imprecision"])

    use_case = dependencies.get_grade_use_case_for_api()

    assert use_case.domain_assessors == adapters
