"""Internal stages for one Study PICO slotwise LLM method."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.errors import (
    StudyPIOInvocationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.extraction_study_pico_slotwise_llm.materials import (
    StageName,
    build_stage_materials,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.extraction_study_pico_slotwise_llm.parsing import (
    parse_comparators,
    parse_interventions,
    parse_outcomes,
    parse_population,
    parse_warnings,
    validate_stage_payload,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.extraction_study_pico_slotwise_llm.schemas import (
    stage_response_schema,
)


LLMJSONCaller = Callable[..., dict[str, Any]]
PROMPTS_DIR = Path(__file__).with_name("prompts")
MAX_ATTEMPTS = 2

_PROMPT_FILES: dict[StageName, str] = {
    "population": "population.txt",
    "intervention_comparator": "intervention_comparator.txt",
    "outcome": "outcome.txt",
}


def extract_study_pico(
    *,
    config: LLMConfig,
    caller: LLMJSONCaller,
    question_pico: QuestionPICO,
    study_id: str,
    article: CleanedArticle,
) -> StudyPIOCharacteristics:
    payloads = {
        stage: _run_stage(
            stage=stage,
            config=config,
            caller=caller,
            question_pico=question_pico,
            article=article,
        )
        for stage in ("population", "intervention_comparator", "outcome")
    }

    warnings = [
        warning
        for stage_payload in payloads.values()
        for warning in parse_warnings(stage_payload)
    ]
    notes = "Extracted by extraction_study_pico_slotwise_llm."
    if warnings:
        notes = f"{notes} Warnings: {'; '.join(warnings[:6])}"

    return StudyPIOCharacteristics(
        study_id=study_id,
        population=parse_population(payloads["population"]),
        interventions=parse_interventions(payloads["intervention_comparator"]),
        comparators=parse_comparators(payloads["intervention_comparator"]),
        outcomes=parse_outcomes(payloads["outcome"]),
        notes=notes,
    )


def _run_stage(
    *,
    stage: StageName,
    config: LLMConfig,
    caller: LLMJSONCaller,
    question_pico: QuestionPICO,
    article: CleanedArticle,
) -> dict[str, Any]:
    system_prompt = (PROMPTS_DIR / _PROMPT_FILES[stage]).read_text(encoding="utf-8")
    user_prompt = _user_prompt(
        stage=stage,
        question_pico=question_pico,
        article=article,
    )
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            payload = caller(
                config=config,
                system=system_prompt,
                prompt=user_prompt,
                json_schema=stage_response_schema(stage),
                json_schema_name=f"study_pio_{stage}",
            )
            validate_stage_payload(stage=stage, payload=payload)
            return payload
        except Exception as exc:
            last_error = exc
    raise StudyPIOInvocationError(
        stage=stage,
        study_id=article.study_id,
        attempts=MAX_ATTEMPTS,
    ) from last_error


def _user_prompt(
    *,
    stage: StageName,
    question_pico: QuestionPICO,
    article: CleanedArticle,
) -> str:
    payload = {
        "question_pico": {
            "P": list(question_pico.P),
            "I": list(question_pico.I),
            "C": list(question_pico.C),
            "O": list(question_pico.O),
        },
        "materials": build_stage_materials(
            stage=stage,
            article=article,
            question_pico=question_pico,
        ),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
