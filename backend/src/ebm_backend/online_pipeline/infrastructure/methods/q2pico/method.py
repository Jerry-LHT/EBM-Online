"""Q2PICO default method."""

from __future__ import annotations

from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.infrastructure.methods.q2pico.extractor import Q2PICOSplitLLMExtractor


class Method:
    def __init__(self, *, extractor: Q2PICOSplitLLMExtractor | None = None) -> None:
        self.extractor = extractor or Q2PICOSplitLLMExtractor()

    def run(self, *, question_text: str, expand_outcomes: bool = False) -> QuestionPICO:
        return self.extractor.run(question_text=question_text, expand_outcomes=expand_outcomes)


def build_method() -> Method:
    return Method()
