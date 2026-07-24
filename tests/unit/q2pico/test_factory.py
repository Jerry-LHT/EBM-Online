from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.q2pico.factory import (
    build_production_q2pico,
)
from ebm_backend.online_pipeline.infrastructure.methods.q2pico.split_slot_llm.method import Method


class StubExtractor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, *, question_text: str, expand_outcomes: bool = True):
        self.calls.append(
            {
                "question_text": question_text,
                "expand_outcomes": expand_outcomes,
            }
        )
        return {
            "question_text": question_text,
            "expand_outcomes": expand_outcomes,
        }


def test_factory_builds_default_q2pico_method() -> None:
    method = build_production_q2pico()

    assert isinstance(method, Method)


def test_method_delegates_to_extractor_with_expand_outcomes_flag() -> None:
    extractor = StubExtractor()
    method = Method(extractor=extractor)

    result = method.run(question_text="Should adults receive treatment?", expand_outcomes=True)

    assert result == {
        "question_text": "Should adults receive treatment?",
        "expand_outcomes": True,
    }
    assert extractor.calls == [
        {
            "question_text": "Should adults receive treatment?",
            "expand_outcomes": True,
        }
    ]


def test_method_expands_outcomes_by_default() -> None:
    extractor = StubExtractor()

    Method(extractor=extractor).run(question_text="Should adults receive treatment?")

    assert extractor.calls == [
        {
            "question_text": "Should adults receive treatment?",
            "expand_outcomes": True,
        }
    ]
