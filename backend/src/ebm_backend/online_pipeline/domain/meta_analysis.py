"""Meta-analysis domain contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

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
    strategy: str | None = None
    target_value: float | None = None
    window_start: float | None = None
    window_end: float | None = None
    unit: str | None = None
    anchor: str | None = None
    basis: str | None = None
    rationale: str = ""


@dataclass(frozen=True)
class AnalysisSubgroup:
    factor: str | None = None
    level: str | None = None
    scope: str | None = None
    membership_relation: str | None = None

    def __post_init__(self) -> None:
        if self.scope not in {None, "study_level", "participant_level"}:
            raise ValueError(f"Unsupported subgroup scope: {self.scope}")
        if self.membership_relation not in {
            None,
            "not_applicable",
            "mutually_exclusive",
            "overlapping",
            "unknown",
        }:
            raise ValueError(
                "Unsupported subgroup membership relation: "
                f"{self.membership_relation}"
            )

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
    population_scope: str
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
class ResultSelectionPolicy:
    """Frozen priorities used to resolve alternative results within a study."""

    acceptable_outcome_measures: list[str] = field(default_factory=list)
    outcome_measure_priority: list[str] = field(default_factory=list)
    analysis_population_priority: list[str] = field(default_factory=list)
    continuous_result_frame_priority: list[str] = field(default_factory=list)
    statistic_type_priority: list[str] = field(default_factory=list)
    source_priority: list[str] = field(default_factory=list)
    tie_policy: str = "unresolved"
    decision_basis: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SynthesisTarget:
    """One frozen, result-blind target from the Meta-analysis local plan."""

    target_id: str
    setting_family_id: str
    population_scope: str
    comparison: AnalysisComparison
    outcome: AnalysisOutcome
    timepoint: AnalysisTimepoint
    subgroup: AnalysisSubgroup
    data_type: DataType
    result_selection_policy: ResultSelectionPolicy = field(
        default_factory=ResultSelectionPolicy
    )
    effect_measure_plan: str | None = None
    analysis_model_plan: str = ""
    notes: str = ""


@dataclass(frozen=True)
class UnsupportedSynthesisTarget:
    """A planned outcome that cannot enter the currently supported pipeline."""

    outcome_label: str
    data_type: str
    reason: str
    reason_code: str = "unsupported_data_type"


@dataclass(frozen=True)
class MetaAnalysisSynthesisPlan:
    """Frozen Meta-analysis planning fragment created before result extraction."""

    plan_id: str
    review_id: str
    version: str
    status: str
    plan_hash: str
    targets: list[SynthesisTarget] = field(default_factory=list)
    unsupported_targets: list[UnsupportedSynthesisTarget] = field(default_factory=list)
    screening_criteria_snapshot: dict[str, object] = field(default_factory=dict)
    rationale: str = ""


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
class GenericInverseVarianceResultData:
    """A directly reported study effect standardized for inverse variance."""

    effect_value: float
    standard_error: float
    effect_measure: str
    analysis_scale: str = "natural"
    participant_count: int | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.effect_value):
            raise ValueError("GIV effect_value must be finite")
        if not math.isfinite(self.standard_error) or self.standard_error <= 0:
            raise ValueError("GIV standard_error must be finite and positive")
        if not self.effect_measure.strip():
            raise ValueError("GIV effect_measure must not be empty")
        if self.analysis_scale not in {"natural", "log"}:
            raise ValueError("GIV analysis_scale must be natural or log")
        if self.participant_count is not None and self.participant_count <= 0:
            raise ValueError("GIV participant_count must be positive when supplied")


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
    reported_statistic_type: str | None = None
    analysis_input_representation: str | None = None
    reported_statistic_kinds: list[str] = field(default_factory=list)
    statistic_type_status: str | None = None
    population_or_subgroup: str | None = None
    analysis_population: str | None = None
    experimental_arm_label: str | None = None
    control_arm_label: str | None = None
    continuous_result_frame: str | None = None
    change_score_definition: str | None = None
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
    result_data: (
        DichotomousResultData
        | ContinuousResultData
        | GenericInverseVarianceResultData
        | None
    ) = None
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
class CandidateResolutionRecord:
    """Auditable disposition of candidates for one study and synthesis target."""

    resolution_id: str
    target_id: str
    study_id: str
    status: str
    operation: str | None = None
    contributing_candidate_ids: list[str] = field(default_factory=list)
    unresolved_candidate_ids: list[str] = field(default_factory=list)
    applied_rule_ids: list[str] = field(default_factory=list)
    excluded_candidate_ids: list[str] = field(default_factory=list)
    reason: str = ""
    dependency_group_id: str | None = None
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)
    candidate_dispositions: list[dict[str, object]] = field(default_factory=list)
    derivation: StudyResultDerivation | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    failure_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ContinuousEffectAlignment:
    result_frame: str
    change_score_definition: str
    scale_direction: str | None = None
    effect_multiplier: int | None = None
    status: str = "uncertain"
    rationale: str = ""


@dataclass(frozen=True)
class MetaAnalysisDataRow:
    """One resolved study row, optionally enriched with single-study statistics.

    The row is created after Candidate Resolution and is the only row shape
    that may enter Subtask 3-5.  Statistical fields remain empty until the
    selected method calculates the row's contribution to one estimate.
    """

    data_row_id: str
    setting_id: str
    setting_family_id: str
    study_id: str
    data_type: DataType
    comparison: StudyResultComparison
    outcome: StudyResultOutcome
    subgroup: AnalysisSubgroup
    result_data: (
        DichotomousResultData
        | ContinuousResultData
        | GenericInverseVarianceResultData
    )
    source_candidate_ids: list[str]
    resolution_id: str
    study_year: str | None = None
    method_id: str | None = None
    estimate_id: str | None = None
    estimate_scope: str | None = None
    resolution_operation: str = "selected"
    derivation: StudyResultDerivation | None = None
    continuous_effect_alignment: ContinuousEffectAlignment | None = None
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)
    analysis_status: str = "pending"
    analysis_exclusion_reason: str | None = None
    participant_count: int = 0
    effect_measure: str | None = None
    analysis_model: str | None = None
    statistical_method: str | None = None
    analysis_effect: float | None = None
    analysis_scale: str | None = None
    effect_value: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    variance: float | None = None
    standard_error: float | None = None
    weight: float | None = None
    weight_fraction: float | None = None
    analysis_notes: str | None = None

    def __post_init__(self) -> None:
        if self.analysis_status not in {"pending", "included", "excluded", "not_analyzed"}:
            raise ValueError(f"Unsupported MetaAnalysisDataRow analysis_status: {self.analysis_status}")
        if self.estimate_scope not in {None, "overall", "subgroup"}:
            raise ValueError("MetaAnalysisDataRow estimate_scope must be overall or subgroup")
        if self.weight_fraction is not None and not 0.0 <= self.weight_fraction <= 1.0:
            raise ValueError("MetaAnalysisDataRow weight_fraction must be between 0 and 1")
        if self.analysis_status == "included":
            required = {
                "effect_value": self.effect_value,
                "analysis_effect": self.analysis_effect,
                "ci_lower": self.ci_lower,
                "ci_upper": self.ci_upper,
                "variance": self.variance,
                "standard_error": self.standard_error,
                "weight": self.weight,
                "weight_fraction": self.weight_fraction,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(
                    "Included MetaAnalysisDataRow is missing calculated fields: "
                    + ", ".join(missing)
                )
        if self.analysis_status in {"excluded", "not_analyzed"} and not self.analysis_exclusion_reason:
            raise ValueError(
                "Excluded or not_analyzed MetaAnalysisDataRow requires analysis_exclusion_reason"
            )


@dataclass(frozen=True)
class SynthesisAnalysisDataset:
    """Only resolved results in this object may enter statistical methods."""

    dataset_id: str
    plan_id: str
    plan_version: str
    target_id: str
    analysis_setting: AnalysisSetting
    data_row_ids: list[str] = field(default_factory=list)
    excluded_study_ids: list[str] = field(default_factory=list)
    excluded_candidate_ids: list[str] = field(default_factory=list)
    unresolved_candidate_ids: list[str] = field(default_factory=list)
    resolution_summary: dict[str, object] = field(default_factory=dict)
    provenance: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisMethodDecision:
    method_id: str
    setting_id: str
    data_type: DataType
    effect_measure: str
    analysis_model: str
    statistical_method: str
    ci_level: str = "95%"
    status: str = "supported"
    method_status: str = "ready"
    analysis_included_study_ids: list[str] = field(default_factory=list)
    analysis_excluded_studies: list[dict[str, object]] = field(default_factory=list)
    heterogeneity_estimator: str | None = None
    interval_method: str = "Wald"
    prediction_interval_enabled: bool = False
    statistical_policy_id: str = "cochrane_revman_v1"
    zero_cell_handling: dict[str, object] | None = None
    smd_method: str | None = None
    rationale: str = ""


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
    i2_method: str | None = None


@dataclass(frozen=True)
class EffectTest:
    statistic_name: str
    statistic_value: float | str
    p_value: float | str
    df: int | None = None


@dataclass(frozen=True)
class OverallEstimate:
    overall_estimate_id: str
    setting_id: str
    setting_family_id: str
    method_id: str
    included_study_ids: list[str]
    study_count: int
    participant_count: int
    data_type: DataType
    effect_measure: str
    analysis_model: str
    statistical_method: str
    ci_level: str
    estimation_status: EstimationStatus
    included_data_row_ids: list[str] = field(default_factory=list)
    interval_method: str = "Wald"
    effect_value: float | str | None = None
    ci_lower: float | str | None = None
    ci_upper: float | str | None = None
    prediction_interval: PredictionInterval | None = None
    heterogeneity: HeterogeneitySummary | None = None
    effect_test: EffectTest | None = None
    effect_direction_convention: str | None = None
    estimation_notes: str | None = None


@dataclass(frozen=True)
class SubgroupEstimate:
    subgroup_estimate_id: str
    setting_id: str
    setting_family_id: str
    method_id: str
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
    included_data_row_ids: list[str] = field(default_factory=list)
    interval_method: str = "Wald"
    effect_value: float | str | None = None
    ci_lower: float | str | None = None
    ci_upper: float | str | None = None
    heterogeneity: HeterogeneitySummary | None = None
    effect_direction_convention: str | None = None
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
    comparison: AnalysisComparison | None = None
    outcome: AnalysisOutcome | None = None
    timepoint: AnalysisTimepoint | None = None
    data_type: DataType | None = None
    effect_measure: str = ""
    test_method: str | None = None
    subgroup_scope: str | None = None
    level_a: str | None = None
    level_b: str | None = None
    paired_study_ids: list[str] = field(default_factory=list)
    paired_study_count: int = 0
    interaction_effect_value: float | str | None = None
    interaction_ci_lower: float | str | None = None
    interaction_ci_upper: float | str | None = None
    interaction_scale: str | None = None
    interaction_heterogeneity: HeterogeneitySummary | None = None
    notes: str | None = None


@dataclass(frozen=True)
class MetaAnalysisResultPackage:
    review_id: str
    synthesis_plan: MetaAnalysisSynthesisPlan | None = None
    candidate_resolution_records: list[CandidateResolutionRecord] = field(default_factory=list)
    synthesis_analysis_datasets: list[SynthesisAnalysisDataset] = field(default_factory=list)
    analysis_settings: list[AnalysisSetting] = field(default_factory=list)
    study_result_rows: list[StudyResultRow] = field(default_factory=list)
    meta_analysis_data_rows: list[MetaAnalysisDataRow] = field(default_factory=list)
    analysis_methods: list[AnalysisMethodDecision] = field(default_factory=list)
    subgroup_estimates: list[SubgroupEstimate] = field(default_factory=list)
    overall_estimates: list[OverallEstimate] = field(default_factory=list)
    subgroup_difference_tests: list[SubgroupDifferenceTest] = field(default_factory=list)
