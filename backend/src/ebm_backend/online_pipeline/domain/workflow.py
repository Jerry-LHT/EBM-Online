"""Domain records for one observable Online EBM workflow run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ebm_backend.online_pipeline.domain.article import SearchRetrievalWarning
from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleQualificationResult,
)
from ebm_backend.online_pipeline.domain.grade import GradeResult
from ebm_backend.online_pipeline.domain.meta_analysis import MetaAnalysisResultPackage
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.risk_of_bias import RiskOfBiasAssessment
from ebm_backend.online_pipeline.domain.screening import StudyScreeningResult
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics


@dataclass(frozen=True)
class WorkflowStageRecord:
    stage_name: str
    status: str
    output: dict[str, Any] | list[Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class WorkflowSearchSourceSummary:
    source_name: str
    search_query: str
    query_used: str
    total_hits: int
    returned_count: int
    retrieved_record_count: int = 0
    full_text_available_count: int = 0
    remaining_full_text_count: int = 0
    truncated: bool = False
    warnings: list[SearchRetrievalWarning] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowSearchRetrievalSummary:
    returned_count: int
    retrieved_record_count: int = 0
    full_text_available_count: int = 0
    remaining_full_text_count: int = 0
    truncated: bool = False
    retrieved_study_ids: list[str] = field(default_factory=list)
    source_results: list[WorkflowSearchSourceSummary] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowStudySelection:
    """Auditable boundary between screening eligibility and downstream analysis."""

    eligible_study_ids: list[str] = field(default_factory=list)
    selected_study_ids: list[str] = field(default_factory=list)
    not_selected_study_ids: list[str] = field(default_factory=list)
    max_downstream_studies: int | None = None
    selection_policy: str = "screening_order"
    truncated: bool = False
    meta_analysis_study_ids: list[str] = field(default_factory=list)
    meta_unavailable_study_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowArticlePrecheckDecision:
    study_id: str
    decision: str
    reason: str


@dataclass(frozen=True)
class WorkflowArticlePrecheckResult:
    decisions: list[WorkflowArticlePrecheckDecision] = field(default_factory=list)
    passed_studies: list[str] = field(default_factory=list)
    excluded_studies: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OnlineEBMWorkflowResult:
    review_id: str
    question_text: str
    status: str
    run_id: str = ""
    persistence_status: str = "disabled"
    persistence_error_code: str | None = None
    stages: list[WorkflowStageRecord] = field(default_factory=list)
    question_pico: QuestionPICO | None = None
    search_retrieval: WorkflowSearchRetrievalSummary | None = None
    article_precheck: WorkflowArticlePrecheckResult | None = None
    article_qualification: ArticleQualificationResult | None = None
    study_screening: StudyScreeningResult | None = None
    study_selection: WorkflowStudySelection | None = None
    study_pio: list[StudyPIOCharacteristics] = field(default_factory=list)
    risk_of_bias: list[RiskOfBiasAssessment] = field(default_factory=list)
    meta_analysis: MetaAnalysisResultPackage | None = None
    grade: GradeResult | None = None
    grade_status: str = "not_run"
