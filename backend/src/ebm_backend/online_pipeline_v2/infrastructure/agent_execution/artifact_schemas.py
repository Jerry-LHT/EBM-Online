"""Canonical Pydantic roots for Agent-authored sidecar artifacts."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from ebm_backend.online_pipeline_v2.domain.common import ArtifactIssue
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasDocumentV4,
)
from ebm_backend.online_pipeline_v2.domain.search import Record, SearchRun
from ebm_backend.online_pipeline_v2.domain.selection import (
    RecordReportLink,
    RecordScreeningDecision,
    Report,
    ReportDiscoveryLink,
    ReportEvidenceObservation,
    SelectionConflict,
    Study,
    StudyEligibilityDecision,
    StudyReportLink,
)
from ebm_backend.online_pipeline_v2.domain.study_characteristics import (
    CharacteristicField,
    CharacteristicsReportEvidenceObservation,
    DiscoveredReportLink,
    StudyArm,
    StudyMethods,
    StudyOutcome,
    StudyPopulation,
    StudyCharacteristicsRecord,
)
from .artifact_contract import VersionedArtifactContract


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
JsonPointer = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^/"),
]
RevManLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


class SourceResultV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["source-result.v2"]
    search_run: SearchRun
    records: tuple[Record, ...]
    tool_observation: dict[str, Any] = Field(default_factory=dict)


class SearchCollectionsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_runs: tuple[SearchRun, ...]
    records: tuple[Record, ...]


class SelectionCollectionsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_screening: tuple[RecordScreeningDecision, ...]
    reports: tuple[Report, ...]
    report_discoveries: tuple[ReportDiscoveryLink, ...]
    record_report_links: tuple[RecordReportLink, ...]
    report_evidence: tuple[ReportEvidenceObservation, ...]
    studies: tuple[Study, ...]
    study_report_links: tuple[StudyReportLink, ...]
    study_decisions: tuple[StudyEligibilityDecision, ...]
    conflicts: tuple[SelectionConflict, ...]


class CharacteristicsCollectionsV5(BaseModel):
    model_config = ConfigDict(extra="forbid")

    studies: tuple[StudyCharacteristicsRecord, ...]
    discovered_reports: tuple[Report, ...]
    discovered_report_links: tuple[DiscoveredReportLink, ...]
    report_evidence: tuple[CharacteristicsReportEvidenceObservation, ...]
    issues: tuple[ArtifactIssue, ...]


class StudyResultScalar(BaseModel):
    """A JSON scalar whose declared kind preserves zero and missing distinctly."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["integer", "number", "text", "boolean"]
    value: int | float | str | bool

    @model_validator(mode="after")
    def validate_kind(self) -> "StudyResultScalar":
        value_type = type(self.value)
        valid = {
            "integer": value_type is int,
            "number": value_type in {int, float},
            "text": value_type is str and bool(self.value.strip()),
            "boolean": value_type is bool,
        }
        if not valid[self.kind]:
            raise ValueError("scalar value does not match its declared kind")
        return self


class StudyResultsAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_id: NonBlank
    standard: NonBlank
    title: NonBlank
    version_or_date: NonBlank
    locator: NonBlank
    scope: tuple[NonBlank, ...] = ()
    applied_principles: tuple[NonBlank, ...] = ()


class StudyResultsMethodDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: NonBlank
    topic: NonBlank
    decision: NonBlank
    rationale: NonBlank
    authority_ids: tuple[NonBlank, ...] = ()
    protocol_references: tuple[NonBlank, ...] = ()


class StudyResultsAccessAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator: NonBlank
    evidence_format: NonBlank
    accessed: bool
    content_scope: Literal[
        "citation_metadata",
        "abstract",
        "partial_report",
        "complete_report",
        "complete_registry_record",
        "supplement",
        "correction",
        "other",
    ]
    observed_at: str | None = None
    summary: NonBlank


class StudyResultsReportCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: NonBlank
    status: Literal["not_started", "inspected", "unavailable", "unreported", "unusable"]
    attempts: tuple[StudyResultsAccessAttempt, ...] = ()
    reason: NonBlank | None = None


class StudyResultTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: NonBlank
    outcome_name: NonBlank
    revman_outcome_name: NonBlank
    timepoint: NonBlank | None = None
    population: NonBlank | None = None
    comparison: NonBlank | None = None
    analysis_population: NonBlank | None = None
    unit_of_analysis: NonBlank | None = None
    protocol_references: tuple[NonBlank, ...] = ()
    report_ids: tuple[NonBlank, ...] = ()


class StudyResultSourceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: NonBlank
    report_id: NonBlank
    target_id: NonBlank | None = None
    source_locator: NonBlank
    source_location: NonBlank
    evidence_description: NonBlank
    reported_name: NonBlank
    reported_value: StudyResultScalar
    reported_unit: str | None = None
    uncertainty: str | None = None


class StudyResultArm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_id: NonBlank
    label: NonBlank
    description: NonBlank | None = None
    intervention: NonBlank | None = None


class StudyResultValueOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_path: NonBlank
    kind: Literal["observed", "derived"]
    observation_id: NonBlank | None = None
    derivation_id: NonBlank | None = None
    source_path: NonBlank

    @model_validator(mode="after")
    def validate_origin(self) -> "StudyResultValueOrigin":
        if not self.result_path.startswith("/"):
            raise ValueError("result_path must be a JSON Pointer")
        if self.kind == "observed" and (
            not self.observation_id or self.derivation_id is not None
        ):
            raise ValueError("observed origin requires only observation_id")
        if self.kind == "derived" and (
            not self.derivation_id or self.observation_id is not None
        ):
            raise ValueError("derived origin requires only derivation_id")
        return self


class RevManContinuousRawDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mean: float | int | None = None
    ci_start: float | int | None = Field(default=None, alias="ci-start")
    ci_end: float | int | None = Field(default=None, alias="ci-end")
    ci_level: Literal[0.9, 0.95, 0.99] | None = Field(
        default=None,
        alias="ci-level",
    )
    se: Annotated[float | int, Field(ge=0)] | None = None
    sd: Annotated[float | int, Field(ge=0)] | None = None
    sample_size: Annotated[int, Field(ge=1, le=99_999_999)] | None = Field(
        default=None,
        alias="sample-size",
    )
    variance: Annotated[float | int, Field(ge=0)] | None = None
    p_value: float | int | None = Field(default=None, alias="p-value")
    t_test: float | int | None = Field(default=None, alias="t-test")

    @model_validator(mode="after")
    def require_input(self) -> "RevManContinuousRawDataV1":
        if all(value is None for value in self.__dict__.values()):
            raise ValueError("continuous raw-data requires at least one value")
        return self


class RevManContrastRawDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mean: float | int | None = None
    ci_start: float | int | None = Field(default=None, alias="ci-start")
    ci_end: float | int | None = Field(default=None, alias="ci-end")
    exp_mean: float | int | None = Field(default=None, alias="exp-mean")
    exp_ci_start: float | int | None = Field(default=None, alias="exp-ci-start")
    exp_ci_end: float | int | None = Field(default=None, alias="exp-ci-end")
    ci_level: Literal[0.9, 0.95, 0.99] | None = Field(
        default=None,
        alias="ci-level",
    )
    se: Annotated[float | int, Field(ge=0)] | None = None
    sample_size: Annotated[int, Field(ge=1, le=999_999_999)] | None = Field(
        default=None,
        alias="sample-size",
    )
    variance: Annotated[float | int, Field(ge=0)] | None = None
    z_test: float | int | None = Field(default=None, alias="z-test")
    p_value: float | int | None = Field(default=None, alias="p-value")
    t_test: float | int | None = Field(default=None, alias="t-test")

    @model_validator(mode="after")
    def require_input(self) -> "RevManContrastRawDataV1":
        if all(value is None for value in self.__dict__.values()):
            raise ValueError("contrast raw-data requires at least one value")
        return self


class RevManDichotomousDataRowV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm: RevManLabel
    cases: Annotated[int, Field(ge=0, le=999_999_999)]
    sample_size: Annotated[int, Field(ge=1, le=999_999_999)] = Field(
        alias="sample-size"
    )

    @model_validator(mode="after")
    def validate_cases(self) -> "RevManDichotomousDataRowV1":
        if self.cases > self.sample_size:
            raise ValueError("cases cannot exceed sample-size")
        return self


class RevManContinuousDataRowV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm: RevManLabel
    mean: float | int | None = None
    sd: Annotated[float | int, Field(ge=0)] | None = None
    sample_size: Annotated[int, Field(ge=1, le=999_999_999)] | None = Field(
        default=None,
        alias="sample-size",
    )
    raw_data: RevManContinuousRawDataV1 | None = Field(
        default=None,
        alias="raw-data",
    )

    @model_validator(mode="after")
    def validate_complete_data(self) -> "RevManContinuousDataRowV1":
        complete = all(
            value is not None for value in (self.mean, self.sd, self.sample_size)
        )
        if not complete and self.raw_data is None:
            raise ValueError(
                "continuous row requires mean, sd, and sample-size or raw-data"
            )
        return self


class RevManArmLevelResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dichotomous_data_rows: tuple[RevManDichotomousDataRowV1, ...] | None = Field(
        default=None,
        alias="dichotomous-data-rows",
    )
    continuous_data_rows: tuple[RevManContinuousDataRowV1, ...] | None = Field(
        default=None,
        alias="continuous-data-rows",
    )
    footnote: str | None = None

    @model_validator(mode="after")
    def validate_data_type(self) -> "RevManArmLevelResultV1":
        present = sum(
            value is not None
            for value in (self.dichotomous_data_rows, self.continuous_data_rows)
        )
        if present != 1:
            raise ValueError(
                "arm-level-result requires exactly one RevMan data-row type"
            )
        rows = self.dichotomous_data_rows or self.continuous_data_rows or ()
        if not rows:
            raise ValueError("arm-level-result data rows cannot be empty")
        return self


class RevManContrastDataRowV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm: RevManLabel
    mean: float | int | None = None
    se: Annotated[float | int, Field(ge=0)] | None = None
    sample_size: Annotated[int, Field(ge=1, le=999_999_999)] | None = Field(
        default=None,
        alias="sample-size",
    )
    raw_data: RevManContrastRawDataV1 | None = Field(
        default=None,
        alias="raw-data",
    )

    @model_validator(mode="after")
    def validate_complete_data(self) -> "RevManContrastDataRowV1":
        if (
            not (self.mean is not None and self.se is not None)
            and self.raw_data is None
        ):
            raise ValueError("contrast row requires mean and se or raw-data")
        return self


class RevManContrastArmPairV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_1: RevManLabel = Field(alias="arm-1")
    arm_2: RevManLabel = Field(alias="arm-2")


class RevManOtherContrastDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_1: RevManLabel = Field(alias="arm-1")
    arm_2: RevManLabel = Field(alias="arm-2")
    raw_data: RevManContrastRawDataV1 = Field(alias="raw-data")


class RevManCorrelationDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contrast_1: RevManContrastArmPairV1 = Field(alias="contrast-1")
    contrast_2: RevManContrastArmPairV1 = Field(alias="contrast-2")
    correlation: Annotated[float | int, Field(ge=0, le=1)]


class RevManCovarianceRawDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_on_another_contrast: RevManOtherContrastDataV1 | None = Field(
        default=None,
        alias="data-on-another-contrast",
    )
    data_on_correlation: RevManCorrelationDataV1 | None = Field(
        default=None,
        alias="data-on-correlation",
    )
    approximation: dict[Literal["never"], Any] | None = None

    @model_validator(mode="after")
    def validate_method(self) -> "RevManCovarianceRawDataV1":
        present = sum(
            value is not None
            for value in (
                self.data_on_another_contrast,
                self.data_on_correlation,
                self.approximation,
            )
        )
        if present != 1:
            raise ValueError("covariance raw-data requires exactly one method")
        if self.approximation:
            raise ValueError("covariance approximation must be an empty object")
        return self


class RevManCovarianceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | int | None = None
    method: Literal["OTHER_CONTRAST", "CORRELATION", "APPROXIMATION"] | None = None
    raw_data: RevManCovarianceRawDataV1 | None = Field(
        default=None,
        alias="raw-data",
    )

    @model_validator(mode="after")
    def require_value(self) -> "RevManCovarianceV1":
        if self.value is None and self.raw_data is None:
            raise ValueError("covariance requires value or raw-data")
        return self


class RevManContrastLevelResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect_measure: Literal[
        "LOG_OR",
        "LOG_RR",
        "LOG_HR",
        "LOG_RATE_RATIO",
        "RD",
        "MD",
        "SMD",
    ] = Field(alias="effect-measure")
    reference_arm: RevManLabel = Field(alias="reference-arm")
    reference_arm_sample_size: (
        Annotated[
            int,
            Field(ge=1, le=999_999_999),
        ]
        | None
    ) = Field(default=None, alias="reference-arm-sample-size")
    contrast_data_rows: tuple[RevManContrastDataRowV1, ...] = Field(
        alias="contrast-data-rows"
    )
    covariance: RevManCovarianceV1 | None = None
    footnote: str | None = None

    @model_validator(mode="after")
    def validate_rows(self) -> "RevManContrastLevelResultV1":
        if not self.contrast_data_rows:
            raise ValueError("contrast-data-rows cannot be empty")
        if any(row.arm == self.reference_arm for row in self.contrast_data_rows):
            raise ValueError("contrast arm cannot equal reference-arm")
        return self


class RevManResultV1(BaseModel):
    """Strict Study Results profile of Cochrane result.schema.json v1.

    Risk-of-bias fields are intentionally excluded because they belong to the
    separate Risk of Bias professional task.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    arm_level_result: RevManArmLevelResultV1 | None = Field(
        default=None,
        alias="arm-level-result",
    )
    contrast_level_results: tuple[RevManContrastLevelResultV1, ...] | None = Field(
        default=None,
        alias="contrast-level-results",
    )

    @model_validator(mode="after")
    def require_data(self) -> "RevManResultV1":
        if self.arm_level_result is None and not self.contrast_level_results:
            raise ValueError("RevMan result requires arm- or contrast-level data")
        return self


class StudyResultRevManNormalization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["revman"]
    result: RevManResultV1
    origins: tuple[StudyResultValueOrigin, ...]


class StudyResultSourceOnlyNormalization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["source_only"]
    reason: Literal[
        "unreported",
        "unusable",
        "conflicting",
        "insufficient_numeric_reporting",
        "unsupported_by_revman_profile",
        "not_applicable",
    ]
    rationale: NonBlank


StudyResultNormalization = Annotated[
    StudyResultRevManNormalization | StudyResultSourceOnlyNormalization,
    Field(discriminator="kind"),
]


class StudyResultDerivationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: NonBlank
    result_path: NonBlank
    output_path: NonBlank

    @model_validator(mode="after")
    def validate_result_path(self) -> "StudyResultDerivationProjection":
        if not self.result_path.startswith("/"):
            raise ValueError("result_path must be a JSON Pointer")
        return self


class StudyResultDerivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    derivation_id: NonBlank
    tool: Literal["result-calculator"]
    operation: NonBlank
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    input_digest: NonBlank
    output_digest: NonBlank
    projections: tuple[StudyResultDerivationProjection, ...]


class StudyResultConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflict_id: NonBlank
    description: NonBlank
    observation_ids: tuple[NonBlank, ...] = ()
    resolved: bool
    resolution: NonBlank | None = None


class StudyResolvedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: NonBlank
    target_id: NonBlank
    evidence_status: Literal["reported", "unreported", "unusable", "conflicting"]
    source_observation_ids: tuple[NonBlank, ...] = ()
    normalization: StudyResultNormalization
    derivation_ids: tuple[NonBlank, ...] = ()
    conflict_ids: tuple[NonBlank, ...] = ()
    notes: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def validate_normalization(self) -> "StudyResolvedResult":
        if self.normalization.kind == "revman" and self.evidence_status != "reported":
            raise ValueError("only reported evidence can have RevMan normalization")
        if self.normalization.kind == "source_only":
            expected = {
                "unreported": "unreported",
                "unusable": "unusable",
                "conflicting": "conflicting",
            }.get(self.evidence_status)
            if expected is not None and self.normalization.reason != expected:
                raise ValueError(
                    "source-only reason must match non-reported evidence status"
                )
            if (
                self.evidence_status == "reported"
                and self.normalization.reason
                not in {
                    "insufficient_numeric_reporting",
                    "unsupported_by_revman_profile",
                    "not_applicable",
                }
            ):
                raise ValueError(
                    "reported source-only evidence requires a reporting limitation"
                )
        return self


class StudyResultsStudy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: NonBlank
    display_name: NonBlank
    report_coverage: tuple[StudyResultsReportCoverage, ...]
    targets: tuple[StudyResultTarget, ...] = ()
    source_observations: tuple[StudyResultSourceObservation, ...] = ()
    arms: tuple[StudyResultArm, ...] = ()
    results: tuple[StudyResolvedResult, ...] = ()
    derivations: tuple[StudyResultDerivation, ...] = ()
    conflicts: tuple[StudyResultConflict, ...] = ()
    issues: tuple[ArtifactIssue, ...] = ()
    completed: bool


class StudyResultsReviewProcess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    human_independent_extraction_satisfied: Literal[False]
    methodology_authorities: tuple[StudyResultsAuthority, ...] = ()
    method_decisions: tuple[StudyResultsMethodDecision, ...] = ()
    methodology_basis_status: Literal["verified", "llm_fallback"] | None = None
    fallback_model: NonBlank | None = None
    fallback_note: NonBlank | None = None

    @model_validator(mode="after")
    def validate_methodology_basis(self) -> "StudyResultsReviewProcess":
        if self.methodology_basis_status == "verified" and not self.methodology_authorities:
            raise ValueError("verified Study Results methodology requires an authority")
        if self.methodology_basis_status == "llm_fallback":
            if self.fallback_model is None or self.fallback_note is None:
                raise ValueError("Study Results methodology fallback requires model and note")
        elif self.fallback_model is not None or self.fallback_note is not None:
            raise ValueError("fallback metadata requires llm_fallback methodology")
        if self.methodology_basis_status == "verified":
            authority_ids = {item.authority_id for item in self.methodology_authorities}
            if any(
                not set(item.authority_ids).issubset(authority_ids)
                for item in self.method_decisions
            ):
                raise ValueError("Study Results method decision references unknown authority")
        return self


class StudyResultsDocumentV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["study-results-document.v3"]
    binding: dict[NonBlank, NonBlank]
    status: Literal["incomplete", "blocked", "completed"]
    review_process: StudyResultsReviewProcess
    studies: tuple[StudyResultsStudy, ...]
    issues: tuple[ArtifactIssue, ...] = ()


class StudyDataScalarV1(BaseModel):
    """Source-faithful scalar; decimals retain their reported lexical value."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["integer", "decimal", "text", "boolean"]
    value: int | str | bool

    @model_validator(mode="after")
    def validate_kind(self) -> "StudyDataScalarV1":
        value_type = type(self.value)
        valid = {
            "integer": value_type is int,
            "decimal": (
                value_type is str
                and bool(self.value.strip())
                and _is_finite_decimal(self.value)
            ),
            "text": value_type is str and bool(self.value.strip()),
            "boolean": value_type is bool,
        }
        if not valid[self.kind]:
            raise ValueError("scalar value does not match its declared kind")
        return self


class StudyDataResultObservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: NonBlank
    report_id: NonBlank
    target_id: NonBlank | None = None
    source_locator: NonBlank
    source_location: NonBlank
    evidence_description: NonBlank
    reported_name: NonBlank
    reported_value: StudyDataScalarV1
    reported_unit: str | None = None
    uncertainty: str | None = None


class StudyDataResultTargetV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: NonBlank
    outcome_id: NonBlank
    outcome_name: NonBlank
    revman_outcome_name: NonBlank
    timepoint: NonBlank | None = None
    population: NonBlank | None = None
    comparison: NonBlank | None = None
    analysis_population: NonBlank | None = None
    unit_of_analysis: NonBlank | None = None
    protocol_references: tuple[NonBlank, ...] = ()
    report_ids: tuple[NonBlank, ...] = ()


class StudyDataAdditionalCharacteristicV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: NonBlank
    category: NonBlank
    label: NonBlank
    field: CharacteristicField
    protocol_references: tuple[NonBlank, ...] = ()


class StudyDataCharacteristicsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "partial"]
    methods: StudyMethods
    population: StudyPopulation
    funding: CharacteristicField
    conflicts_of_interest: CharacteristicField
    notes: CharacteristicField
    additional_characteristics: tuple[StudyDataAdditionalCharacteristicV1, ...] = ()


class StudyDataCalculationInputOriginV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["observed", "calculated"]
    observation_id: NonBlank | None = None
    calculation_id: NonBlank | None = None
    output_name: Literal["value", "exact"] | None = None

    @model_validator(mode="after")
    def validate_origin(self) -> "StudyDataCalculationInputOriginV2":
        if self.kind == "observed" and (
            not self.observation_id
            or self.calculation_id is not None
            or self.output_name is not None
        ):
            raise ValueError("observed calculation input requires observation_id")
        if self.kind == "calculated" and (
            not self.calculation_id
            or self.observation_id is not None
            or self.output_name is None
        ):
            raise ValueError(
                "calculated input requires calculation_id and output_name"
            )
        return self


class StudyDataValueOriginV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["observed", "calculated"]
    observation_id: NonBlank | None = None
    calculation_id: NonBlank | None = None
    output_name: Literal["value", "exact"] | None = None

    @model_validator(mode="after")
    def validate_origin(self) -> "StudyDataValueOriginV3":
        if self.kind == "observed" and (
            not self.observation_id
            or self.calculation_id is not None
            or self.output_name is not None
        ):
            raise ValueError("observed representation value requires observation_id")
        if self.kind == "calculated" and (
            not self.calculation_id
            or self.observation_id is not None
            or self.output_name is None
        ):
            raise ValueError(
                "calculated representation value requires calculation_id "
                "and output_name"
            )
        return self


class StudyDataNumericValueV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value_id: NonBlank
    value: int | float
    origin: StudyDataValueOriginV3


class StudyDataRevManContinuousRawDataV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mean: StudyDataNumericValueV3 | None = None
    ci_start: StudyDataNumericValueV3 | None = Field(default=None, alias="ci-start")
    ci_end: StudyDataNumericValueV3 | None = Field(default=None, alias="ci-end")
    ci_level: StudyDataNumericValueV3 | None = Field(default=None, alias="ci-level")
    se: StudyDataNumericValueV3 | None = None
    sd: StudyDataNumericValueV3 | None = None
    sample_size: StudyDataNumericValueV3 | None = Field(
        default=None, alias="sample-size"
    )
    variance: StudyDataNumericValueV3 | None = None
    p_value: StudyDataNumericValueV3 | None = Field(default=None, alias="p-value")
    t_test: StudyDataNumericValueV3 | None = Field(default=None, alias="t-test")


class StudyDataRevManContrastRawDataV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mean: StudyDataNumericValueV3 | None = None
    ci_start: StudyDataNumericValueV3 | None = Field(default=None, alias="ci-start")
    ci_end: StudyDataNumericValueV3 | None = Field(default=None, alias="ci-end")
    exp_mean: StudyDataNumericValueV3 | None = Field(default=None, alias="exp-mean")
    exp_ci_start: StudyDataNumericValueV3 | None = Field(
        default=None, alias="exp-ci-start"
    )
    exp_ci_end: StudyDataNumericValueV3 | None = Field(
        default=None, alias="exp-ci-end"
    )
    ci_level: StudyDataNumericValueV3 | None = Field(default=None, alias="ci-level")
    se: StudyDataNumericValueV3 | None = None
    sample_size: StudyDataNumericValueV3 | None = Field(
        default=None, alias="sample-size"
    )
    variance: StudyDataNumericValueV3 | None = None
    z_test: StudyDataNumericValueV3 | None = Field(default=None, alias="z-test")
    p_value: StudyDataNumericValueV3 | None = Field(default=None, alias="p-value")
    t_test: StudyDataNumericValueV3 | None = Field(default=None, alias="t-test")


class StudyDataRevManDichotomousRowV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_id: NonBlank
    cases: StudyDataNumericValueV3
    sample_size: StudyDataNumericValueV3 = Field(alias="sample-size")


class StudyDataRevManContinuousRowV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_id: NonBlank
    mean: StudyDataNumericValueV3 | None = None
    sd: StudyDataNumericValueV3 | None = None
    sample_size: StudyDataNumericValueV3 | None = Field(
        default=None, alias="sample-size"
    )
    raw_data: StudyDataRevManContinuousRawDataV3 | None = Field(
        default=None, alias="raw-data"
    )


class StudyDataRevManArmLevelResultV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dichotomous_data_rows: tuple[StudyDataRevManDichotomousRowV3, ...] | None = (
        Field(default=None, alias="dichotomous-data-rows")
    )
    continuous_data_rows: tuple[StudyDataRevManContinuousRowV3, ...] | None = Field(
        default=None, alias="continuous-data-rows"
    )
    footnote: str | None = None


class StudyDataRevManContrastRowV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_id: NonBlank
    mean: StudyDataNumericValueV3 | None = None
    se: StudyDataNumericValueV3 | None = None
    sample_size: StudyDataNumericValueV3 | None = Field(
        default=None, alias="sample-size"
    )
    raw_data: StudyDataRevManContrastRawDataV3 | None = Field(
        default=None, alias="raw-data"
    )


class StudyDataRevManContrastArmPairV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_1_id: NonBlank = Field(alias="arm-1-id")
    arm_2_id: NonBlank = Field(alias="arm-2-id")


class StudyDataRevManOtherContrastDataV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_1_id: NonBlank = Field(alias="arm-1-id")
    arm_2_id: NonBlank = Field(alias="arm-2-id")
    raw_data: StudyDataRevManContrastRawDataV3 = Field(alias="raw-data")


class StudyDataRevManCorrelationDataV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contrast_1: StudyDataRevManContrastArmPairV3 = Field(alias="contrast-1")
    contrast_2: StudyDataRevManContrastArmPairV3 = Field(alias="contrast-2")
    correlation: StudyDataNumericValueV3


class StudyDataRevManCovarianceRawDataV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_on_another_contrast: StudyDataRevManOtherContrastDataV3 | None = Field(
        default=None, alias="data-on-another-contrast"
    )
    data_on_correlation: StudyDataRevManCorrelationDataV3 | None = Field(
        default=None, alias="data-on-correlation"
    )
    approximation: dict[Literal["never"], Any] | None = None


class StudyDataRevManCovarianceV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StudyDataNumericValueV3 | None = None
    method: Literal["OTHER_CONTRAST", "CORRELATION", "APPROXIMATION"] | None = None
    raw_data: StudyDataRevManCovarianceRawDataV3 | None = Field(
        default=None, alias="raw-data"
    )


class StudyDataRevManContrastLevelResultV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect_measure: Literal[
        "LOG_OR", "LOG_RR", "LOG_HR", "LOG_RATE_RATIO", "RD", "MD", "SMD"
    ] = Field(alias="effect-measure")
    reference_arm_id: NonBlank = Field(alias="reference-arm-id")
    reference_arm_sample_size: StudyDataNumericValueV3 | None = Field(
        default=None, alias="reference-arm-sample-size"
    )
    contrast_data_rows: tuple[StudyDataRevManContrastRowV3, ...] = Field(
        alias="contrast-data-rows"
    )
    covariance: StudyDataRevManCovarianceV3 | None = None
    footnote: str | None = None


class StudyDataRevManResultV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_level_result: StudyDataRevManArmLevelResultV3 | None = Field(
        default=None, alias="arm-level-result"
    )
    contrast_level_results: tuple[StudyDataRevManContrastLevelResultV3, ...] | None = (
        Field(default=None, alias="contrast-level-results")
    )


class StudyDataRevManRepresentationV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    representation_id: NonBlank
    kind: Literal["revman"]
    result: StudyDataRevManResultV3
    notes: tuple[NonBlank, ...] = ()


class StudyDataCollectionAssessmentV2(BaseModel):
    """Agent-authored professional assessment of the collected source state."""

    model_config = ConfigDict(extra="forbid")

    status: NonBlank
    rationale: NonBlank
    report_ids: tuple[NonBlank, ...] = ()
    limitations: tuple[NonBlank, ...] = ()


class StudyDataCollectedResultV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: NonBlank
    target_id: NonBlank
    collection_assessment: StudyDataCollectionAssessmentV2
    source_observation_ids: tuple[NonBlank, ...] = ()
    analysis_representations: tuple[StudyDataRevManRepresentationV3, ...] = ()
    calculation_ids: tuple[NonBlank, ...] = ()
    conflict_ids: tuple[NonBlank, ...] = ()
    notes: tuple[NonBlank, ...] = ()


class StudyDataCalculationV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    derivation_id: NonBlank
    tool: Literal["data-calculator"]
    expression: NonBlank
    inputs: dict[NonBlank, NonBlank]
    input_origins: dict[NonBlank, StudyDataCalculationInputOriginV2]
    precision: Annotated[int, Field(ge=16, le=80)] = 34
    outputs: dict[Literal["value", "exact"], int | float | str]
    input_digest: NonBlank
    output_digest: NonBlank
    rationale: NonBlank

    @model_validator(mode="after")
    def validate_inputs(self) -> "StudyDataCalculationV1":
        if not self.inputs or set(self.inputs) != set(self.input_origins):
            raise ValueError("calculation inputs require exact input origins")
        if set(self.outputs) != {"value", "exact"}:
            raise ValueError("calculation outputs require value and exact")
        return self


class StudyDataCompletionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    characteristics: Literal["completed", "partial"]
    results: Literal["completed", "partial"]
    completed: bool


class StudyDataCollectionStudyV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: NonBlank
    display_name: NonBlank
    report_coverage: tuple[StudyResultsReportCoverage, ...]
    characteristics: StudyDataCharacteristicsV1
    arms: tuple[StudyArm, ...] = ()
    outcomes: tuple[StudyOutcome, ...] = ()
    targets: tuple[StudyDataResultTargetV1, ...] = ()
    source_observations: tuple[StudyDataResultObservationV1, ...] = ()
    results: tuple[StudyDataCollectedResultV2, ...] = ()
    calculations: tuple[StudyDataCalculationV2, ...] = ()
    conflicts: tuple[StudyResultConflict, ...] = ()
    issues: tuple[ArtifactIssue, ...] = ()
    completion: StudyDataCompletionV1


class StudyDataCollectionDocumentV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["study-data-collection-document.v3"]
    binding: dict[NonBlank, NonBlank]
    status: Literal["incomplete", "blocked", "completed"]
    review_process: StudyResultsReviewProcess
    studies: tuple[StudyDataCollectionStudyV1, ...]
    issues: tuple[ArtifactIssue, ...] = ()


class SynthesisReviewProcessV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    human_independent_synthesis_satisfied: Literal[False]
    methodology_authorities: tuple[StudyResultsAuthority, ...] = ()
    method_decisions: tuple[StudyResultsMethodDecision, ...] = ()
    methodology_basis_status: Literal["verified", "llm_fallback"] | None = None
    fallback_model: NonBlank | None = None
    fallback_note: NonBlank | None = None

    @model_validator(mode="after")
    def validate_references(self) -> "SynthesisReviewProcessV2":
        authority_ids = [item.authority_id for item in self.methodology_authorities]
        decision_ids = [item.decision_id for item in self.method_decisions]
        if len(authority_ids) != len(set(authority_ids)):
            raise ValueError("Synthesis authority ids must be unique")
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("Synthesis method decision ids must be unique")
        if self.methodology_basis_status == "verified" and not self.methodology_authorities:
            raise ValueError("verified Synthesis methodology requires an authority")
        if self.methodology_basis_status == "llm_fallback":
            if self.fallback_model is None or self.fallback_note is None:
                raise ValueError("Synthesis methodology fallback requires model and note")
        elif self.fallback_model is not None or self.fallback_note is not None:
            raise ValueError("fallback metadata requires llm_fallback methodology")
        if self.methodology_basis_status == "verified":
            known = set(authority_ids)
            if any(
                not set(item.authority_ids).issubset(known)
                for item in self.method_decisions
            ):
                raise ValueError("Synthesis method decision references unknown authority")
        return self


class SynthesisDefinitionV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    population: NonBlank
    intervention: NonBlank
    comparator: NonBlank
    outcome: NonBlank
    time_point: NonBlank
    study_designs: tuple[NonBlank, ...] = ()


class SynthesisCompatibilityV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: NonBlank
    clinical: NonBlank
    methodological: NonBlank
    statistical: NonBlank


class SynthesisResultValueSourceV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: NonBlank
    representation_id: NonBlank
    source_value_id: NonBlank
    value_name: NonBlank


class SynthesisScalarInputSourceV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: NonBlank
    representation_id: NonBlank
    source_value_id: NonBlank
    input_name: NonBlank


class SynthesisCalculatedValueSourceV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: NonBlank
    output_name: Literal["value", "exact"]
    value_name: NonBlank
    inputs: tuple[SynthesisScalarInputSourceV3, ...] = Field(min_length=1)


class SynthesisAnalysisRepresentationV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    representation_id: NonBlank
    study_id: NonBlank
    data_type: NonBlank
    effect_measure: NonBlank
    source_result_ids: tuple[NonBlank, ...] = Field(min_length=1)
    values: dict[NonBlank, int | float | str]
    result_value_sources: tuple[SynthesisResultValueSourceV3, ...]
    calculated_value_sources: tuple[SynthesisCalculatedValueSourceV3, ...] = ()

    @model_validator(mode="after")
    def validate_projections(self) -> "SynthesisAnalysisRepresentationV3":
        if not self.values:
            raise ValueError("Synthesis representation values cannot be empty")
        if any(
            item.result_id not in self.source_result_ids
            for item in self.result_value_sources
        ):
            raise ValueError("Synthesis projection references an undeclared Result")
        projected = [item.value_name for item in self.result_value_sources]
        projected.extend(item.value_name for item in self.calculated_value_sources)
        if len(projected) != len(set(projected)):
            raise ValueError("Synthesis representation projections must be unique")
        if set(projected) != set(self.values):
            raise ValueError("Every Synthesis representation value requires provenance")
        return self


class SynthesisContributionV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: NonBlank
    included: bool
    reason: NonBlank


class SynthesisRiskOfBiasReferenceV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: NonBlank
    reference: NonBlank
    used_as_statistical_weight: Literal[False]


class SynthesisCalculationTraceV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: NonBlank
    tool: Literal["meta-compute", "scalar-calculate"]
    engine_id: NonBlank
    engine_version: NonBlank
    input_digest: NonBlank
    output_digest: NonBlank
    input: dict[str, Any]
    output: dict[str, Any]
    representation_projections: tuple[dict[str, Any], ...] = ()
    input_projections: tuple[dict[str, Any], ...] = ()
    projections: tuple[dict[str, Any], ...] = ()


class SynthesisOtherMethodV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: NonBlank
    result: NonBlank
    rationale: NonBlank
    limitations: tuple[NonBlank, ...] = ()


class SynthesisReasonV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: NonBlank


class SynthesisAnalysisV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: NonBlank
    synthesis_pico_id: NonBlank | None = None
    origin: Literal["protocol_planned", "protocol_interpretation", "post_hoc"]
    change_rationale: NonBlank | None = None
    definition: SynthesisDefinitionV2
    compatibility: SynthesisCompatibilityV2
    authority_ids: tuple[NonBlank, ...] = ()
    method_decision_ids: tuple[NonBlank, ...] = ()
    settings: dict[str, Any]
    representations: tuple[SynthesisAnalysisRepresentationV3, ...] = ()
    contributions: tuple[SynthesisContributionV2, ...]
    risk_of_bias_refs: tuple[SynthesisRiskOfBiasReferenceV2, ...] = ()
    calculation_traces: tuple[SynthesisCalculationTraceV2, ...] = ()
    data_rows: tuple[dict[str, Any], ...] = ()
    subgroup_estimates: tuple[dict[str, Any], ...] = ()
    overall_estimates_and_settings: tuple[dict[str, Any], ...] = ()
    alternative_synthesis: SynthesisOtherMethodV2 | None = None
    no_pooling: SynthesisReasonV2 | None = None
    no_evidence: SynthesisReasonV2 | None = None
    issues: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def validate_disposition(self) -> "SynthesisAnalysisV3":
        dispositions = sum(
            (
                bool(self.data_rows),
                self.alternative_synthesis is not None,
                self.no_pooling is not None,
                self.no_evidence is not None,
            )
        )
        if dispositions > 1:
            raise ValueError("Synthesis Analysis allows at most one disposition")
        if self.origin == "post_hoc" and self.change_rationale is None:
            raise ValueError("post-hoc Synthesis Analysis requires rationale")
        return self


class EvidenceSynthesisDocumentV3(BaseModel):
    """Single Agent-authored Synthesis document and public scientific result."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-synthesis-document.v3"]
    binding: dict[NonBlank, NonBlank]
    status: Literal["incomplete", "blocked", "completed"]
    review_process: SynthesisReviewProcessV2
    analyses: tuple[SynthesisAnalysisV3, ...]
    issues: tuple[ArtifactIssue, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> "EvidenceSynthesisDocumentV3":
        analysis_ids = [item.analysis_id for item in self.analyses]
        if len(analysis_ids) != len(set(analysis_ids)):
            raise ValueError("Synthesis analysis ids must be unique")
        if self.status == "completed" and not self.analyses:
            raise ValueError("completed Synthesis requires at least one Analysis")
        authorities = {
            item.authority_id for item in self.review_process.methodology_authorities
        }
        decisions = {item.decision_id for item in self.review_process.method_decisions}
        for analysis in self.analyses:
            if not set(analysis.authority_ids).issubset(authorities):
                raise ValueError("Analysis references unknown methodology authority")
            if not set(analysis.method_decision_ids).issubset(decisions):
                raise ValueError("Analysis references unknown method decision")
        return self


def _is_finite_decimal(value: str) -> bool:
    from decimal import Decimal, InvalidOperation

    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return False
    return parsed.is_finite()


SOURCE_RESULT_V2 = VersionedArtifactContract(
    name="source result",
    version="source-result.v2",
    adapter=TypeAdapter(SourceResultV2),
)
SEARCH_COLLECTIONS_V1 = VersionedArtifactContract(
    name="search collections",
    version="agent-search-collections.v1",
    adapter=TypeAdapter(SearchCollectionsV1),
)
SELECTION_COLLECTIONS_V2 = VersionedArtifactContract(
    name="selection collections",
    version="agent-selection-collections.v2",
    adapter=TypeAdapter(SelectionCollectionsV2),
)
CHARACTERISTICS_COLLECTIONS_V5 = VersionedArtifactContract(
    name="characteristics collections",
    version="agent-study-characteristics-collections.v5",
    adapter=TypeAdapter(CharacteristicsCollectionsV5),
)
STUDY_RESULTS_DOCUMENT_V3 = VersionedArtifactContract(
    name="study results document",
    version="study-results-document.v3",
    adapter=TypeAdapter(StudyResultsDocumentV3),
)
STUDY_DATA_COLLECTION_DOCUMENT_V3 = VersionedArtifactContract(
    name="study data collection document",
    version="study-data-collection-document.v3",
    adapter=TypeAdapter(StudyDataCollectionDocumentV3),
)
EVIDENCE_SYNTHESIS_DOCUMENT_V3 = VersionedArtifactContract(
    name="evidence synthesis document",
    version="evidence-synthesis-document.v3",
    adapter=TypeAdapter(EvidenceSynthesisDocumentV3),
)
RISK_OF_BIAS_DOCUMENT_V4 = VersionedArtifactContract(
    name="risk of bias document",
    version="risk-of-bias-document.v4",
    adapter=TypeAdapter(RiskOfBiasDocumentV4),
)
# Compatibility name for callers that have not yet renamed the checked snapshot.
CHARACTERISTICS_COLLECTIONS_V4 = CHARACTERISTICS_COLLECTIONS_V5
