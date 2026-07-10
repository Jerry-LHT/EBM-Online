from __future__ import annotations

import os
from pathlib import Path

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.q2pico.extractor import Q2PICOSplitLLMExtractor


REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_LIVE_LLM_TESTS = os.getenv("RUN_LIVE_LLM_TESTS") == "1"
LIVE_CASE = {
    "instance_id": "2020 EAN Dementia::4a",
    "question_text": (
        "Should patients with dementia and agitation/aggressive behaviour "
        "be treated with atypical anti-psychotics compared to no pharmacological treatment?"
    ),
}


@pytest.mark.skipif(not RUN_LIVE_LLM_TESTS, reason="Set RUN_LIVE_LLM_TESTS=1 to run live LLM tests.")
def test_q2pico_live_llm_on_benchmark_case(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CONFIG_PATH", str(REPO_ROOT / "llm.local.json"))

    extractor = Q2PICOSplitLLMExtractor()
    result = extractor.run(question_text=LIVE_CASE["question_text"])

    assert result.P
    assert result.I
    assert result.C
    assert isinstance(result.O, list)
    assert any("dementia" in value.casefold() for value in result.P)
    assert any(
        "agitation" in value.casefold() or "aggressive" in value.casefold()
        for value in result.P
    )
    assert any(
        "antipsych" in value.casefold() or "anti-psych" in value.casefold() or "atypical" in value.casefold()
        for value in result.I
    )
    assert any(
        "pharmacological" in value.casefold() or "no treatment" in value.casefold() or "usual care" in value.casefold()
        for value in result.C
    )
    assert result.O_expanded == []


@pytest.mark.skipif(not RUN_LIVE_LLM_TESTS, reason="Set RUN_LIVE_LLM_TESTS=1 to run live LLM tests.")
def test_q2pico_live_llm_can_expand_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CONFIG_PATH", str(REPO_ROOT / "llm.local.json"))

    extractor = Q2PICOSplitLLMExtractor()
    result = extractor.run(question_text=LIVE_CASE["question_text"], expand_outcomes=True)

    assert isinstance(result.O, list)
    assert result.O_expanded
    assert any("agitation" in value.casefold() or "aggressive" in value.casefold() for value in result.O_expanded)
    assert any(
        "adverse" in value.casefold()
        or "mortality" in value.casefold()
        or "cognitive" in value.casefold()
        or "quality of life" in value.casefold()
        for value in result.O_expanded
    )
