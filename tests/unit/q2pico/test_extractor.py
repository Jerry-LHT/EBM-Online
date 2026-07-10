from __future__ import annotations

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.q2pico.extractor import (
    Q2PICOSplitLLMExtractor,
)


TEST_CONFIG = {
    "api_key": "sk-test",
    "base_url": "https://llm.example/v1",
    "model": "test-model",
}


def test_run_extracts_split_slots_and_normalizes_values() -> None:
    responses = {
        "participants": {"participants": [" adults with depression ", "adults with depression", ""]},
        "interventions": {"interventions": ["SSRI"]},
        "comparators": {"comparators": ["placebo"]},
        "outcomes": {"outcomes": ["remission"]},
    }
    seen_calls: list[str] = []

    def fake_llm_caller(**kwargs):
        prompt = kwargs["prompt"]
        for key, payload in responses.items():
            if f'"{key}"' in prompt:
                seen_calls.append(key)
                return payload
        raise AssertionError(f"unexpected prompt: {prompt}")

    extractor = Q2PICOSplitLLMExtractor(config=TEST_CONFIG, llm_caller=fake_llm_caller)

    result = extractor.run(question_text="Should adults with depression receive SSRI versus placebo for remission?")

    assert result.P == ["adults with depression"]
    assert result.I == ["SSRI"]
    assert result.C == ["placebo"]
    assert result.O == ["remission"]
    assert result.O_expanded == []
    assert sorted(seen_calls) == ["comparators", "interventions", "outcomes", "participants"]


def test_run_optionally_expands_outcomes() -> None:
    seen_calls: list[str] = []

    def fake_llm_caller(**kwargs):
        prompt = kwargs["prompt"]
        if '"participants"' in prompt:
            seen_calls.append("participants")
            return {"participants": ["patients with dementia and agitation/aggressive behaviour"]}
        if '"interventions"' in prompt:
            seen_calls.append("interventions")
            return {"interventions": ["atypical anti-psychotics"]}
        if '"comparators"' in prompt:
            seen_calls.append("comparators")
            return {"comparators": ["no pharmacological treatment"]}
        if '"outcomes"' in prompt:
            seen_calls.append("outcomes")
            return {"outcomes": []}
        if '"expanded_outcomes"' in prompt:
            seen_calls.append("expanded_outcomes")
            return {"expanded_outcomes": ["agitation severity", "serious adverse events", "mortality"]}
        raise AssertionError(f"unexpected prompt: {prompt}")

    extractor = Q2PICOSplitLLMExtractor(config=TEST_CONFIG, llm_caller=fake_llm_caller)

    result = extractor.run(
        question_text=(
            "Should patients with dementia and agitation/aggressive behaviour be treated "
            "with atypical anti-psychotics compared to no pharmacological treatment?"
        ),
        expand_outcomes=True,
    )

    assert result.O == []
    assert result.O_expanded == ["agitation severity", "serious adverse events", "mortality"]
    assert sorted(seen_calls) == ["comparators", "expanded_outcomes", "interventions", "outcomes", "participants"]


def test_rendered_prompts_keep_runtime_input_and_remove_template_placeholders() -> None:
    extractor = Q2PICOSplitLLMExtractor(config=TEST_CONFIG)

    for label in ("P", "I", "C", "O"):
        prompt = extractor._render_prompt(label=label, question_text="Should adults receive treatment?")
        assert "Should adults receive treatment?" in prompt
        assert "Few-shot" not in prompt
        assert "Question id" not in prompt
        assert "{question_text}" not in prompt
        assert "{few_shot_examples}" not in prompt
        assert "{question_id}" not in prompt

    expansion_prompt = extractor._render_outcome_expansion_prompt(
        question_text="Should adults receive treatment?",
        participants=["adults"],
        interventions=["treatment"],
        comparators=["placebo"],
        explicit_outcomes=["remission"],
    )
    assert "Should adults receive treatment?" in expansion_prompt
    assert '"adults"' in expansion_prompt
    assert '"remission"' in expansion_prompt
    assert "{question_text}" not in expansion_prompt
    assert "{participants}" not in expansion_prompt


def test_run_rejects_missing_required_slot_key() -> None:
    extractor = Q2PICOSplitLLMExtractor(
        config=TEST_CONFIG,
        llm_caller=lambda **kwargs: {"wrong": []},
        labels=("P",),
    )

    with pytest.raises(ValueError, match="participants"):
        extractor.run(question_text="Should adults receive treatment?")


def test_run_normalizes_auto_api_mode_for_existing_llm_helper() -> None:
    seen_config: dict[str, str] = {}

    def fake_llm_caller(**kwargs):
        seen_config.update(kwargs["config"])
        return {"participants": []}

    extractor = Q2PICOSplitLLMExtractor(
        config={**TEST_CONFIG, "api_mode": "auto"},
        llm_caller=fake_llm_caller,
        labels=("P",),
    )

    extractor.run(question_text="Should adults receive treatment?")

    assert seen_config["api_mode"] == "responses"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_workers": 0}, "max_workers"),
        ({"labels": ()}, "labels"),
        ({"labels": ("X",)}, "unsupported Q2PICO labels"),
    ],
)
def test_run_rejects_invalid_runtime_configuration(kwargs: dict[str, object], message: str) -> None:
    extractor = Q2PICOSplitLLMExtractor(config=TEST_CONFIG, **kwargs)

    with pytest.raises(ValueError, match=message):
        extractor.run(question_text="Should adults receive treatment?")
