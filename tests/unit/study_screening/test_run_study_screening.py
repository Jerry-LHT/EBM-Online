from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.application.use_cases.run_study_screening import (
    RunStudyScreening,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria, StudyScreeningResult


@dataclass(frozen=True)
class _FakeMethod:
    def run(self, **kwargs) -> StudyScreeningResult:
        return StudyScreeningResult(
            screening_criteria=ScreeningCriteria(inclusion_criteria=["Adults"]),
            decisions=[],
            included_studies=[],
        )


def test_run_study_screening_delegates_to_method() -> None:
    result = RunStudyScreening(method=_FakeMethod()).execute(
        question_text="Question",
        question_pico=QuestionPICO(P=["Adults"], I=["exercise"]),
        constraints=WorkflowConstraints(),
        articles=[
            CleanedArticle(
                study_id="pmc::1",
                metadata=ArticleMetadata(title="Article"),
                xml_content=ArticleXmlContent(),
            )
        ],
    )

    assert result.screening_criteria.inclusion_criteria == ["Adults"]
