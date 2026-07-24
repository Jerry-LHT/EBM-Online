"""Content-based article-type qualification before review-specific screening."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan


class ArticleQualificationDecision(str, Enum):
    """High-recall routing decision independent of one review question."""

    PASS = "pass"
    EXCLUDE = "exclude"
    ADVANCE_UNCERTAIN = "advance_uncertain"
    TECHNICAL_FAILURE = "technical_failure"


class ArticleReportRole(str, Enum):
    PRIMARY_RESULTS = "primary_results"
    PROTOCOL = "protocol"
    SECONDARY_REPORT = "secondary_report"
    REVIEW_OR_META_ANALYSIS = "review_or_meta_analysis"
    OTHER = "other"
    UNCLEAR = "unclear"


class RandomizationStatus(str, Enum):
    RANDOMIZED = "randomized"
    NOT_RANDOMIZED = "not_randomized"
    UNCLEAR = "unclear"


class TrialDesign(str, Enum):
    INDIVIDUAL_PARALLEL = "individual_parallel"
    CLUSTER = "cluster"
    CROSSOVER = "crossover"
    OTHER = "other"
    UNCLEAR = "unclear"


class ResultsReportStatus(str, Enum):
    RESULTS_REPORTED = "results_reported"
    NO_PRIMARY_RESULTS = "no_primary_results"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class ArticleEvidenceCoverage:
    """Coverage facts for auditing what the classifier was allowed to read."""

    complete_section_ids: list[str] = field(default_factory=list)
    partial_section_ids: list[str] = field(default_factory=list)
    complete_table_ids: list[str] = field(default_factory=list)
    partial_table_ids: list[str] = field(default_factory=list)
    unread_table_ids: list[str] = field(default_factory=list)
    input_token_estimate: int = 0
    input_token_budget: int = 0


@dataclass(frozen=True)
class ArticleQualificationAssessment:
    study_id: str
    decision: ArticleQualificationDecision
    report_role: ArticleReportRole
    randomization_status: RandomizationStatus
    trial_design: TrialDesign
    results_report_status: ResultsReportStatus
    has_quantitative_results: bool | None
    reason: str
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)
    evidence_coverage: ArticleEvidenceCoverage = field(
        default_factory=ArticleEvidenceCoverage
    )
    failure_code: str | None = None


@dataclass(frozen=True)
class ArticleQualificationResult:
    assessments: list[ArticleQualificationAssessment] = field(default_factory=list)
    passed_studies: list[str] = field(default_factory=list)
    uncertain_studies: list[str] = field(default_factory=list)
    excluded_studies: list[str] = field(default_factory=list)
    technical_failure_studies: list[str] = field(default_factory=list)

