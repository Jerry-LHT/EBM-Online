"""Question-level domain objects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ClinicalQuestionInput:
    question_text: str


@dataclass(frozen=True)
class QuestionPICO:
    P: list[str] = field(default_factory=list)
    I: list[str] = field(default_factory=list)
    C: list[str] = field(default_factory=list)
    O: list[str] = field(default_factory=list)
    O_expanded: list[str] = field(default_factory=list)
