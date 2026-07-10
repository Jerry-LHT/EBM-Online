"""Shared domain value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ModuleStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DataType(str, Enum):
    DICHOTOMOUS = "Dichotomous"
    CONTINUOUS = "Continuous"


class EstimationStatus(str, Enum):
    COMPUTED = "computed"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class GradeDomainName(str, Enum):
    RISK_OF_BIAS = "risk_of_bias"
    INCONSISTENCY = "inconsistency"
    INDIRECTNESS = "indirectness"
    IMPRECISION = "imprecision"


@dataclass(frozen=True)
class WorkflowWarning:
    code: str
    message: str
    module_name: str | None = None


@dataclass(frozen=True)
class EvidenceSourceSpan:
    source_id: str
    text: str
    section: str | None = None
    page: str | None = None
    table_id: str | None = None


@dataclass(frozen=True)
class SearchFilters:
    study_design: str | None = "RCT"
    full_text_required: bool | None = None
    language: list[str] = field(default_factory=list)
    publication_year_range: str | None = None


@dataclass(frozen=True)
class WorkflowConstraints:
    study_design: str = "RCT"
    evidence_scope: str | None = "online_question_guided_rct_evidence"
    publication_year_range: str | None = None
    supported_data_types: list[DataType] = field(
        default_factory=lambda: [DataType.DICHOTOMOUS, DataType.CONTINUOUS]
    )
    supports_one_main_rct_one_study: bool = True
    supports_pairwise_rct_only: bool = True
