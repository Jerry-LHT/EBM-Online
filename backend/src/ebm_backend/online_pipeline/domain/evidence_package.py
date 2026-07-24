"""Compact product contract for one completed Online EBM evidence chain."""

from __future__ import annotations

from dataclasses import dataclass, field

from ebm_backend.online_pipeline.domain.common import DataType, GradeDomainName
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSubgroup,
    AnalysisTimepoint,
    ContinuousResultData,
    DichotomousResultData,
    GenericInverseVarianceResultData,
    EffectTest,
    HeterogeneitySummary,
    PredictionInterval,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO


@dataclass(frozen=True)
class EvidencePackageStatus:
    """Separate execution health from the completeness of the evidence."""

    execution_status: str
    evidence_status: str
    ready_for_downstream: bool
    reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceProtocol:
    question_text: str
    question_pico: QuestionPICO | None
    inclusion_criteria: list[str] = field(default_factory=list)
    exclusion_criteria: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceSearchSource:
    source_name: str
    total_hits: int
    retrieved_count: int
    citation_count: int = 0
    full_text_available_count: int = 0
    remaining_full_text_count: int = 0
    truncated: bool = False
    warning_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceSearchSummary:
    retrieved_count: int
    screened_count: int
    included_count: int
    excluded_count: int
    downstream_selected_count: int = 0
    downstream_not_selected_count: int = 0
    citation_count: int = 0
    full_text_available_count: int = 0
    remaining_full_text_count: int = 0
    precheck_passed_count: int = 0
    precheck_excluded_count: int = 0
    article_type_passed_count: int = 0
    article_type_uncertain_count: int = 0
    article_type_excluded_count: int = 0
    article_type_technical_failure_count: int = 0
    meta_ready_count: int = 0
    meta_investigation_count: int = 0
    meta_unavailable_no_readable_table_count: int = 0
    meta_selected_count: int = 0
    sources: list[EvidenceSearchSource] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceStudyPopulation:
    description: str
    eligibility_notes: str | None = None


@dataclass(frozen=True)
class EvidenceStudyArm:
    label: str
    description: str


@dataclass(frozen=True)
class EvidenceStudyOutcome:
    outcome_label: str
    measurement: str
    timepoints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceStudyPIO:
    population: EvidenceStudyPopulation
    interventions: list[EvidenceStudyArm] = field(default_factory=list)
    comparators: list[EvidenceStudyArm] = field(default_factory=list)
    outcomes: list[EvidenceStudyOutcome] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceRoBDomain:
    domain: str
    judgement: str
    rationale: str


@dataclass(frozen=True)
class EvidenceRoBOverall:
    judgement: str
    rationale: str
    driving_domains: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceRiskOfBias:
    domains: list[EvidenceRoBDomain] = field(default_factory=list)
    overall: EvidenceRoBOverall | None = None


@dataclass(frozen=True)
class EvidenceStudy:
    study_id: str
    study_pio: EvidenceStudyPIO | None = None
    risk_of_bias: EvidenceRiskOfBias | None = None


@dataclass(frozen=True)
class EvidenceTarget:
    target_id: str
    setting_family_id: str
    population_scope: str
    comparison: AnalysisComparison
    outcome: AnalysisOutcome
    timepoint: AnalysisTimepoint
    subgroup: AnalysisSubgroup
    data_type: DataType
    planned_effect_measure: str | None = None


@dataclass(frozen=True)
class EvidenceStudyEffect:
    study_id: str
    analysis_status: str
    comparison: AnalysisComparison
    outcome: AnalysisOutcome
    result_data: (
        DichotomousResultData
        | ContinuousResultData
        | GenericInverseVarianceResultData
    )
    participant_count: int = 0
    effect_measure: str | None = None
    effect_value: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    weight_fraction: float | None = None
    analysis_scale: str | None = None
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class EvidenceEstimate:
    estimate_id: str
    estimate_type: str
    estimation_status: str
    included_study_ids: list[str]
    study_count: int
    participant_count: int
    data_type: DataType
    effect_measure: str
    analysis_model: str
    statistical_method: str
    ci_level: str
    effect_value: float | str | None = None
    ci_lower: float | str | None = None
    ci_upper: float | str | None = None
    prediction_interval: PredictionInterval | None = None
    heterogeneity: HeterogeneitySummary | None = None
    effect_test: EffectTest | None = None
    effect_direction_convention: str | None = None
    subgroup: AnalysisSubgroup | None = None


@dataclass(frozen=True)
class EvidenceSubgroupDifference:
    test_id: str
    subgroup_factor: str
    test_status: str
    compared_subgroup_estimate_ids: list[str] = field(default_factory=list)
    chi2: float | str | None = None
    df: int | None = None
    p_value: float | str | None = None
    i2_between_subgroups: float | str | None = None


@dataclass(frozen=True)
class EvidenceCompleteness:
    status: str
    expected_study_ids: list[str] = field(default_factory=list)
    contributing_study_ids: list[str] = field(default_factory=list)
    data_unavailable_study_ids: list[str] = field(default_factory=list)
    unresolved_study_ids: list[str] = field(default_factory=list)
    technical_failure_study_ids: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceGradeJudgement:
    domain: GradeDomainName
    downgraded: str
    severity: str
    levels: int | str
    level_evaluable: bool
    rationale: str
    assessment_status: str


@dataclass(frozen=True)
class EvidenceGradeAssessment:
    scope: str = "four_domain_partial_grade"
    assessment_status: str = "not_available"
    overall_certainty: None = None
    domain_judgements: list[EvidenceGradeJudgement] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceUnit:
    evidence_unit_id: str
    target: EvidenceTarget
    completeness: EvidenceCompleteness
    study_effects: list[EvidenceStudyEffect] = field(default_factory=list)
    overall_estimate: EvidenceEstimate | None = None
    subgroup_estimates: list[EvidenceEstimate] = field(default_factory=list)
    subgroup_difference_tests: list[EvidenceSubgroupDifference] = field(default_factory=list)
    grade: EvidenceGradeAssessment = field(default_factory=EvidenceGradeAssessment)


@dataclass(frozen=True)
class EvidencePackage:
    schema_version: str
    run_id: str
    review_id: str
    status: EvidencePackageStatus
    protocol: EvidenceProtocol
    search_summary: EvidenceSearchSummary
    studies: list[EvidenceStudy] = field(default_factory=list)
    evidence_units: list[EvidenceUnit] = field(default_factory=list)
