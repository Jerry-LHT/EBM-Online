"""Benchmark adapter for Study PIO methods."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ebm_backend.online_pipeline.application.use_cases.run_study_pio import RunStudyPIO
from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.factory import (
    build_production_study_pio,
)


@dataclass
class StudyPIOBenchmarkMethod:
    extractor: object

    def configure_for_benchmark(
        self,
        *,
        llm_config: str | Path = "llm.local.json",
        workers: int = 1,
        run_dir: str | Path | None = None,
        resume: bool = False,
    ) -> None:
        if hasattr(self.extractor, "configure_for_benchmark"):
            self.extractor.configure_for_benchmark(
                llm_config=llm_config,
                workers=workers,
                run_dir=run_dir,
                resume=resume,
            )

    def run(
        self,
        *,
        question_pico: QuestionPICO,
        included_studies: list[str],
        articles: list[CleanedArticle],
    ) -> list[StudyPIOCharacteristics]:
        return RunStudyPIO(
            study_pio_extractor=self.extractor,  # type: ignore[arg-type]
            max_workers=1,
        ).execute(
            question_pico=question_pico,
            included_studies=included_studies,
            articles=articles,
        )


def load_study_pio_benchmark_method(method_spec: str) -> StudyPIOBenchmarkMethod:
    method_name = _method_name(method_spec)
    if method_name == "method_llm":
        method_name = "extraction_study_pico_slotwise_llm"
    if method_name != "extraction_study_pico_slotwise_llm":
        raise ValueError(f"Unknown Study PIO benchmark method '{method_name}'")
    extractor = build_production_study_pio()
    return StudyPIOBenchmarkMethod(extractor=extractor)


def _method_name(method_spec: str) -> str:
    for prefix in ("study_pio.", "study_pio_extraction."):
        if method_spec.startswith(prefix):
            return method_spec.removeprefix(prefix)
    return method_spec
