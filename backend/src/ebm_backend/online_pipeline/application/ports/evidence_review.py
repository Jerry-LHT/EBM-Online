"""Application ports for study-level review steps."""

from __future__ import annotations

from typing import Protocol

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.risk_of_bias import RiskOfBiasAssessment
from ebm_backend.online_pipeline.domain.screening import StudyScreeningResult
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics


class StudyScreeningPort(Protocol):
    def run(
        self,
        *,
        question_text: str,
        question_pico: QuestionPICO,
        constraints: WorkflowConstraints,
        articles: list[CleanedArticle],
    ) -> StudyScreeningResult:
        ...


class StudyPIOExtractionPort(Protocol):
    def run(
        self,
        *,
        question_pico: QuestionPICO,
        included_studies: list[str],
        articles: list[CleanedArticle],
    ) -> list[StudyPIOCharacteristics]:
        ...


class RiskOfBiasPort(Protocol):
    def run(self, *, included_studies: list[str], articles: list[CleanedArticle]) -> list[RiskOfBiasAssessment]:
        ...
