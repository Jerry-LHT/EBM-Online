import json

import pytest

from benchmark.ebm_application.beyond_abstracts.evaluation import (
    evaluate_conclusion,
    validate_conclusion,
)


class FakeJudge:
    def __init__(self) -> None:
        self.agreement = iter([4, 3, 4])
        self.groundedness = iter([2, 3, 4])

    def __call__(self, **kwargs):
        if "agreement" in kwargs["schema_name"]:
            return {"score": next(self.agreement), "reasoning": "semantic comparison"}
        return {
            "score": next(self.groundedness),
            "effect_direction_correct": True,
            "limitations_reflected": True,
            "overclaiming": False,
            "unsupported_claims": [],
            "reasoning": "evidence audit",
        }


def test_three_vote_evaluation_aggregates_and_persists_each_vote(tmp_path) -> None:
    result = evaluate_conclusion(
        reference_conclusion="Treatment may help, but evidence is uncertain.",
        generated_conclusion="Treatment may help, but evidence is uncertain.",
        generation_evidence={"effect": "possible benefit"},
        judge=FakeJudge(),
        artifact_dir=tmp_path,
    )
    assert result["scope"] == "final_conclusion_only"
    assert result["agreement"]["score"] == 4
    assert result["agreement"]["agreement"] is True
    assert result["groundedness"]["score"] == 3  # median tie-break
    assert (tmp_path / "agreement" / "vote_01.json").exists()
    assert (tmp_path / "groundedness" / "vote_03.json").exists()
    persisted = json.loads((tmp_path / "evaluation_summary.json").read_text())
    assert persisted["agreement"]["scores"] == [4, 3, 4]


def test_conclusion_validation_enforces_200_words() -> None:
    assert validate_conclusion("one two")["valid"] is True
    assert validate_conclusion(" ")["valid"] is False
    assert validate_conclusion("word " * 201)["within_word_limit"] is False


def test_repetitions_must_be_positive_and_odd() -> None:
    with pytest.raises(ValueError, match="positive odd"):
        evaluate_conclusion(
            reference_conclusion="gold", generated_conclusion="generated",
            generation_evidence="evidence", judge=FakeJudge(), repetitions=2,
        )
