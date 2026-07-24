"""Study-level PIO characteristic contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan


MAX_STUDY_PIO_ITEMS_PER_RUN = 500


@dataclass(frozen=True)
class StudyPopulationCharacteristics:
    description: str
    eligibility_notes: str | None = None
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)


@dataclass(frozen=True)
class StudyInterventionCharacteristics:
    label: str
    description: str
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)


@dataclass(frozen=True)
class StudyComparatorCharacteristics:
    label: str
    description: str
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)


@dataclass(frozen=True)
class StudyOutcomeCharacteristics:
    outcome_label: str
    measurement: str
    timepoints: list[str] = field(default_factory=list)
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)


@dataclass(frozen=True)
class StudyPIOCharacteristics:
    study_id: str
    population: StudyPopulationCharacteristics
    interventions: list[StudyInterventionCharacteristics] = field(default_factory=list)
    comparators: list[StudyComparatorCharacteristics] = field(default_factory=list)
    outcomes: list[StudyOutcomeCharacteristics] = field(default_factory=list)
    notes: str = ""
