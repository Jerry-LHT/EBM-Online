from __future__ import annotations

import pytest

from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.extraction_study_pico_slotwise_llm.pipeline import (
    extract_study_pico,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.errors import (
    StudyPIOInvocationError,
)


def test_pipeline_runs_three_focused_stages_and_assembles_one_result() -> None:
    prompts: list[str] = []
    schemas: dict[str, dict] = {}

    def caller(*, config, system, prompt, json_schema, json_schema_name):
        prompts.append(system)
        schemas[json_schema_name] = json_schema
        if "population characteristics" in system:
            return {
                "population": {
                    "description": "120 adults with hypertension",
                    "eligibility_notes": "age 18 years or older",
                },
                "warnings": [],
            }
        if "intervention and comparator" in system:
            return {
                "interventions": [
                    {"label": "exercise", "description": "supervised exercise weekly"}
                ],
                "comparators": [
                    {"label": "usual care", "description": "usual care alone"}
                ],
                "warnings": [],
            }
        return {
            "outcomes": [
                {
                    "outcome_label": "blood pressure",
                    "measurement": "systolic blood pressure",
                    "timepoints": ["12 weeks"],
                }
            ],
            "warnings": [],
        }

    article = CleanedArticle(
        study_id="study-1",
        metadata=ArticleMetadata(title="Exercise trial"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id="methods",
                    title="Methods",
                    text="Participants were randomized to exercise or usual care.",
                ),
                ArticleSection(
                    section_id="outcomes",
                    title="Outcomes",
                    text="Systolic blood pressure was assessed at 12 weeks.",
                ),
            ]
        ),
    )

    result = extract_study_pico(
        config=object(),  # type: ignore[arg-type]
        caller=caller,
        question_pico=QuestionPICO(
            P=["adults with hypertension"],
            I=["exercise"],
            C=["usual care"],
            O=["blood pressure"],
        ),
        study_id="study-1",
        article=article,
    )

    assert len(prompts) == 3
    assert set(schemas) == {
        "study_pio_population",
        "study_pio_intervention_comparator",
        "study_pio_outcome",
    }
    assert all(schema["additionalProperties"] is False for schema in schemas.values())
    assert result.study_id == "study-1"
    assert result.population.description == "120 adults with hypertension"
    assert result.interventions[0].label == "exercise"
    assert result.comparators[0].label == "usual care"
    assert result.outcomes[0].timepoints == ["12 weeks"]


def test_stage_validation_failure_retries_once_then_recovers() -> None:
    attempts: dict[str, int] = {}

    def caller(*, json_schema_name, **kwargs):
        attempts[json_schema_name] = attempts.get(json_schema_name, 0) + 1
        if json_schema_name == "study_pio_population":
            if attempts[json_schema_name] == 1:
                return {"population": "invalid", "warnings": []}
            return {
                "population": {"description": "Adults", "eligibility_notes": None},
                "warnings": [],
            }
        if json_schema_name == "study_pio_intervention_comparator":
            return {
                "interventions": [{"label": "Drug", "description": "Drug daily"}],
                "comparators": [{"label": "Placebo", "description": "Placebo"}],
                "warnings": [],
            }
        return {
            "outcomes": [
                {
                    "outcome_label": "Mortality",
                    "measurement": "All-cause mortality",
                    "timepoints": [],
                }
            ],
            "warnings": [],
        }

    result = extract_study_pico(
        config=object(),  # type: ignore[arg-type]
        caller=caller,
        question_pico=QuestionPICO(),
        study_id="study-1",
        article=_article(),
    )

    assert result.population.description == "Adults"
    assert attempts["study_pio_population"] == 2
    assert attempts["study_pio_intervention_comparator"] == 1
    assert attempts["study_pio_outcome"] == 1


def test_stage_invalid_timepoints_exhausts_exactly_two_attempts() -> None:
    attempts = 0

    def caller(*, json_schema_name, **kwargs):
        nonlocal attempts
        if json_schema_name == "study_pio_population":
            return {
                "population": {"description": "Adults", "eligibility_notes": None},
                "warnings": [],
            }
        if json_schema_name == "study_pio_intervention_comparator":
            return {"interventions": [], "comparators": [], "warnings": []}
        attempts += 1
        return {
            "outcomes": [
                {
                    "outcome_label": "Mortality",
                    "measurement": "All-cause mortality",
                    "timepoints": "12 weeks",
                }
            ],
            "warnings": [],
        }

    with pytest.raises(StudyPIOInvocationError) as raised:
        extract_study_pico(
            config=object(),  # type: ignore[arg-type]
            caller=caller,
            question_pico=QuestionPICO(),
            study_id="study-1",
            article=_article(),
        )

    assert attempts == 2
    assert raised.value.stage == "outcome"
    assert raised.value.study_id == "study-1"
    assert raised.value.attempts == 2


def _article() -> CleanedArticle:
    return CleanedArticle(
        study_id="study-1",
        metadata=ArticleMetadata(title="Trial"),
        xml_content=ArticleXmlContent(
            sections=[ArticleSection(section_id="methods", title="Methods", text="RCT")]
        ),
    )
