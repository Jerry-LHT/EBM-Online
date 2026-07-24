"""Factory for study-screening infrastructure methods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ebm_backend.online_pipeline.domain.screening import ScreeningEvidenceScope
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.abstract_screening_llm import (
    AbstractScreeningCriteriaPlanner,
    AbstractStudyArticleScreener,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.full_text_screening_llm import (
    FullTextScreeningCriteriaPlanner,
    FullTextStudyArticleScreener,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.staged_synthesis_screening_llm import (
    CoarseSynthesisStudyArticleScreener,
    SynthesisReadyStudyArticleScreener,
)


@dataclass(frozen=True)
class StudyScreeningMethodPair:
    """A criteria planner and screener designed for the same evidence scope."""

    criteria_planner: AbstractScreeningCriteriaPlanner | FullTextScreeningCriteriaPlanner
    article_screener: AbstractStudyArticleScreener | FullTextStudyArticleScreener | None = None
    coarse_screener: CoarseSynthesisStudyArticleScreener | None = None
    synthesis_ready_screener: SynthesisReadyStudyArticleScreener | None = None


def build_production_study_screening(
    *,
    evidence_scope: ScreeningEvidenceScope = ScreeningEvidenceScope.FULL_TEXT,
) -> StudyScreeningMethodPair:
    """Build the production method pair for the requested business evidence scope."""
    if evidence_scope == ScreeningEvidenceScope.ABSTRACT:
        return StudyScreeningMethodPair(
            criteria_planner=AbstractScreeningCriteriaPlanner(),
            article_screener=AbstractStudyArticleScreener(),
        )
    if evidence_scope == ScreeningEvidenceScope.FULL_TEXT:
        return StudyScreeningMethodPair(
            criteria_planner=FullTextScreeningCriteriaPlanner(),
            article_screener=FullTextStudyArticleScreener(),
        )
    raise ValueError(f"Unsupported Study Screening evidence scope: {evidence_scope}")


def build_production_staged_study_screening(
    *,
    config: Any | None = None,
) -> StudyScreeningMethodPair:
    """Build the workflow screener: one planner, coarse pass, precise pass."""
    return StudyScreeningMethodPair(
        criteria_planner=FullTextScreeningCriteriaPlanner(config=config),
        coarse_screener=CoarseSynthesisStudyArticleScreener(config=config),
        synthesis_ready_screener=SynthesisReadyStudyArticleScreener(config=config),
    )
