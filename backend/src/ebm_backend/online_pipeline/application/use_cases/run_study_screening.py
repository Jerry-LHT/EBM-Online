"""Use case for article-level study screening."""

from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.application.ports import StudyScreeningPort
from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import StudyScreeningResult


@dataclass(frozen=True)
class RunStudyScreening:
    method: StudyScreeningPort

    def execute(
        self,
        *,
        question_text: str,
        question_pico: QuestionPICO,
        constraints: WorkflowConstraints,
        articles: list[CleanedArticle],
    ) -> StudyScreeningResult:
        return self.method.run(
            question_text=question_text,
            question_pico=question_pico,
            constraints=constraints,
            articles=articles,
        )
