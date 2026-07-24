"""Explicit factories for the four GRADE domain capabilities."""

from __future__ import annotations


def build_production_grade_risk_of_bias_assessor():
    from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_evidence_body_llm.method import build_method

    return build_method()


def build_production_grade_inconsistency_assessor():
    from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.method import (
        build_method,
    )

    return build_method()


def build_production_grade_indirectness_assessor():
    from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.method import (
        build_method,
    )

    return build_method()


def build_production_grade_imprecision_assessor():
    from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.method import (
        build_method,
    )

    return build_method()
