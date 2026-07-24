"""Explicit factories for the Meta-analysis business capabilities."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig


def build_production_synthesis_planner(
    *,
    config: LLMConfig | dict[str, Any] | None = None,
):
    from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.synthesis_planning.synthesis_plan_llm.method import (
        build_method,
    )

    return build_method(config=config)


def build_production_study_evidence_agent(
    *,
    config: LLMConfig | dict[str, Any] | None = None,
):
    """Build the bounded source-workspace Study Evidence adapter."""

    from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.source_workspace_agent.method import (
        build_method,
    )

    return build_method(config=config)


def build_production_analysis_methods_selector():
    from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.analysis_method_selection.contextual.method import (
        build_method,
    )

    return build_method()


def build_production_subgroup_analyzer():
    from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subgroup_analysis.statistical.method import (
        build_method,
    )

    return build_method()


def build_production_overall_estimates_calculator():
    from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.overall_estimation.statistical.method import (
        build_method,
    )

    return build_method()
