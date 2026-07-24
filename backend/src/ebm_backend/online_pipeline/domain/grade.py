"""GRADE assessment domain contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

from ebm_backend.online_pipeline.domain.common import (
    DataType,
    EvidenceSourceSpan,
    GradeDomainName,
)
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    ContinuousResultData,
    DichotomousResultData,
    GenericInverseVarianceResultData,
    HeterogeneitySummary,
    AnalysisOutcome,
    AnalysisSubgroup,
    AnalysisTimepoint,
    PredictionInterval,
    StudyResultComparison,
    StudyResultOutcome,
    SubgroupDifferenceTest,
    SubgroupEstimate,
)
from ebm_backend.online_pipeline.domain.study_characteristics import (
    StudyComparatorCharacteristics,
    StudyInterventionCharacteristics,
    StudyOutcomeCharacteristics,
    StudyPIOCharacteristics,
    StudyPopulationCharacteristics,
)
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria


GRADE_ROB_ASSESSMENT_PROFILES = {
    "rob1_core_5",
    "rob1_full_7",
    "rob1_custom",
}
GRADE_ROB_CONTRIBUTION_BASES = {"study_count", "meta_analysis_weight"}
GRADE_ROB_WEIGHT_STATUSES = {"complete", "partial", "unavailable"}
GRADE_DOMAIN_SEVERITIES = {
    "not_serious",
    "serious",
    "very_serious",
    "unclear",
}
GRADE_DOMAIN_ASSESSMENT_STATUSES = {
    "assessed",
    "single_study_not_estimable",
    "insufficient_evidence",
}


@dataclass(frozen=True)
class GRADERiskOfBiasSetting:
    setting_id: str
    population: str
    comparison: AnalysisComparison
    outcome: AnalysisOutcome
    timepoint: AnalysisTimepoint
    subgroup: AnalysisSubgroup

    def __post_init__(self) -> None:
        if not self.setting_id.strip():
            raise ValueError("GRADE risk-of-bias setting_id must not be empty")


@dataclass(frozen=True)
class GRADERiskOfBiasDomainEvidence:
    domain: str
    judgement: str
    rationale: str

    def __post_init__(self) -> None:
        if not self.domain.strip():
            raise ValueError("GRADE risk-of-bias domain must not be empty")
        if self.judgement not in {"low_risk", "unclear_risk", "high_risk"}:
            raise ValueError("Unsupported GRADE risk-of-bias domain judgement")
        if not self.rationale.strip():
            raise ValueError("GRADE risk-of-bias domain rationale must not be empty")


@dataclass(frozen=True)
class GRADERiskOfBiasStudyEvidence:
    study_id: str
    contribution_weight: float | None
    rob_available: bool
    assessment_scope: str
    assessment_profile: str
    assessed_domains: list[str]
    unassessed_domains: list[str]
    domains: list[GRADERiskOfBiasDomainEvidence]

    def __post_init__(self) -> None:
        if not self.study_id.strip():
            raise ValueError("GRADE risk-of-bias study_id must not be empty")
        if self.assessment_profile not in GRADE_ROB_ASSESSMENT_PROFILES:
            raise ValueError(
                "GRADE risk-of-bias assessment_profile must be one of: "
                + ", ".join(sorted(GRADE_ROB_ASSESSMENT_PROFILES))
            )
        if len(set(self.assessed_domains)) != len(self.assessed_domains):
            raise ValueError("GRADE risk-of-bias assessed_domains must be unique")
        if len(set(self.unassessed_domains)) != len(self.unassessed_domains):
            raise ValueError("GRADE risk-of-bias unassessed_domains must be unique")
        if set(self.assessed_domains) & set(self.unassessed_domains):
            raise ValueError(
                "GRADE risk-of-bias assessed_domains and unassessed_domains must not overlap"
            )
        domain_ids = [item.domain for item in self.domains]
        if len(set(domain_ids)) != len(domain_ids):
            raise ValueError("GRADE risk-of-bias domains must be unique per study")
        if set(domain_ids) != set(self.assessed_domains):
            raise ValueError(
                "GRADE risk-of-bias domains must match assessed_domains"
            )
        if self.rob_available and not self.domains:
            raise ValueError(
                "GRADE risk-of-bias available study evidence must include domains"
            )
        if not self.rob_available and (self.domains or self.assessed_domains):
            raise ValueError(
                "GRADE risk-of-bias unavailable study evidence must not include assessed domains"
            )
        if self.contribution_weight is not None and not (
            0.0 <= self.contribution_weight <= 1.0
        ):
            raise ValueError(
                "GRADE risk-of-bias contribution_weight must be between 0 and 1"
            )


@dataclass(frozen=True)
class GRADERiskOfBiasCoverage:
    expected_study_ids: list[str]
    assessed_study_ids: list[str]
    missing_rob_study_ids: list[str]
    weight_status: str

    def __post_init__(self) -> None:
        if self.weight_status not in GRADE_ROB_WEIGHT_STATUSES:
            raise ValueError(
                "GRADE risk-of-bias weight_status must be one of: "
                + ", ".join(sorted(GRADE_ROB_WEIGHT_STATUSES))
            )
        for name, values in (
            ("expected_study_ids", self.expected_study_ids),
            ("assessed_study_ids", self.assessed_study_ids),
            ("missing_rob_study_ids", self.missing_rob_study_ids),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"GRADE risk-of-bias {name} must be unique")
        expected = set(self.expected_study_ids)
        assessed = set(self.assessed_study_ids)
        missing = set(self.missing_rob_study_ids)
        if assessed | missing != expected or assessed & missing:
            raise ValueError(
                "GRADE risk-of-bias coverage must partition expected studies into assessed and missing"
            )


@dataclass(frozen=True)
class GRADERiskOfBiasDomainSummary:
    domain: str
    assessed_study_count: int
    low_risk_count: int
    unclear_risk_count: int
    high_risk_count: int
    low_risk_weight: float | None = None
    unclear_risk_weight: float | None = None
    high_risk_weight: float | None = None
    high_risk_study_ids: list[str] = field(default_factory=list)
    unclear_risk_study_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GRADERiskOfBiasSummary:
    profile_counts: dict[str, int] = field(default_factory=dict)
    domain_summaries: list[GRADERiskOfBiasDomainSummary] = field(
        default_factory=list
    )


@dataclass(frozen=True)
class GRADERiskOfBiasInput:
    setting: GRADERiskOfBiasSetting
    contribution_basis: str
    contributing_studies: list[GRADERiskOfBiasStudyEvidence]
    coverage: GRADERiskOfBiasCoverage
    summary: GRADERiskOfBiasSummary

    def __post_init__(self) -> None:
        if self.contribution_basis not in GRADE_ROB_CONTRIBUTION_BASES:
            raise ValueError(
                "GRADE risk-of-bias contribution_basis must be one of: "
                + ", ".join(sorted(GRADE_ROB_CONTRIBUTION_BASES))
            )
        study_ids = [item.study_id for item in self.contributing_studies]
        if len(set(study_ids)) != len(study_ids):
            raise ValueError(
                "GRADE risk-of-bias contributing study IDs must be unique"
            )
        if study_ids != self.coverage.expected_study_ids:
            raise ValueError(
                "GRADE risk-of-bias contributing studies must follow expected_study_ids order"
            )
        available_study_ids = [
            item.study_id for item in self.contributing_studies if item.rob_available
        ]
        if available_study_ids != self.coverage.assessed_study_ids:
            raise ValueError(
                "GRADE risk-of-bias available studies must follow assessed_study_ids order"
            )
        weights = [item.contribution_weight for item in self.contributing_studies]
        if self.contribution_basis == "meta_analysis_weight":
            if self.coverage.weight_status != "complete":
                raise ValueError(
                    "meta_analysis_weight contribution requires complete weight coverage"
                )
            if not weights or any(value is None for value in weights):
                raise ValueError(
                    "meta_analysis_weight contribution requires every contributing study weight"
                )
            weight_sum = sum(value for value in weights if value is not None)
            if abs(weight_sum - 1.0) > 0.01:
                raise ValueError(
                    "GRADE risk-of-bias contribution weights must sum to approximately 1"
                )
        elif any(value is not None for value in weights):
            raise ValueError(
                "study_count contribution must not expose partial or inferred weights"
            )


@dataclass(frozen=True)
class GRADEInconsistencySetting:
    setting_id: str
    setting_family_id: str
    population: str
    comparison: AnalysisComparison
    outcome: AnalysisOutcome
    timepoint: AnalysisTimepoint
    subgroup: AnalysisSubgroup
    data_type: DataType
    effect_measure: str

    def __post_init__(self) -> None:
        if not self.setting_id.strip():
            raise ValueError("GRADE inconsistency setting_id must not be empty")
        if not self.setting_family_id.strip():
            raise ValueError(
                "GRADE inconsistency setting_family_id must not be empty"
            )
        if not self.effect_measure.strip():
            raise ValueError(
                "GRADE inconsistency effect_measure must not be empty"
            )


@dataclass(frozen=True)
class GRADEInconsistencyEstimate:
    estimate_type: str
    estimate_id: str
    estimation_status: str
    included_study_ids: list[str]
    included_data_row_ids: list[str]
    study_count: int
    participant_count: int
    effect_measure: str
    analysis_model: str
    pooled_effect: float | None
    ci_lower: float | None
    ci_upper: float | None
    heterogeneity: HeterogeneitySummary | None
    prediction_interval: PredictionInterval | None


@dataclass(frozen=True)
class GRADEInconsistencyStudyEffect:
    data_row_id: str
    study_id: str
    effect_value: float
    ci_lower: float | None
    ci_upper: float | None
    weight_fraction: float | None
    analysis_scale: str | None
    effect_measure: str
    comparison: StudyResultComparison
    outcome: StudyResultOutcome
    subgroup: AnalysisSubgroup


@dataclass(frozen=True)
class GRADEInconsistencyCoverage:
    expected_data_row_ids: list[str]
    available_data_row_ids: list[str]
    missing_data_row_ids: list[str]
    missing_ci_data_row_ids: list[str] = field(default_factory=list)
    missing_weight_data_row_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        expected = set(self.expected_data_row_ids)
        available = set(self.available_data_row_ids)
        missing = set(self.missing_data_row_ids)
        if len(expected) != len(self.expected_data_row_ids):
            raise ValueError(
                "GRADE inconsistency expected_data_row_ids must be unique"
            )
        for name, values in (
            ("available_data_row_ids", self.available_data_row_ids),
            ("missing_data_row_ids", self.missing_data_row_ids),
            ("missing_ci_data_row_ids", self.missing_ci_data_row_ids),
            ("missing_weight_data_row_ids", self.missing_weight_data_row_ids),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"GRADE inconsistency {name} must be unique")
        if available | missing != expected or available & missing:
            raise ValueError(
                "GRADE inconsistency coverage must partition expected DataRows"
            )
        expected_available_order = [
            item
            for item in self.expected_data_row_ids
            if item in available
        ]
        if self.available_data_row_ids != expected_available_order:
            raise ValueError(
                "GRADE inconsistency available DataRows must follow expected order"
            )
        if not set(self.missing_ci_data_row_ids).issubset(available):
            raise ValueError(
                "GRADE inconsistency missing CI IDs must refer to available DataRows"
            )
        if not set(self.missing_weight_data_row_ids).issubset(available):
            raise ValueError(
                "GRADE inconsistency missing weight IDs must refer to available DataRows"
            )


@dataclass(frozen=True)
class GRADEInconsistencyInput:
    setting: GRADEInconsistencySetting
    estimate: GRADEInconsistencyEstimate
    study_effects: list[GRADEInconsistencyStudyEffect]
    subgroup_estimates: list[SubgroupEstimate]
    subgroup_difference_tests: list[SubgroupDifferenceTest]
    study_characteristics: list[StudyPIOCharacteristics]
    coverage: GRADEInconsistencyCoverage

    def __post_init__(self) -> None:
        if self.estimate.included_data_row_ids != self.coverage.expected_data_row_ids:
            raise ValueError(
                "GRADE inconsistency estimate DataRows must match coverage order"
            )
        effect_ids = [item.data_row_id for item in self.study_effects]
        if effect_ids != self.coverage.available_data_row_ids:
            raise ValueError(
                "GRADE inconsistency study effects must match available DataRow order"
            )
        if len(set(effect_ids)) != len(effect_ids):
            raise ValueError("GRADE inconsistency study effect IDs must be unique")


GRADE_INDIRECTNESS_MAPPING_STATUSES = {
    "matched",
    "ambiguous",
    "not_found",
    "target_missing",
    "study_pio_missing",
}
GRADE_INDIRECTNESS_DIRECT_COMPARISON_STATUSES = {
    "pairwise_direct",
    "indirect_or_network",
    "unclear",
}


@dataclass(frozen=True)
class GRADEIndirectnessSetting:
    setting_id: str
    setting_family_id: str
    population: str
    comparison: AnalysisComparison
    outcome: AnalysisOutcome
    timepoint: AnalysisTimepoint
    subgroup: AnalysisSubgroup
    data_type: DataType
    effect_measure: str

    def __post_init__(self) -> None:
        if not self.setting_id.strip():
            raise ValueError("GRADE indirectness setting_id must not be empty")
        if not self.setting_family_id.strip():
            raise ValueError(
                "GRADE indirectness setting_family_id must not be empty"
            )
        if not self.effect_measure.strip():
            raise ValueError(
                "GRADE indirectness effect_measure must not be empty"
            )


@dataclass(frozen=True)
class GRADEIndirectnessEstimate:
    estimate_type: str
    estimate_id: str
    estimation_status: str
    included_study_ids: list[str]
    included_data_row_ids: list[str]
    study_count: int
    participant_count: int
    effect_measure: str
    analysis_model: str
    pooled_effect: float | None
    ci_lower: float | None
    ci_upper: float | None


@dataclass(frozen=True)
class GRADEIndirectnessMappingStatus:
    intervention: str
    comparator: str
    outcome: str
    timepoint: str

    def __post_init__(self) -> None:
        for name, value in (
            ("intervention", self.intervention),
            ("comparator", self.comparator),
            ("outcome", self.outcome),
            ("timepoint", self.timepoint),
        ):
            if value not in GRADE_INDIRECTNESS_MAPPING_STATUSES:
                raise ValueError(
                    f"Unsupported GRADE indirectness {name} mapping status: {value}"
                )


@dataclass(frozen=True)
class GRADEIndirectnessStudyEvidence:
    data_row_id: str
    study_id: str
    comparison: StudyResultComparison
    outcome: StudyResultOutcome
    subgroup: AnalysisSubgroup
    population: StudyPopulationCharacteristics | None
    intervention: StudyInterventionCharacteristics | None
    comparator: StudyComparatorCharacteristics | None
    study_outcome: StudyOutcomeCharacteristics | None
    mapping_status: GRADEIndirectnessMappingStatus
    candidate_interventions: list[StudyInterventionCharacteristics]
    candidate_comparators: list[StudyComparatorCharacteristics]
    candidate_outcomes: list[StudyOutcomeCharacteristics]
    effect_value: float | None
    ci_lower: float | None
    ci_upper: float | None
    weight_fraction: float | None
    control_baseline_risk: float | None

    def __post_init__(self) -> None:
        if not self.data_row_id.strip() or not self.study_id.strip():
            raise ValueError(
                "GRADE indirectness DataRow and study IDs must not be empty"
            )
        if self.weight_fraction is not None and not (
            0.0 <= self.weight_fraction <= 1.0
        ):
            raise ValueError(
                "GRADE indirectness weight_fraction must be between 0 and 1"
            )
        if self.control_baseline_risk is not None and not (
            0.0 <= self.control_baseline_risk <= 1.0
        ):
            raise ValueError(
                "GRADE indirectness control baseline risk must be between 0 and 1"
            )


@dataclass(frozen=True)
class GRADEIndirectnessCoverage:
    expected_data_row_ids: list[str]
    available_data_row_ids: list[str]
    missing_data_row_ids: list[str]
    missing_study_pio_data_row_ids: list[str]
    ambiguous_mapping_data_row_ids: list[str]
    missing_weight_data_row_ids: list[str]

    def __post_init__(self) -> None:
        expected = set(self.expected_data_row_ids)
        available = set(self.available_data_row_ids)
        missing = set(self.missing_data_row_ids)
        for name, values in (
            ("expected_data_row_ids", self.expected_data_row_ids),
            ("available_data_row_ids", self.available_data_row_ids),
            ("missing_data_row_ids", self.missing_data_row_ids),
            (
                "missing_study_pio_data_row_ids",
                self.missing_study_pio_data_row_ids,
            ),
            ("ambiguous_mapping_data_row_ids", self.ambiguous_mapping_data_row_ids),
            ("missing_weight_data_row_ids", self.missing_weight_data_row_ids),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"GRADE indirectness {name} must be unique")
        if available | missing != expected or available & missing:
            raise ValueError(
                "GRADE indirectness coverage must partition expected DataRows"
            )
        expected_available_order = [
            item for item in self.expected_data_row_ids if item in available
        ]
        if self.available_data_row_ids != expected_available_order:
            raise ValueError(
                "GRADE indirectness available DataRows must follow expected order"
            )
        for name, values in (
            ("missing Study PIO", self.missing_study_pio_data_row_ids),
            ("ambiguous mapping", self.ambiguous_mapping_data_row_ids),
            ("missing weight", self.missing_weight_data_row_ids),
        ):
            if not set(values).issubset(available):
                raise ValueError(
                    f"GRADE indirectness {name} IDs must refer to available DataRows"
                )


@dataclass(frozen=True)
class GRADEIndirectnessInput:
    setting: GRADEIndirectnessSetting
    estimate: GRADEIndirectnessEstimate
    review_population: list[str]
    review_intervention: list[str]
    review_comparator: list[str]
    review_outcome: list[str]
    screening_criteria: ScreeningCriteria
    study_evidence: list[GRADEIndirectnessStudyEvidence]
    direct_comparison_status: str
    subgroup_estimates: list[SubgroupEstimate]
    subgroup_difference_tests: list[SubgroupDifferenceTest]
    coverage: GRADEIndirectnessCoverage

    def __post_init__(self) -> None:
        if self.direct_comparison_status not in (
            GRADE_INDIRECTNESS_DIRECT_COMPARISON_STATUSES
        ):
            raise ValueError(
                "Unsupported GRADE indirectness direct comparison status"
            )
        if self.estimate.included_data_row_ids != self.coverage.expected_data_row_ids:
            raise ValueError(
                "GRADE indirectness estimate DataRows must match coverage order"
            )
        row_ids = [item.data_row_id for item in self.study_evidence]
        if row_ids != self.coverage.available_data_row_ids:
            raise ValueError(
                "GRADE indirectness evidence must match available DataRow order"
            )
        if len(set(row_ids)) != len(row_ids):
            raise ValueError("GRADE indirectness evidence DataRow IDs must be unique")


@dataclass(frozen=True)
class GRADEImprecisionSetting:
    setting_id: str
    setting_family_id: str
    population: str
    comparison: AnalysisComparison
    outcome: AnalysisOutcome
    timepoint: AnalysisTimepoint
    subgroup: AnalysisSubgroup
    data_type: DataType
    effect_measure: str

    def __post_init__(self) -> None:
        if not self.setting_id.strip():
            raise ValueError("GRADE imprecision setting_id must not be empty")
        if not self.setting_family_id.strip():
            raise ValueError(
                "GRADE imprecision setting_family_id must not be empty"
            )
        if not self.effect_measure.strip():
            raise ValueError(
                "GRADE imprecision effect_measure must not be empty"
            )


@dataclass(frozen=True)
class GRADEImprecisionEstimate:
    estimate_type: str
    estimate_id: str
    estimation_status: str
    included_study_ids: list[str]
    included_data_row_ids: list[str]
    participant_count: int
    data_type: DataType
    effect_measure: str
    ci_level: str
    pooled_effect: float | None
    ci_lower: float | None
    ci_upper: float | None
    effect_direction_convention: str | None = None

    def __post_init__(self) -> None:
        if self.estimate_type not in {"overall", "subgroup"}:
            raise ValueError(
                "GRADE imprecision estimate_type must be overall or subgroup"
            )
        if not self.estimate_id.strip():
            raise ValueError("GRADE imprecision estimate_id must not be empty")
        if self.participant_count < 0:
            raise ValueError(
                "GRADE imprecision participant_count must not be negative"
            )
        if not self.effect_measure.strip():
            raise ValueError(
                "GRADE imprecision estimate effect_measure must not be empty"
            )
        for name, values in (
            ("included_study_ids", self.included_study_ids),
            ("included_data_row_ids", self.included_data_row_ids),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"GRADE imprecision {name} must be unique")


@dataclass(frozen=True)
class GRADEImprecisionDataRow:
    data_row_id: str
    study_id: str
    data_type: DataType
    result_data: (
        DichotomousResultData
        | ContinuousResultData
        | GenericInverseVarianceResultData
    )

    def __post_init__(self) -> None:
        if not self.data_row_id.strip() or not self.study_id.strip():
            raise ValueError(
                "GRADE imprecision DataRow and study IDs must not be empty"
            )
        if self.data_type == DataType.DICHOTOMOUS and not isinstance(
            self.result_data,
            DichotomousResultData,
        ):
            raise ValueError(
                "Dichotomous GRADE imprecision rows require DichotomousResultData"
            )
        if self.data_type == DataType.CONTINUOUS and not isinstance(
            self.result_data,
            (ContinuousResultData, GenericInverseVarianceResultData),
        ):
            raise ValueError(
                "Continuous GRADE imprecision rows require continuous arm data or GIV data"
            )


@dataclass(frozen=True)
class GRADEImprecisionCoverage:
    expected_data_row_ids: list[str]
    available_data_row_ids: list[str]
    missing_data_row_ids: list[str]

    def __post_init__(self) -> None:
        expected = set(self.expected_data_row_ids)
        available = set(self.available_data_row_ids)
        missing = set(self.missing_data_row_ids)
        for name, values in (
            ("expected_data_row_ids", self.expected_data_row_ids),
            ("available_data_row_ids", self.available_data_row_ids),
            ("missing_data_row_ids", self.missing_data_row_ids),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"GRADE imprecision {name} must be unique")
        if available | missing != expected or available & missing:
            raise ValueError(
                "GRADE imprecision coverage must partition expected DataRows"
            )
        expected_available_order = [
            item for item in self.expected_data_row_ids if item in available
        ]
        if self.available_data_row_ids != expected_available_order:
            raise ValueError(
                "GRADE imprecision available DataRows must follow expected order"
            )


@dataclass(frozen=True)
class GRADEImprecisionInput:
    setting: GRADEImprecisionSetting
    estimate: GRADEImprecisionEstimate
    contributing_data_rows: list[GRADEImprecisionDataRow]
    coverage: GRADEImprecisionCoverage

    def __post_init__(self) -> None:
        if self.setting.data_type != self.estimate.data_type:
            raise ValueError(
                "GRADE imprecision setting and estimate data types must match"
            )
        if self.setting.effect_measure != self.estimate.effect_measure:
            raise ValueError(
                "GRADE imprecision setting and estimate effect measures must match"
            )
        if self.estimate.included_data_row_ids != self.coverage.expected_data_row_ids:
            raise ValueError(
                "GRADE imprecision estimate DataRows must match coverage order"
            )
        row_ids = [item.data_row_id for item in self.contributing_data_rows]
        if row_ids != self.coverage.available_data_row_ids:
            raise ValueError(
                "GRADE imprecision evidence must match available DataRow order"
            )
        if len(set(row_ids)) != len(row_ids):
            raise ValueError("GRADE imprecision evidence DataRow IDs must be unique")
        if any(
            row.data_type != self.setting.data_type
            for row in self.contributing_data_rows
        ):
            raise ValueError(
                "GRADE imprecision contributing DataRows must match setting data type"
            )


@dataclass(frozen=True)
class EffectEstimateRef:
    estimate_type: str
    estimate_id: str | None = None
    estimation_status: str | None = None


@dataclass(frozen=True)
class GRADEDomainJudgement:
    domain: GradeDomainName
    downgraded: str
    severity: str
    levels: int | str
    level_evaluable: bool
    rationale: str
    assessment_status: str = "assessed"
    source_spans: list[EvidenceSourceSpan] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.severity not in GRADE_DOMAIN_SEVERITIES:
            raise ValueError(
                "GRADE domain severity must be one of: "
                + ", ".join(sorted(GRADE_DOMAIN_SEVERITIES))
            )
        if self.assessment_status not in GRADE_DOMAIN_ASSESSMENT_STATUSES:
            raise ValueError(
                "GRADE domain assessment_status must be one of: "
                + ", ".join(sorted(GRADE_DOMAIN_ASSESSMENT_STATUSES))
            )


@dataclass(frozen=True)
class DomainJudgements:
    risk_of_bias: GRADEDomainJudgement
    inconsistency: GRADEDomainJudgement
    indirectness: GRADEDomainJudgement
    imprecision: GRADEDomainJudgement


@dataclass(frozen=True)
class SoFRowGRADEAssessment:
    sof_row_id: str
    row_label: str | None
    setting_id: str
    setting_family_id: str
    population_scope: str
    comparison: AnalysisComparison
    outcome: AnalysisOutcome
    timepoint: AnalysisTimepoint
    subgroup: AnalysisSubgroup
    effect_estimate_ref: EffectEstimateRef
    included_study_ids: list[str]
    domain_judgements: DomainJudgements


@dataclass(frozen=True)
class GradeResult:
    review_id: str
    question_text: str
    sof_rows: list[SoFRowGRADEAssessment] = field(default_factory=list)
