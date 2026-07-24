"""Application port for question-to-PICO extraction."""

from __future__ import annotations

from typing import Protocol

from ebm_backend.online_pipeline.domain.question import QuestionPICO


class Q2PICOPort(Protocol):
    def run(self, *, question_text: str, expand_outcomes: bool = True) -> QuestionPICO:
        ...
