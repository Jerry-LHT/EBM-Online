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


class ScreeningEvidenceScope(str, Enum):
    ABSTRACT = "abstract"
    FULL_TEXT = "full_text"


class SynthesisReadinessStatus(str, Enum):
    """Target-level disposition used before the expensive Meta extraction."""

    CURRENT_META_SUPPORTED = "current_meta_supported"
    NEEDS_META_INVESTIGATION = "needs_meta_investigation"
    METHODOLOGICALLY_ELIGIBLE_UNSUPPORTED = (
        "methodologically_eligible_unsupported"
    )
    NOT_ELIGIBLE = "not_eligible"


class ScreeningReportScope(str, Enum):
    PRIMARY_RESULTS_REPORT = "primary_results_report"
    ALL_STUDY_REPORTS = "all_study_reports"


@dataclass(frozen=True)
class ScreeningPolicy:
    rct_only: bool = True
    pairwise_parallel_individual_only: bool = True
    report_scope: ScreeningReportScope = ScreeningReportScope.PRIMARY_RESULTS_REPORT
    outcome_eligibility_enabled: bool = False
    publication_year_start: int | None = None
    publication_year_end: int | None = None
    allowed_languages: list[str] = field(default_factory=list)
    exclude_retracted: bool = True

    def __post_init__(self) -> None:
        if (
            self.publication_year_start is not None
            and self.publication_year_end is not None
            and self.publication_year_start > self.publication_year_end
        ):
            raise ValueError(
                "publication_year_start must be less than or equal to publication_year_end"
            )


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
    criterion_id: str | None = None
    decision_source: str = "llm"


@dataclass(frozen=True)
class ArticleScreeningResult:
    criterion_judgments: list[ScreeningCriterionJudgment] = field(default_factory=list)
    overall_note: str = ""


@dataclass(frozen=True)
class CoarseScreeningDecision:
    """High-recall title/abstract decision; only explicit mismatches exclude."""

    study_id: str
    decision: str
    reason: str
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)
    evidence_char_count: int = 0
    evidence_source_count: int = 0

    def __post_init__(self) -> None:
        if self.decision not in {"advance", "exclude"}:
            raise ValueError("Coarse screening decision must be advance or exclude")
        if self.evidence_char_count < 0 or self.evidence_source_count < 0:
            raise ValueError("Coarse screening evidence counts must be non-negative")


@dataclass(frozen=True)
class SynthesisTargetReadiness:
    target_id: str
    status: SynthesisReadinessStatus
    reason: str
    data_representation: str | None = None
    experimental_arm: str | None = None
    control_arm: str | None = None
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)


@dataclass(frozen=True)
class ArticleSynthesisScreeningResult:
    """Final article judgement plus target-specific quantitative readiness."""

    article_screening: ArticleScreeningResult
    target_readiness: list[SynthesisTargetReadiness] = field(default_factory=list)
    overall_note: str = ""
    evidence_char_count: int = 0
    evidence_source_count: int = 0

    def __post_init__(self) -> None:
        if self.evidence_char_count < 0 or self.evidence_source_count < 0:
            raise ValueError("Final screening evidence counts must be non-negative")


@dataclass(frozen=True)
class ScreeningDecision:
    study_id: str
    decision: str
    rationale: str
    exclusion_reason: str | None = None
    criterion_judgments: list[ScreeningCriterionJudgment] = field(default_factory=list)
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)
    meta_entry_target_ids: list[str] = field(default_factory=list)
    meta_investigation_target_ids: list[str] = field(default_factory=list)
    methodologically_eligible_unsupported_target_ids: list[str] = field(
        default_factory=list
    )
    evidence_char_count: int = 0
    evidence_source_count: int = 0
    meta_routing_status: str = "not_assessed"
    meta_unavailable_reason: str | None = None


@dataclass(frozen=True)
class StudyScreeningResult:
    screening_criteria: ScreeningCriteria
    decisions: list[ScreeningDecision] = field(default_factory=list)
    included_studies: list[str] = field(default_factory=list)
    included_articles: list[str] = field(default_factory=list)
    excluded_articles: list[str] = field(default_factory=list)
    coarse_decisions: list[CoarseScreeningDecision] = field(default_factory=list)
    synthesis_readiness: dict[str, list[SynthesisTargetReadiness]] = field(
        default_factory=dict
    )
    methodologically_eligible_unsupported_studies: list[str] = field(
        default_factory=list
    )
    meta_ready_studies: list[str] = field(default_factory=list)
    meta_investigation_studies: list[str] = field(default_factory=list)
    meta_unavailable_no_readable_table_studies: list[str] = field(
        default_factory=list
    )


def screening_decision_from_article_result(
    *,
    study_id: str,
    result: ArticleScreeningResult,
) -> ScreeningDecision:
    decision, rationale, exclusion_reason = _aggregate_screening_decision(result=result)
    return ScreeningDecision(
        study_id=study_id,
        decision=decision,
        rationale=rationale,
        exclusion_reason=exclusion_reason,
        criterion_judgments=result.criterion_judgments,
        source_spans=[
            span
            for judgment in result.criterion_judgments
            for span in judgment.source_spans
        ],
    )


def _aggregate_screening_decision(
    *,
    result: ArticleScreeningResult,
) -> tuple[str, str, str | None]:
    for judgment in result.criterion_judgments:
        if (
            judgment.criterion_type == ScreeningCriterionType.EXCLUSION
            and judgment.judgment == ScreeningCriterionJudgmentValue.YES
        ):
            reason = judgment.reason or f"Matched exclusion criterion: {judgment.criterion_text}"
            return "exclude", reason, reason

    for judgment in result.criterion_judgments:
        if (
            judgment.criterion_type == ScreeningCriterionType.INCLUSION
            and judgment.judgment == ScreeningCriterionJudgmentValue.NO
        ):
            reason = judgment.reason or f"Failed inclusion criterion: {judgment.criterion_text}"
            return "exclude", reason, reason

    rationale = result.overall_note.strip() or "No decisive exclusion signal found; conservatively include."
    return "include", rationale, None
