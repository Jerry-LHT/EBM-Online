from __future__ import annotations

from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.criteria_planner import (
    ScreeningCriteriaPlanner,
)


def test_criteria_planner_parses_and_normalizes_output() -> None:
    planner = ScreeningCriteriaPlanner(
        config={"temperature": 0},
        llm_caller=lambda **_: {
            "inclusion_criteria": ["Adults with hypertension", "Adults with hypertension", " Randomized trial "],
            "exclusion_criteria": ["Protocol-only report", ""],
            "rationale": "Operational criteria.",
        },
    )

    result = planner.run(
        question_text="Should adults with hypertension receive exercise?",
        question_pico=QuestionPICO(P=["Adults with hypertension"], I=["exercise"]),
        constraints=WorkflowConstraints(),
    )

    assert result.inclusion_criteria == ["Adults with hypertension", "Randomized trial"]
    assert result.exclusion_criteria == ["Protocol-only report"]
    assert result.rationale == "Operational criteria."


def test_criteria_planner_requires_inclusion_criteria() -> None:
    planner = ScreeningCriteriaPlanner(
        config={"temperature": 0},
        llm_caller=lambda **_: {
            "inclusion_criteria": [],
            "exclusion_criteria": [],
            "rationale": "",
        },
    )

    try:
        planner.run(
            question_text="Question",
            question_pico=QuestionPICO(P=["Adults"], I=["exercise"]),
            constraints=WorkflowConstraints(),
        )
    except ValueError as exc:
        assert "at least one inclusion criterion" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_criteria_planner_drops_outcome_reporting_requirements() -> None:
    planner = ScreeningCriteriaPlanner(
        config={"temperature": 0},
        llm_caller=lambda **_: {
            "inclusion_criteria": [
                "Adults with inflammatory bowel disease.",
                "Outcomes related to disease activity, flare-ups, or quality of life are reported or planned.",
            ],
            "exclusion_criteria": [
                "The intervention is not educational.",
                "Outcome data are not numerically extractable for later synthesis.",
            ],
            "rationale": "Operational criteria.",
        },
    )

    result = planner.run(
        question_text="Question",
        question_pico=QuestionPICO(P=["People with IBD"], I=["education"]),
        constraints=WorkflowConstraints(),
    )

    assert result.inclusion_criteria == ["Adults with inflammatory bowel disease."]
    assert result.exclusion_criteria == ["The intervention is not educational."]


def test_criteria_planner_adds_publication_year_range_constraint() -> None:
    planner = ScreeningCriteriaPlanner(
        config={"temperature": 0},
        llm_caller=lambda **_: {
            "inclusion_criteria": ["Adults with inflammatory bowel disease."],
            "exclusion_criteria": [],
            "rationale": "Operational criteria.",
        },
    )

    result = planner.run(
        question_text="Question",
        question_pico=QuestionPICO(P=["People with IBD"], I=["education"]),
        constraints=WorkflowConstraints(publication_year_range="2000-2024"),
    )

    assert result.inclusion_criteria == [
        "Adults with inflammatory bowel disease.",
        "Publication year is within 2000-2024.",
    ]
