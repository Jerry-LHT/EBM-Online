from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.q2pico.factory import (
    build_q2pico_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.q2pico.method import Method


class StubExtractor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, *, question_text: str, expand_outcomes: bool = False):
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
    method = build_q2pico_method(method_name="default")

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
