"""Use case for extracting study-level PIO characteristics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from ebm_backend.online_pipeline.application.ports import StudyPIOExtractionPort
from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.study_characteristics import (
    MAX_STUDY_PIO_ITEMS_PER_RUN,
    StudyPIOCharacteristics,
)


class StudyPIOArticleContentMissingError(ValueError):
    """One or more included studies have no usable full-text sections."""

    def __init__(self, *, study_ids: list[str]) -> None:
        joined = ", ".join(study_ids)
        super().__init__(f"Missing usable full text for study_id(s): {joined}")
        self.study_ids = study_ids


@dataclass(frozen=True)
class RunStudyPIO:
    study_pio_extractor: StudyPIOExtractionPort
    max_workers: int = 4

    def execute(
        self,
        *,
        question_pico: QuestionPICO,
        included_studies: list[str],
        articles: list[CleanedArticle],
    ) -> list[StudyPIOCharacteristics]:
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if len(included_studies) > MAX_STUDY_PIO_ITEMS_PER_RUN:
            raise ValueError(
                f"Study PIO accepts at most {MAX_STUDY_PIO_ITEMS_PER_RUN} included studies"
            )
        if len(articles) > MAX_STUDY_PIO_ITEMS_PER_RUN:
            raise ValueError(
                f"Study PIO accepts at most {MAX_STUDY_PIO_ITEMS_PER_RUN} articles"
            )
        if any(not str(study_id).strip() for study_id in included_studies):
            raise ValueError("included_studies must not contain empty study IDs")
        if len(set(included_studies)) != len(included_studies):
            raise ValueError("included_studies must not contain duplicate study IDs")

        articles_by_study: dict[str, CleanedArticle] = {}
        for article in articles:
            if article.study_id in articles_by_study:
                raise ValueError(
                    f"Multiple articles were provided for study_id '{article.study_id}'"
                )
            articles_by_study[article.study_id] = article

        unexpected_studies = [
            study_id for study_id in articles_by_study if study_id not in set(included_studies)
        ]
        if unexpected_studies:
            unexpected = ", ".join(unexpected_studies)
            raise ValueError(
                f"CleanedArticle was provided for non-included study_id(s): {unexpected}"
            )

        missing_studies = [
            study_id for study_id in included_studies if study_id not in articles_by_study
        ]
        if missing_studies:
            missing = ", ".join(missing_studies)
            raise ValueError(f"Missing CleanedArticle for included study_id(s): {missing}")

        if not included_studies:
            return []

        missing_full_text = [
            study_id
            for study_id in included_studies
            if not _has_usable_full_text(articles_by_study[study_id])
        ]
        if missing_full_text:
            raise StudyPIOArticleContentMissingError(study_ids=missing_full_text)

        workers = min(self.max_workers, len(included_studies))
        if workers == 1:
            return [
                self.study_pio_extractor.run(
                    question_pico=question_pico,
                    study_id=study_id,
                    article=articles_by_study[study_id],
                )
                for study_id in included_studies
            ]

        indexed_results: list[tuple[int, StudyPIOCharacteristics]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(
                    self.study_pio_extractor.run,
                    question_pico=question_pico,
                    study_id=study_id,
                    article=articles_by_study[study_id],
                ): index
                for index, study_id in enumerate(included_studies)
            }
            for future in as_completed(future_to_index):
                indexed_results.append((future_to_index[future], future.result()))

        indexed_results.sort(key=lambda item: item[0])
        return [result for _, result in indexed_results]


def _has_usable_full_text(article: CleanedArticle) -> bool:
    return any(section.text.strip() for section in article.xml_content.sections)
