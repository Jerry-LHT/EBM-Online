"""Meta-analysis domain contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

from ebm_backend.online_pipeline.domain.common import DataType, EstimationStatus, EvidenceSourceSpan


@dataclass(frozen=True)
class AnalysisComparison:
    experimental: str
    comparator: str


@dataclass(frozen=True)
class AnalysisOutcome:
    label: str
    measure: str | None = None


@dataclass(frozen=True)
class AnalysisTimepoint:
    label: str | None = None


@dataclass(frozen=True)
class AnalysisSubgroup:
    factor: str | None = None
    level: str | None = None

    @property
    def is_overall(self) -> bool:
        return not self.factor and not self.level


@dataclass(frozen=True)
class AnalysisSettingExtractionTarget:
    target_id: str
    extraction_hint: str | None = None


@dataclass(frozen=True)
class AnalysisSettingStudyCandidate:
    study_id: str
    article_id: str | None = None
    extraction_task_id: str | None = None
    extraction_targets: list[AnalysisSettingExtractionTarget] = field(default_factory=list)


@dataclass(frozen=True)
class AnalysisSetting:
    setting_id: str
    setting_family_id: str
    candidate_id: str
    comparison: AnalysisComparison
    outcome: AnalysisOutcome
    timepoint: AnalysisTimepoint
    subgroup: AnalysisSubgroup
    data_type: DataType
    eligible_study_ids: list[str] = field(default_factory=list)
    eligible_study_candidates: list[AnalysisSettingStudyCandidate] = field(default_factory=list)
    excluded_study_ids: list[str] = field(default_factory=list)
    source_context: dict[str, object] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class StudyResultComparison:
    experimental_arm: str
    control_arm: str


@dataclass(frozen=True)
class StudyResultOutcome:
    label: str
    timepoint: str | None = None


@dataclass(frozen=True)
class DichotomousResultData:
    experimental_events: int
    experimental_total: int
    control_events: int
    control_total: int


@dataclass(frozen=True)
class ContinuousResultData:
    experimental_mean: float
    experimental_sd: float
    experimental_total: int
    control_mean: float
    control_sd: float
    control_total: int


@dataclass(frozen=True)
class StudyResultTarget:
    target_id: str
    setting_id: str
    study_id: str
    article_id: str | None = None
    extraction_hint: str | None = None
    comparison: StudyResultComparison | None = None
    outcome: StudyResultOutcome | None = None
    subgroup: AnalysisSubgroup | None = None
    data_type: DataType | None = None
    notes: str = ""


@dataclass(frozen=True)
class StudyResultSetting:
    row_label: str | None = None
    outcome_label: str | None = None
    outcome_measure: str | None = None
    timepoint: str | None = None
    statistic_type: str | None = None
    population_or_subgroup: str | None = None
    experimental_arm_label: str | None = None
    control_arm_label: str | None = None
    table_local_notes: str | None = None


@dataclass(frozen=True)
class StudyResultDerivation:
    method: str = "direct"
    computed_fields: list[str] = field(default_factory=list)
    input_values: dict[str, object] = field(default_factory=dict)
    formula: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class CandidateStudyResult:
    candidate_id: str
    match_status: str
    study_result_setting: StudyResultSetting
    data_type: DataType
    result_data: DichotomousResultData | ContinuousResultData | None = None
    include_in_estimate: bool | None = None
    analysis_disposition: str | None = None
    resolution_reason: str | None = None
    derivation: StudyResultDerivation | None = None
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)
    confidence: str | None = None
    study_local_note: str | None = None
    study_local_result: dict[str, object] = field(default_factory=dict)
    setting_alignment: dict[str, object] = field(default_factory=dict)
    numeric_extraction: dict[str, object] = field(default_factory=dict)
    note: str | None = None


@dataclass(frozen=True)
class StudyResultRow:
    row_id: str
    setting_id: str
    study_id: str
    extraction_status: str
    data_type: DataType
    comparison: StudyResultComparison
    outcome: StudyResultOutcome
    subgroup: AnalysisSubgroup
    extraction_task_id: str | None = None
    study_year: str | None = None
    missing_reason: str | None = None
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)
    result_items: list[CandidateStudyResult] = field(default_factory=list)
    candidate_results: list[CandidateStudyResult] = field(default_factory=list)
    study_result_note: str | None = None
    extraction_status_reason: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class PredictionInterval:
    lower: float | str
    upper: float | str


@dataclass(frozen=True)
class HeterogeneitySummary:
    tau2: float | str | None = None
    chi2: float | str | None = None
    df: int | None = None
    p_value: float | str | None = None
    i2: float | str | None = None


@dataclass(frozen=True)
class OverallEstimate:
    overall_estimate_id: str
    setting_id: str
    setting_family_id: str
    method_id: str
    candidate_id: str
    included_study_ids: list[str]
    study_count: int
    participant_count: int
    data_type: DataType
    effect_measure: str
    analysis_model: str
    statistical_method: str
    ci_level: str
    estimation_status: EstimationStatus
    effect_value: float | str | None = None
    ci_lower: float | str | None = None
    ci_upper: float | str | None = None
    prediction_interval: PredictionInterval | None = None
    heterogeneity: HeterogeneitySummary | None = None
    estimation_notes: str | None = None


@dataclass(frozen=True)
class SubgroupEstimate:
    subgroup_estimate_id: str
    setting_id: str
    setting_family_id: str
    method_id: str
    candidate_id: str
    subgroup: AnalysisSubgroup
    included_study_ids: list[str]
    study_count: int
    participant_count: int
    data_type: DataType
    effect_measure: str
    analysis_model: str
    statistical_method: str
    ci_level: str
    estimation_status: EstimationStatus
    effect_value: float | str | None = None
    ci_lower: float | str | None = None
    ci_upper: float | str | None = None
    heterogeneity: HeterogeneitySummary | None = None
    estimation_notes: str | None = None


@dataclass(frozen=True)
class SubgroupDifferenceTest:
    test_id: str
    setting_family_id: str
    subgroup_factor: str
    compared_subgroup_estimate_ids: list[str] = field(default_factory=list)
    test_status: str = "not_applicable"
    chi2: float | str | None = None
    df: int | None = None
    p_value: float | str | None = None
    i2_between_subgroups: float | str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class MetaAnalysisResultPackage:
    review_id: str
    analysis_settings: list[AnalysisSetting] = field(default_factory=list)
    study_result_rows: list[StudyResultRow] = field(default_factory=list)
    subgroup_estimates: list[SubgroupEstimate] = field(default_factory=list)
    overall_estimates: list[OverallEstimate] = field(default_factory=list)
    subgroup_difference_tests: list[SubgroupDifferenceTest] = field(default_factory=list)
