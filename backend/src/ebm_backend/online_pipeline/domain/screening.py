"""Study screening domain objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan


class ScreeningCriterionType(str, Enum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


class ScreeningCriterionJudgmentValue(str, Enum):
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class ScreeningCriteria:
    inclusion_criteria: list[str] = field(default_factory=list)
    exclusion_criteria: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass(frozen=True)
class ScreeningCriterionJudgment:
    criterion_text: str
    criterion_type: ScreeningCriterionType
    judgment: ScreeningCriterionJudgmentValue
    reason: str
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)


@dataclass(frozen=True)
class ScreeningDecision:
    study_id: str
    decision: str
    rationale: str
    exclusion_reason: str | None = None
    criterion_judgments: list[ScreeningCriterionJudgment] = field(default_factory=list)
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)


@dataclass(frozen=True)
class StudyScreeningResult:
    screening_criteria: ScreeningCriteria
    decisions: list[ScreeningDecision] = field(default_factory=list)
    included_studies: list[str] = field(default_factory=list)
