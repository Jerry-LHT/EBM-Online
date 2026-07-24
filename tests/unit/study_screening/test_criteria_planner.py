from __future__ import annotations

from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.full_text_screening_llm.criteria_planner import (
    FullTextScreeningCriteriaPlanner,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.errors import (
    StudyScreeningInvocationError,
)


def test_criteria_planner_parses_and_normalizes_output() -> None:
    planner = FullTextScreeningCriteriaPlanner(
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
    planner = FullTextScreeningCriteriaPlanner(
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
    except StudyScreeningInvocationError as exc:
        assert exc.stage == "criteria_planning"
        assert exc.attempts == 2
    else:
        raise AssertionError("Expected ValueError")


def test_criteria_planner_omits_outcome_context_by_default() -> None:
    captured = {}

    def fake_llm(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return {
            "inclusion_criteria": ["Adults with inflammatory bowel disease."],
            "exclusion_criteria": ["The intervention is not educational."],
            "rationale": "Operational criteria.",
        }

    planner = FullTextScreeningCriteriaPlanner(
        config={"temperature": 0},
        llm_caller=fake_llm,
    )

    result = planner.run(
        question_text="Question",
        question_pico=QuestionPICO(
            P=["People with IBD"],
            I=["education"],
            O=["quality of life"],
        ),
        constraints=WorkflowConstraints(),
    )

    assert result.inclusion_criteria == ["Adults with inflammatory bowel disease."]
    assert result.exclusion_criteria == ["The intervention is not educational."]
    assert "quality of life" not in captured["prompt"]
    assert "Outcome eligibility: disabled" in captured["prompt"]


def test_criteria_planner_leaves_publication_year_to_deterministic_screening() -> None:
    captured = {}

    def fake_llm(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return {
            "inclusion_criteria": ["Adults with inflammatory bowel disease."],
            "exclusion_criteria": [],
            "rationale": "Operational criteria.",
        }

    planner = FullTextScreeningCriteriaPlanner(
        config={"temperature": 0},
        llm_caller=fake_llm,
    )

    result = planner.run(
        question_text="Question",
        question_pico=QuestionPICO(P=["People with IBD"], I=["education"]),
        constraints=WorkflowConstraints(publication_year_range="2000-2024"),
    )

    assert result.inclusion_criteria == ["Adults with inflammatory bowel disease."]
    assert "Handled deterministically outside the LLM" in captured["prompt"]
