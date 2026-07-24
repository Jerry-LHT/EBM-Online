"""Application ports for study-level review steps."""

from __future__ import annotations

from typing import Protocol

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.meta_analysis import MetaAnalysisSynthesisPlan
from ebm_backend.online_pipeline.domain.risk_of_bias import (
    RiskOfBiasAssessment,
    RiskOfBiasDomainConfig,
)
from ebm_backend.online_pipeline.domain.screening import (
    ArticleSynthesisScreeningResult,
    ArticleScreeningResult,
    CoarseScreeningDecision,
    ScreeningCriteria,
    ScreeningPolicy,
)
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics


class ScreeningCriteriaPlannerPort(Protocol):
    def run(
        self,
        *,
        question_text: str,
        question_pico: QuestionPICO,
        constraints: WorkflowConstraints,
        policy: ScreeningPolicy = ScreeningPolicy(),
    ) -> ScreeningCriteria:
        ...


class StudyArticleScreenerPort(Protocol):
    def run(
        self,
        *,
        criteria: ScreeningCriteria,
        article: CleanedArticle,
    ) -> ArticleScreeningResult:
        ...


class CoarseStudyArticleScreenerPort(Protocol):
    def run(
        self,
        *,
        criteria: ScreeningCriteria,
        synthesis_plan: MetaAnalysisSynthesisPlan,
        article: CleanedArticle,
    ) -> CoarseScreeningDecision:
        ...


class SynthesisReadyStudyArticleScreenerPort(Protocol):
    def run(
        self,
        *,
        criteria: ScreeningCriteria,
        synthesis_plan: MetaAnalysisSynthesisPlan,
        article: CleanedArticle,
    ) -> ArticleSynthesisScreeningResult:
        ...


class StudyPIOExtractionPort(Protocol):
    def run(
        self,
        *,
        question_pico: QuestionPICO,
        study_id: str,
        article: CleanedArticle,
    ) -> StudyPIOCharacteristics:
        ...


class RiskOfBiasPort(Protocol):
    def assess(
        self,
        *,
        study_id: str,
        article: CleanedArticle,
        domain_config: RiskOfBiasDomainConfig,
    ) -> RiskOfBiasAssessment:
        ...
