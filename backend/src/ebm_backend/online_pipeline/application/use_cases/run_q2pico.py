"""Use case for extracting question-level PICO."""

from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.application.ports import Q2PICOPort
from ebm_backend.online_pipeline.domain.question import QuestionPICO


@dataclass(frozen=True)
class RunQ2PICO:
    method: Q2PICOPort

    def execute(self, *, question_text: str, expand_outcomes: bool = False) -> QuestionPICO:
        return self.method.run(question_text=question_text, expand_outcomes=expand_outcomes)
