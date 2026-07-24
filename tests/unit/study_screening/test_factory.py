from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.study_screening.abstract_screening_llm import (
    AbstractScreeningCriteriaPlanner,
    AbstractStudyArticleScreener,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.factory import (
    StudyScreeningMethodPair,
    build_production_staged_study_screening,
    build_production_study_screening,
)
from ebm_backend.online_pipeline.domain.screening import ScreeningEvidenceScope
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.full_text_screening_llm import (
    FullTextScreeningCriteriaPlanner,
    FullTextStudyArticleScreener,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.staged_synthesis_screening_llm import (
    CoarseSynthesisStudyArticleScreener,
    SynthesisReadyStudyArticleScreener,
)


def test_factory_builds_application_port_adapters() -> None:
    method_pair = build_production_study_screening()

    assert isinstance(method_pair, StudyScreeningMethodPair)
    assert isinstance(method_pair.criteria_planner, FullTextScreeningCriteriaPlanner)
    assert isinstance(method_pair.article_screener, FullTextStudyArticleScreener)

    abstract_pair = build_production_study_screening(
        evidence_scope=ScreeningEvidenceScope.ABSTRACT,
    )
    assert isinstance(abstract_pair.criteria_planner, AbstractScreeningCriteriaPlanner)
    assert isinstance(abstract_pair.article_screener, AbstractStudyArticleScreener)


def test_factory_builds_staged_workflow_screeners() -> None:
    pair = build_production_staged_study_screening(config={"api_mode": "responses"})

    assert pair.article_screener is None
    assert isinstance(pair.coarse_screener, CoarseSynthesisStudyArticleScreener)
    assert isinstance(pair.synthesis_ready_screener, SynthesisReadyStudyArticleScreener)
