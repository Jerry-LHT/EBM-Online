from __future__ import annotations

import time

import pytest

from benchmark.online_pipeline.study_pio.evaluation.method_adapter import (
    load_study_pio_benchmark_method,
)
from ebm_backend.online_pipeline.application.use_cases.run_study_pio import (
    RunStudyPIO,
    StudyPIOArticleContentMissingError,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.study_characteristics import (
    StudyPIOCharacteristics,
    StudyPopulationCharacteristics,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.extraction_study_pico_slotwise_llm.method import (
    Method,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.factory import (
    build_production_study_pio,
)


class _FakeExtractor:
    def run(self, *, question_pico, study_id, article):
        if study_id == "study-1":
            time.sleep(0.02)
        return StudyPIOCharacteristics(
            study_id=study_id,
            population=StudyPopulationCharacteristics(description=article.metadata.title),
        )


def _article(study_id: str) -> CleanedArticle:
    return CleanedArticle(
        study_id=study_id,
        metadata=ArticleMetadata(title=f"Article {study_id}"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id="methods",
                    title="Methods",
                    text="Participants were randomized.",
                )
            ]
        ),
    )


def test_use_case_runs_studies_concurrently_and_preserves_input_order() -> None:
    use_case = RunStudyPIO(study_pio_extractor=_FakeExtractor(), max_workers=2)

    result = use_case.execute(
        question_pico=QuestionPICO(P=["adults"]),
        included_studies=["study-1", "study-2"],
        articles=[_article("study-2"), _article("study-1")],
    )

    assert [item.study_id for item in result] == ["study-1", "study-2"]
    assert [item.population.description for item in result] == [
        "Article study-1",
        "Article study-2",
    ]


def test_use_case_rejects_missing_study_article() -> None:
    use_case = RunStudyPIO(study_pio_extractor=_FakeExtractor())

    with pytest.raises(ValueError, match="Missing CleanedArticle.*study-2"):
        use_case.execute(
            question_pico=QuestionPICO(),
            included_studies=["study-1", "study-2"],
            articles=[_article("study-1")],
        )


def test_use_case_rejects_empty_full_text_before_extraction() -> None:
    use_case = RunStudyPIO(study_pio_extractor=_FakeExtractor())
    article = CleanedArticle(
        study_id="study-1",
        metadata=ArticleMetadata(title="No full text"),
        xml_content=ArticleXmlContent(),
    )

    with pytest.raises(StudyPIOArticleContentMissingError) as raised:
        use_case.execute(
            question_pico=QuestionPICO(),
            included_studies=["study-1"],
            articles=[article],
        )

    assert raised.value.study_ids == ["study-1"]


def test_use_case_enforces_five_hundred_item_limit() -> None:
    use_case = RunStudyPIO(study_pio_extractor=_FakeExtractor())

    with pytest.raises(ValueError, match="at most 500 included studies"):
        use_case.execute(
            question_pico=QuestionPICO(),
            included_studies=[f"study-{index}" for index in range(501)],
            articles=[],
        )


def test_use_case_rejects_articles_outside_included_set() -> None:
    use_case = RunStudyPIO(study_pio_extractor=_FakeExtractor())

    with pytest.raises(ValueError, match="non-included.*study-2"):
        use_case.execute(
            question_pico=QuestionPICO(),
            included_studies=["study-1"],
            articles=[_article("study-1"), _article("study-2")],
        )


def test_factory_and_benchmark_alias_load_slotwise_llm_method() -> None:
    method = build_production_study_pio()
    benchmark_method = load_study_pio_benchmark_method("study_pio.method_llm")

    assert isinstance(method, Method)
    assert isinstance(benchmark_method.extractor, Method)


@pytest.mark.parametrize("method_name", ["method_rule", "unknown"])
def test_benchmark_adapter_rejects_unconnected_method(method_name: str) -> None:
    with pytest.raises(ValueError, match="Unknown Study PIO benchmark method"):
        load_study_pio_benchmark_method(method_name)
