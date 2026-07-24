from __future__ import annotations

from collections import defaultdict
from threading import Lock

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.q2pico.errors import (
    Q2PICOInvocationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.q2pico.split_slot_llm.extractor import (
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

    result = extractor.run(
        question_text="Should adults with depression receive SSRI versus placebo for remission?",
        expand_outcomes=False,
    )

    assert result.P == ["adults with depression"]
    assert result.I == ["SSRI"]
    assert result.C == ["placebo"]
    assert result.O == ["remission"]
    assert result.O_expanded == []
    assert sorted(seen_calls) == ["comparators", "interventions", "outcomes", "participants"]


def test_run_expands_outcomes_by_default() -> None:
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
    )

    assert result.O == []
    assert result.O_expanded == ["agitation severity", "serious adverse events", "mortality"]
    assert sorted(seen_calls) == ["comparators", "expanded_outcomes", "interventions", "outcomes", "participants"]


def test_run_retries_only_the_failed_slot_once_and_sends_its_schema() -> None:
    attempts: dict[str, int] = defaultdict(int)
    schemas: dict[str, dict] = {}
    lock = Lock()
    responses = {
        "q2pico_p_slot": {"participants": ["adults"]},
        "q2pico_i_slot": {"interventions": ["SSRI"]},
        "q2pico_c_slot": {"comparators": ["placebo"]},
        "q2pico_o_slot": {"outcomes": ["remission"]},
    }

    def fake_llm_caller(**kwargs):
        stage = kwargs["json_schema_name"]
        with lock:
            attempts[stage] += 1
            schemas[stage] = kwargs["json_schema"]
            attempt = attempts[stage]
        if stage == "q2pico_p_slot" and attempt == 1:
            raise RuntimeError("temporary provider failure")
        return responses[stage]

    result = Q2PICOSplitLLMExtractor(
        config=TEST_CONFIG,
        llm_caller=fake_llm_caller,
    ).run(
        question_text="Should adults receive SSRI versus placebo for remission?",
        expand_outcomes=False,
    )

    assert result == result.__class__(
        P=["adults"],
        I=["SSRI"],
        C=["placebo"],
        O=["remission"],
    )
    assert attempts == {
        "q2pico_p_slot": 2,
        "q2pico_i_slot": 1,
        "q2pico_c_slot": 1,
        "q2pico_o_slot": 1,
    }
    assert schemas["q2pico_p_slot"] == {
        "type": "object",
        "properties": {"participants": {"type": "array", "items": {"type": "string"}}},
        "required": ["participants"],
        "additionalProperties": False,
    }
    assert all(kwargs is not None for kwargs in schemas.values())


def test_outcome_expansion_retries_once_without_repeating_successful_slots() -> None:
    attempts: dict[str, int] = defaultdict(int)

    def fake_llm_caller(**kwargs):
        stage = kwargs["json_schema_name"]
        attempts[stage] += 1
        responses = {
            "q2pico_p_slot": {"participants": ["adults"]},
            "q2pico_i_slot": {"interventions": ["SSRI"]},
            "q2pico_c_slot": {"comparators": ["placebo"]},
            "q2pico_o_slot": {"outcomes": ["remission"]},
            "q2pico_expanded_outcomes": {"expanded_outcomes": ["quality of life"]},
        }
        if stage == "q2pico_expanded_outcomes" and attempts[stage] == 1:
            return {"wrong": []}
        return responses[stage]

    result = Q2PICOSplitLLMExtractor(
        config=TEST_CONFIG,
        llm_caller=fake_llm_caller,
    ).run(
        question_text="Should adults receive SSRI versus placebo for remission?",
        expand_outcomes=True,
    )

    assert result.O_expanded == ["quality of life"]
    assert attempts == {
        "q2pico_p_slot": 1,
        "q2pico_i_slot": 1,
        "q2pico_c_slot": 1,
        "q2pico_o_slot": 1,
        "q2pico_expanded_outcomes": 2,
    }


def test_run_fails_after_one_retry_when_a_required_slot_still_fails() -> None:
    calls = 0

    def fake_llm_caller(**kwargs):
        nonlocal calls
        calls += 1
        return {"wrong": []}

    extractor = Q2PICOSplitLLMExtractor(
        config=TEST_CONFIG,
        llm_caller=fake_llm_caller,
        labels=("P",),
    )

    with pytest.raises(Q2PICOInvocationError) as error:
        extractor.run(question_text="Should adults receive treatment?")

    assert error.value.stage == "P"
    assert error.value.attempts == 2
    assert calls == 2


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

    with pytest.raises(Q2PICOInvocationError) as error:
        extractor.run(question_text="Should adults receive treatment?")

    assert error.value.stage == "P"
    assert error.value.attempts == 2


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

    extractor.run(question_text="Should adults receive treatment?", expand_outcomes=False)

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
