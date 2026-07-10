"""Default study-screening method."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import (
    ScreeningCriteria,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
    ScreeningDecision,
    StudyScreeningResult,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.article_screener import (
    ArticleScreeningResult,
    StudyScreeningArticleScreener,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.criteria_planner import (
    ScreeningCriteriaPlanner,
)


@dataclass(frozen=True)
class Method:
    criteria_planner: ScreeningCriteriaPlanner = field(default_factory=ScreeningCriteriaPlanner)
    article_screener: StudyScreeningArticleScreener = field(default_factory=StudyScreeningArticleScreener)
    max_workers: int = 4

    def run(
        self,
        *,
        question_text: str,
        question_pico: QuestionPICO,
        constraints: WorkflowConstraints,
        articles: list[CleanedArticle],
    ) -> StudyScreeningResult:
        if not question_text.strip():
            raise ValueError("question_text is required")
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")

        criteria = self.criteria_planner.run(
            question_text=question_text,
            question_pico=question_pico,
            constraints=constraints,
        )
        decisions = self._screen_articles(
            criteria=criteria,
            articles=articles,
        )
        included_studies = [decision.study_id for decision in decisions if decision.decision == "include"]
        return StudyScreeningResult(
            screening_criteria=criteria,
            decisions=decisions,
            included_studies=included_studies,
        )

    def _screen_articles(
        self,
        *,
        criteria: ScreeningCriteria,
        articles: list[CleanedArticle],
    ) -> list[ScreeningDecision]:
        if not articles:
            return []
        indexed_articles = list(enumerate(articles))
        workers = min(self.max_workers, len(indexed_articles))
        results: list[tuple[int, ScreeningDecision]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(
                    self._screen_one_article,
                    criteria=criteria,
                    article=article,
                ): index
                for index, article in indexed_articles
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                results.append((index, future.result()))
        results.sort(key=lambda item: item[0])
        return [decision for _, decision in results]

    def _screen_one_article(
        self,
        *,
        criteria: ScreeningCriteria,
        article: CleanedArticle,
    ) -> ScreeningDecision:
        result = self.article_screener.run(
            criteria=criteria,
            article=article,
        )
        decision, rationale, exclusion_reason = _aggregate_screening_decision(
            criterion_result=result,
            criteria=criteria,
        )
        source_spans = [span for judgment in result.criterion_judgments for span in judgment.source_spans]
        return ScreeningDecision(
            study_id=article.study_id,
            decision=decision,
            rationale=rationale,
            exclusion_reason=exclusion_reason,
            criterion_judgments=result.criterion_judgments,
            source_spans=source_spans,
        )


def _aggregate_screening_decision(
    *,
    criterion_result: ArticleScreeningResult,
    criteria: ScreeningCriteria,
) -> tuple[str, str, str | None]:
    for judgment in criterion_result.criterion_judgments:
        if (
            judgment.criterion_type == ScreeningCriterionType.EXCLUSION
            and judgment.judgment == ScreeningCriterionJudgmentValue.YES
        ):
            reason = judgment.reason or f"Matched exclusion criterion: {judgment.criterion_text}"
            return "exclude", reason, judgment.criterion_text

    for judgment in criterion_result.criterion_judgments:
        if (
            judgment.criterion_type == ScreeningCriterionType.INCLUSION
            and judgment.judgment == ScreeningCriterionJudgmentValue.NO
        ):
            reason = judgment.reason or f"Failed inclusion criterion: {judgment.criterion_text}"
            return "exclude", reason, judgment.criterion_text

    rationale = criterion_result.overall_note.strip() or "No decisive exclusion signal found; conservatively include."
    return "include", rationale, None


def build_method() -> Method:
    return Method()
