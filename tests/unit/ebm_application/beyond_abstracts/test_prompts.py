from benchmark.ebm_application.beyond_abstracts.prompts import (
    agreement_prompt,
    conclusion_prompt,
    groundedness_prompt,
)


def test_conclusion_prompt_is_conclusion_only_and_has_limit() -> None:
    prompt = conclusion_prompt(review_question="Does A help?", evidence={"study": "S1"}, evidence_label="oracle")
    assert "no more than 200 words" in prompt
    assert "Do not write a report" in prompt
    assert "Does A help?" in prompt
    assert '"study": "S1"' in prompt


def test_agreement_and_groundedness_have_separate_information() -> None:
    agreement = agreement_prompt(reference="gold secret", generated="prediction")
    grounding = groundedness_prompt(evidence="actual input", generated="prediction")
    assert "gold secret" in agreement
    assert "actual input" not in agreement
    assert "actual input" in grounding
    assert "gold secret" not in grounding
