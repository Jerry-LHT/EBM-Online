"""Public adapter for slotwise LLM extraction of one study's PICO."""

from __future__ import annotations

from pathlib import Path

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics
from ebm_backend.online_pipeline.infrastructure.llm import call_llm_json, load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.errors import (
    StudyPIOConfigurationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.extraction_study_pico_slotwise_llm.pipeline import (
    LLMJSONCaller,
    extract_study_pico,
)


class Method:
    def __init__(self, *, caller: LLMJSONCaller = call_llm_json) -> None:
        self.caller = caller
        self.llm_config_path = Path("llm.local.json")

    def configure_for_benchmark(
        self,
        *,
        llm_config: str | Path = "llm.local.json",
        workers: int = 1,
        run_dir: str | Path | None = None,
        resume: bool = False,
    ) -> None:
        self.llm_config_path = Path(llm_config)

    def run(
        self,
        *,
        question_pico: QuestionPICO,
        study_id: str,
        article: CleanedArticle,
    ) -> StudyPIOCharacteristics:
        if article.study_id != study_id:
            raise ValueError(
                f"article.study_id '{article.study_id}' does not match study_id '{study_id}'"
            )
        try:
            config = load_llm_config(self.llm_config_path)
            if config is None:
                raise RuntimeError("Missing required LLM config")
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise StudyPIOConfigurationError(
                "Study PIO LLM configuration is unavailable"
            ) from exc
        return extract_study_pico(
            config=config,
            caller=self.caller,
            question_pico=question_pico,
            study_id=study_id,
            article=article,
        )


def build_method() -> Method:
    return Method()
