"""GRADE and Summary of Findings task contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isclose
from typing import Literal

from .common import (
    ArtifactFile,
    ArtifactIssue,
    DomainValidationError,
    Provenance,
    require_text,
    require_unique,
)
from .protocol import (
    MethodologyBasisStatus,
    MethodologyReference,
    PICO,
    ProtocolDraft,
    SynthesisPICO,
)


class GRADEDomain(StrEnum):
    RISK_OF_BIAS = "risk_of_bias"
    INCONSISTENCY = "inconsistency"
    INDIRECTNESS = "indirectness"
    IMPRECISION = "imprecision"
    PUBLICATION_BIAS = "publication_bias"


class GRADEConcern(StrEnum):
    NOT_SERIOUS = "not_serious"
    SERIOUS = "serious"
    VERY_SERIOUS = "very_serious"
    EXTREMELY_SERIOUS = "extremely_serious"


class GRADEUpgradeDomain(StrEnum):
    LARGE_EFFECT = "large_effect"
    DOSE_RESPONSE = "dose_response"
    OPPOSING_PLAUSIBLE_RESIDUAL_CONFOUNDING = (
        "opposing_plausible_residual_confounding"
    )


class GRADEUpgradeJudgement(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    NOT_PRESENT = "not_present"
    PRESENT = "present"


class Certainty(StrEnum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    VERY_LOW = "very_low"


class EvidenceProfileStatus(StrEnum):
    GRADED = "graded"
    NO_EVIDENCE = "no_evidence"


class EffectStatus(StrEnum):
    ESTIMATED = "estimated"
    NOT_ESTIMABLE = "not_estimable"
    NOT_REPORTED = "not_reported"


class ProtocolAlignment(StrEnum):
    FOLLOWED = "followed"
    SUPPLEMENTED = "supplemented"
    DEVIATED = "deviated"


@dataclass(frozen=True, slots=True)
class GradeProtocolBlock:
    heading: str
    text: str

    def __post_init__(self) -> None:
        for field_name in ("heading", "text"):
            object.__setattr__(
                self,
                field_name,
                require_text(getattr(self, field_name), f"grade_protocol.{field_name}"),
            )


@dataclass(frozen=True, slots=True)
class GradeProtocol:
    """Complete Protocol context needed to perform GRADE and build SoF tables."""

    version: str
    review_question: str
    review_pico: PICO
    objectives: tuple[str, ...]
    candidate_comparisons: tuple[SynthesisPICO, ...]
    eligibility_and_outcomes: tuple[GradeProtocolBlock, ...]
    risk_of_bias: tuple[GradeProtocolBlock, ...]
    effect_calculation: tuple[GradeProtocolBlock, ...]
    synthesis: tuple[GradeProtocolBlock, ...]
    reporting_bias: tuple[GradeProtocolBlock, ...]
    certainty: tuple[GradeProtocolBlock, ...]
    methodology_basis: tuple[MethodologyReference, ...]
    methodology_basis_status: MethodologyBasisStatus = MethodologyBasisStatus.VERIFIED
    methodology_fallback_model: str | None = None
    methodology_fallback_note: str | None = None
    schema_version: str = "grade-protocol.v2"

    def __post_init__(self) -> None:
        for field_name in ("version", "review_question"):
            object.__setattr__(
                self,
                field_name,
                require_text(getattr(self, field_name), field_name),
            )
        if not self.objectives:
            raise DomainValidationError("GRADE Protocol requires objectives")
        if not self.candidate_comparisons:
            raise DomainValidationError("GRADE Protocol requires candidate comparisons")
        for field_name in (
            "eligibility_and_outcomes",
            "risk_of_bias",
            "effect_calculation",
            "synthesis",
            "reporting_bias",
            "certainty",
        ):
            if not getattr(self, field_name):
                raise DomainValidationError(
                    f"GRADE Protocol requires {field_name.replace('_', ' ')}"
                )
        if self.methodology_basis_status is MethodologyBasisStatus.VERIFIED:
            if not self.methodology_basis:
                raise DomainValidationError(
                    "verified GRADE Protocol requires methodology citations"
                )
        elif self.methodology_basis_status is MethodologyBasisStatus.LLM_FALLBACK:
            if not self.methodology_fallback_model or not self.methodology_fallback_note:
                raise DomainValidationError(
                    "LLM fallback GRADE Protocol requires model and note"
                )
        elif self.methodology_basis_status is MethodologyBasisStatus.UNRESOLVED:
            raise DomainValidationError(
                "unresolved GRADE Protocol cannot be executed"
            )
        if self.schema_version != "grade-protocol.v2":
            raise DomainValidationError("GRADE requires grade-protocol.v2")

    @classmethod
    def from_protocol(cls, protocol: ProtocolDraft) -> "GradeProtocol":
        eligibility = protocol.methods.eligibility
        outcomes = protocol.methods.outcomes.outcomes
        analysis = protocol.methods.analysis
        synthesis = protocol.methods.synthesis
        collection = protocol.methods.data_collection

        def block(heading: str, text: str) -> GradeProtocolBlock:
            return GradeProtocolBlock(heading, text)

        def eligibility_block(heading: str, section: object) -> GradeProtocolBlock:
            parts = [getattr(section, "description")]
            parts.extend(f"Include: {value}" for value in section.inclusion_criteria)
            parts.extend(f"Exclude: {value}" for value in section.exclusion_criteria)
            return block(heading, "\n".join(parts))

        return cls(
            version=protocol.version,
            review_question=protocol.review_question,
            review_pico=protocol.review_pico,
            objectives=protocol.objectives,
            candidate_comparisons=synthesis.comparisons,
            eligibility_and_outcomes=(
                eligibility_block("Types of studies", eligibility.types_of_studies),
                eligibility_block(
                    "Types of participants", eligibility.types_of_participants
                ),
                eligibility_block(
                    "Types of interventions", eligibility.types_of_interventions
                ),
                eligibility_block("Comparators", eligibility.comparators),
            )
            + tuple(
                block(
                    f"{outcome.role.value.title()} outcome: {outcome.name}",
                    "\n".join(
                        (
                            outcome.definition,
                            f"Measurement: {outcome.measurement}",
                            f"Time points: {', '.join(outcome.time_points)}",
                        )
                    ),
                )
                for outcome in outcomes
            ),
            risk_of_bias=(
                block("Risk of bias standard", protocol.methods.risk_of_bias.tool),
                block(
                    "Risk of bias process",
                    "\n".join(
                        (
                            protocol.methods.risk_of_bias.reviewer_process,
                            protocol.methods.risk_of_bias.disagreement_resolution,
                            protocol.methods.risk_of_bias.use_in_synthesis,
                        )
                    ),
                ),
            ),
            effect_calculation=(
                block(
                    "Measures of treatment effect",
                    "\n".join(
                        f"{item.result_type}: {item.effect_measure}"
                        for item in analysis.effect_measures
                    ),
                ),
                block("Unit of analysis issues", analysis.unit_of_analysis),
                block("Dealing with missing data", analysis.missing_data),
            ),
            synthesis=(
                block(
                    "Criteria for synthesis",
                    synthesis.quantitative_synthesis_criteria,
                ),
                block("Meta-analysis", synthesis.meta_analysis_methods),
                block("Non-meta-analysed synthesis", synthesis.non_meta_synthesis),
                block(
                    "Subgroup analysis",
                    "; ".join(synthesis.subgroup_analyses)
                    if synthesis.subgroup_analyses
                    else "No subgroup analysis planned.",
                ),
                block(
                    "Sensitivity analysis",
                    "; ".join(synthesis.sensitivity_analyses)
                    if synthesis.sensitivity_analyses
                    else "No sensitivity analysis planned.",
                ),
            ),
            reporting_bias=(
                block(
                    "Reporting bias and missing evidence",
                    "\n".join(
                        (
                            collection.missing_information,
                            analysis.reporting_bias,
                        )
                    ),
                ),
            ),
            certainty=(
                block(
                    "Summary of Findings plan",
                    protocol.methods.certainty.summary_of_findings_plan,
                ),
                block("Certainty approach", protocol.methods.certainty.approach),
                block(
                    "Outcomes selected for certainty assessment",
                    "; ".join(protocol.methods.certainty.outcomes),
                ),
            ),
            methodology_basis=protocol.methodology_basis,
            methodology_basis_status=protocol.methodology_profile.basis_status,
            methodology_fallback_model=protocol.methodology_profile.fallback_model,
            methodology_fallback_note=protocol.methodology_profile.fallback_note,
        )


@dataclass(frozen=True, slots=True)
class GradeEvidencePackageRef:
    package_id: str
    schema_version: str
    review_id: str
    protocol_version: str
    content_digest: str
    files: tuple[ArtifactFile, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "package_id",
            "schema_version",
            "review_id",
            "protocol_version",
            "content_digest",
        ):
            object.__setattr__(
                self,
                field_name,
                require_text(getattr(self, field_name), field_name),
            )
        if self.schema_version != "grade-evidence-package.v2":
            raise DomainValidationError("unsupported GRADE evidence package schema")
        if not self.files:
            raise DomainValidationError("GRADE evidence package requires files")
        names = tuple(item.name for item in self.files)
        if len(names) != len(set(names)):
            raise DomainValidationError("GRADE evidence package files must be unique")


@dataclass(frozen=True, slots=True)
class EffectPresentation:
    status: EffectStatus
    measure: str | None = None
    estimate: float | None = None
    confidence_interval_lower: float | None = None
    confidence_interval_upper: float | None = None
    confidence_interval_unavailable_reason: str | None = None
    unit: str | None = None
    narrative: str | None = None
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        if self.status is EffectStatus.ESTIMATED:
            if self.measure is None or self.estimate is None:
                raise DomainValidationError(
                    "estimated effect requires measure and estimate"
                )
            object.__setattr__(self, "measure", require_text(self.measure, "measure"))
            if (
                self.confidence_interval_lower is None
            ) != (self.confidence_interval_upper is None):
                raise DomainValidationError(
                    "effect confidence interval requires both limits"
                )
            if (
                self.confidence_interval_lower is not None
                and self.confidence_interval_lower > self.confidence_interval_upper
            ):
                raise DomainValidationError("effect confidence interval is reversed")
            if (
                self.confidence_interval_lower is None
                and self.confidence_interval_unavailable_reason is None
            ):
                raise DomainValidationError(
                    "estimated effect without a confidence interval requires a reason"
                )
            if (
                self.confidence_interval_lower is not None
                and self.confidence_interval_unavailable_reason is not None
            ):
                raise DomainValidationError(
                    "effect with a confidence interval cannot state it is unavailable"
                )
        elif self.estimate is not None:
            raise DomainValidationError("non-estimated effect cannot contain estimate")
        elif (
            self.confidence_interval_lower is not None
            or self.confidence_interval_upper is not None
        ):
            raise DomainValidationError(
                "non-estimated effect cannot contain a confidence interval"
            )
        if self.confidence_interval_unavailable_reason is not None:
            object.__setattr__(
                self,
                "confidence_interval_unavailable_reason",
                require_text(
                    self.confidence_interval_unavailable_reason,
                    "effect.confidence_interval_unavailable_reason",
                ),
            )
        if self.narrative is not None:
            object.__setattr__(
                self, "narrative", require_text(self.narrative, "effect.narrative")
            )


@dataclass(frozen=True, slots=True)
class AbsoluteEffectScenario:
    label: str
    comparator_effect: EffectPresentation
    intervention_effect: EffectPresentation
    absolute_difference: EffectPresentation
    baseline_basis: str
    calculation: "AbsoluteEffectCalculation | None" = None
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("label", "baseline_basis"):
            object.__setattr__(
                self,
                field_name,
                require_text(getattr(self, field_name), field_name),
            )
        if self.calculation is not None:
            _validate_absolute_effect_calculation(self, self.calculation)


@dataclass(frozen=True, slots=True)
class AbsoluteEffectCalculation:
    """Inputs for a supported deterministic absolute-effect derivation.

    Absence means that the scenario was reported upstream or could not be
    derived by a supported calculator. It is not an error or a professional
    insufficiency judgement.
    """

    measure: str
    baseline_risk: float
    effect_estimate: float
    confidence_interval_lower: float | None = None
    confidence_interval_upper: float | None = None
    display_scale: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "measure", require_text(self.measure, "measure"))
        if self.measure not in {"RR", "OR", "RD", "HR"}:
            raise DomainValidationError(
                "supported absolute-effect calculations use RR, OR, RD, or HR"
            )
        if not 0 <= self.baseline_risk <= 1:
            raise DomainValidationError("baseline risk must be between zero and one")
        if self.display_scale <= 0:
            raise DomainValidationError("absolute-effect display scale must be positive")
        if (self.confidence_interval_lower is None) != (
            self.confidence_interval_upper is None
        ):
            raise DomainValidationError(
                "absolute-effect calculation requires both confidence limits"
            )


def _treated_risk(measure: str, baseline: float, effect: float) -> float:
    if measure == "RR":
        value = baseline * effect
    elif measure == "OR":
        value = effect * baseline / (1 - baseline + effect * baseline)
    elif measure == "RD":
        value = baseline + effect
    else:
        value = 1 - (1 - baseline) ** effect
    if not 0 <= value <= 1:
        raise DomainValidationError("derived intervention risk falls outside zero to one")
    return value


def _validate_absolute_effect_calculation(
    scenario: AbsoluteEffectScenario,
    calculation: AbsoluteEffectCalculation,
) -> None:
    effects = (
        scenario.comparator_effect,
        scenario.intervention_effect,
        scenario.absolute_difference,
    )
    if any(item.status is not EffectStatus.ESTIMATED for item in effects):
        raise DomainValidationError(
            "a calculated absolute-effect scenario requires three estimated effects"
        )
    baseline = calculation.baseline_risk * calculation.display_scale
    intervention_risk = _treated_risk(
        calculation.measure,
        calculation.baseline_risk,
        calculation.effect_estimate,
    )
    intervention = intervention_risk * calculation.display_scale
    difference = intervention - baseline
    tolerance = max(1e-9, calculation.display_scale * 1e-6)
    observed = (
        scenario.comparator_effect.estimate,
        scenario.intervention_effect.estimate,
        scenario.absolute_difference.estimate,
    )
    expected = (baseline, intervention, difference)
    if any(
        value is None or not isclose(value, target, abs_tol=tolerance, rel_tol=1e-9)
        for value, target in zip(observed, expected, strict=True)
    ):
        raise DomainValidationError(
            "absolute-effect values do not match the deterministic calculation"
        )


@dataclass(frozen=True, slots=True)
class GRADEMethodDecision:
    decision_id: str
    topic: str
    decision: str
    rationale: str
    protocol_alignment: ProtocolAlignment
    authoritative_sources: tuple[MethodologyReference, ...] = ()
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("decision_id", "topic", "decision", "rationale"):
            object.__setattr__(
                self,
                field_name,
                require_text(getattr(self, field_name), field_name),
            )
        if (
            self.protocol_alignment is not ProtocolAlignment.FOLLOWED
            and not self.authoritative_sources
        ):
            raise DomainValidationError(
                "supplemented or deviated method decision requires authority"
            )


@dataclass(frozen=True, slots=True)
class GRADEDomainJudgement:
    domain: GRADEDomain
    concern: GRADEConcern
    downgrade_levels: int
    explanation: str
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "explanation", require_text(self.explanation, "explanation")
        )
        expected = {
            GRADEConcern.NOT_SERIOUS: 0,
            GRADEConcern.SERIOUS: 1,
            GRADEConcern.VERY_SERIOUS: 2,
            GRADEConcern.EXTREMELY_SERIOUS: 3,
        }[self.concern]
        if self.downgrade_levels != expected:
            raise DomainValidationError(
                "downgrade levels must agree with the GRADE concern"
            )


@dataclass(frozen=True, slots=True)
class GRADEUpgradeAssessment:
    domain: GRADEUpgradeDomain
    judgement: GRADEUpgradeJudgement
    upgrade_levels: int
    explanation: str
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "explanation", require_text(self.explanation, "explanation")
        )
        if self.judgement is GRADEUpgradeJudgement.PRESENT:
            if self.upgrade_levels not in (1, 2):
                raise DomainValidationError("present upgrade must add one or two levels")
            if not self.provenance:
                raise DomainValidationError("present upgrade requires provenance")
        elif self.upgrade_levels != 0:
            raise DomainValidationError("absent upgrade cannot add certainty levels")


@dataclass(frozen=True, slots=True)
class GradedGRADEAssessmentDraft:
    evidence_body_id: str
    synthesis_analysis_ids: tuple[str, ...]
    status: Literal[EvidenceProfileStatus.GRADED]
    initial_certainty: Certainty
    initial_certainty_basis: str
    domains: tuple[GRADEDomainJudgement, ...]
    upgrades: tuple[GRADEUpgradeAssessment, ...]
    explanation: str
    issues: tuple[ArtifactIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_body_id",
            require_text(self.evidence_body_id, "evidence_body_id"),
        )
        object.__setattr__(
            self,
            "synthesis_analysis_ids",
            require_unique(
                self.synthesis_analysis_ids,
                "GRADE synthesis analysis ids",
            ),
        )
        object.__setattr__(
            self,
            "initial_certainty_basis",
            require_text(self.initial_certainty_basis, "initial_certainty_basis"),
        )
        object.__setattr__(
            self, "explanation", require_text(self.explanation, "explanation")
        )
        if not self.synthesis_analysis_ids:
            raise DomainValidationError(
                "graded profile requires at least one Synthesis Analysis reference"
            )
        assessed = {item.domain for item in self.domains}
        if assessed != set(GRADEDomain) or len(self.domains) != len(assessed):
            raise DomainValidationError(
                "graded profile requires five unique downgrade domains"
            )
        upgraded = {item.domain for item in self.upgrades}
        if upgraded != set(GRADEUpgradeDomain) or len(self.upgrades) != len(upgraded):
            raise DomainValidationError(
                "graded profile requires three unique upgrade assessments"
            )
        applied_upgrades = sum(item.upgrade_levels for item in self.upgrades)
        applied_downgrades = sum(item.downgrade_levels for item in self.domains)
        if applied_upgrades and (
            self.initial_certainty is not Certainty.LOW or applied_downgrades
        ):
            raise DomainValidationError(
                "GRADE upgrading applies only to low-certainty evidence "
                "with no reasons to downgrade"
            )


@dataclass(frozen=True, slots=True)
class NoEvidenceGRADEProfileDraft:
    evidence_body_id: str
    status: Literal[EvidenceProfileStatus.NO_EVIDENCE]
    explanation: str
    provenance: tuple[Provenance, ...] = ()
    issues: tuple[ArtifactIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_body_id",
            require_text(self.evidence_body_id, "evidence_body_id"),
        )
        object.__setattr__(
            self, "explanation", require_text(self.explanation, "explanation")
        )


GRADEAssessmentDraft = GradedGRADEAssessmentDraft | NoEvidenceGRADEProfileDraft


@dataclass(frozen=True, slots=True)
class GradedGRADEAssessment:
    evidence_body_id: str
    synthesis_analysis_ids: tuple[str, ...]
    status: Literal[EvidenceProfileStatus.GRADED]
    initial_certainty: Certainty
    initial_certainty_basis: str
    domains: tuple[GRADEDomainJudgement, ...]
    upgrades: tuple[GRADEUpgradeAssessment, ...]
    final_certainty: Certainty
    explanation: str
    issues: tuple[ArtifactIssue, ...] = ()

    def __post_init__(self) -> None:
        draft = GradedGRADEAssessmentDraft(
            evidence_body_id=self.evidence_body_id,
            synthesis_analysis_ids=self.synthesis_analysis_ids,
            status=self.status,
            initial_certainty=self.initial_certainty,
            initial_certainty_basis=self.initial_certainty_basis,
            domains=self.domains,
            upgrades=self.upgrades,
            explanation=self.explanation,
            issues=self.issues,
        )
        if calculated_certainty(draft) is not self.final_certainty:
            raise DomainValidationError(
                "final certainty does not match recorded downgrade and upgrade levels"
            )


@dataclass(frozen=True, slots=True)
class NoEvidenceGRADEProfile:
    evidence_body_id: str
    status: Literal[EvidenceProfileStatus.NO_EVIDENCE]
    explanation: str
    provenance: tuple[Provenance, ...] = ()
    issues: tuple[ArtifactIssue, ...] = ()

    def __post_init__(self) -> None:
        NoEvidenceGRADEProfileDraft(
            evidence_body_id=self.evidence_body_id,
            status=self.status,
            explanation=self.explanation,
            provenance=self.provenance,
            issues=self.issues,
        )


GRADEAssessment = GradedGRADEAssessment | NoEvidenceGRADEProfile


@dataclass(frozen=True, slots=True)
class SummaryOfFindingsRow:
    evidence_body_id: str
    outcome: str
    time_frame: str
    relative_effect: EffectPresentation | None
    absolute_effects: tuple[AbsoluteEffectScenario, ...]
    study_count: int
    participant_count: int | None
    certainty: Certainty | None
    explanation: str
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("evidence_body_id", "outcome", "time_frame", "explanation"):
            object.__setattr__(
                self,
                field_name,
                require_text(getattr(self, field_name), field_name),
            )
        if self.study_count < 0:
            raise DomainValidationError("study_count must be non-negative")
        if self.participant_count is not None and self.participant_count < 0:
            raise DomainValidationError("participant_count must be non-negative")
        if self.study_count == 0 and self.certainty is not None:
            raise DomainValidationError("no-evidence row must not state certainty")


@dataclass(frozen=True, slots=True)
class SummaryOfFindingsRowDraft:
    evidence_body_id: str
    outcome: str
    time_frame: str
    relative_effect: EffectPresentation | None
    absolute_effects: tuple[AbsoluteEffectScenario, ...]
    study_count: int
    participant_count: int | None
    explanation: str
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("evidence_body_id", "outcome", "time_frame", "explanation"):
            object.__setattr__(
                self,
                field_name,
                require_text(getattr(self, field_name), field_name),
            )
        if self.study_count < 0:
            raise DomainValidationError("study_count must be non-negative")
        if self.participant_count is not None and self.participant_count < 0:
            raise DomainValidationError("participant_count must be non-negative")


@dataclass(frozen=True, slots=True)
class SummaryOfFindingsTableDraft:
    table_id: str
    population: str
    setting: str | None
    intervention: str
    comparison: str
    rows: tuple[SummaryOfFindingsRowDraft, ...]

    def __post_init__(self) -> None:
        for field_name in ("table_id", "population", "intervention", "comparison"):
            object.__setattr__(
                self,
                field_name,
                require_text(getattr(self, field_name), field_name),
            )
        if len(self.rows) > 7:
            raise DomainValidationError("SoF table must contain at most seven outcomes")
        ids = tuple(row.evidence_body_id for row in self.rows)
        if len(ids) != len(set(ids)):
            raise DomainValidationError("SoF table evidence bodies must be unique")


@dataclass(frozen=True, slots=True)
class SummaryOfFindingsTable:
    table_id: str
    population: str
    setting: str | None
    intervention: str
    comparison: str
    rows: tuple[SummaryOfFindingsRow, ...]

    def __post_init__(self) -> None:
        for field_name in ("table_id", "population", "intervention", "comparison"):
            object.__setattr__(
                self,
                field_name,
                require_text(getattr(self, field_name), field_name),
            )
        if not self.rows or len(self.rows) > 7:
            raise DomainValidationError("SoF table must contain one to seven outcomes")
        ids = tuple(row.evidence_body_id for row in self.rows)
        if len(ids) != len(set(ids)):
            raise DomainValidationError("SoF table evidence bodies must be unique")


@dataclass(frozen=True, slots=True)
class SummaryOfFindingsDocument:
    method_decisions: tuple[GRADEMethodDecision, ...]
    tables: tuple[SummaryOfFindingsTable, ...]

    def __post_init__(self) -> None:
        if not self.tables:
            raise DomainValidationError("at least one SoF table is required")
        decision_ids = tuple(item.decision_id for item in self.method_decisions)
        if len(decision_ids) != len(set(decision_ids)):
            raise DomainValidationError("GRADE method decision ids must be unique")


@dataclass(frozen=True, slots=True)
class GradeSummaryOfFindingsDraft:
    schema_version: Literal["grade-sof-draft.v4"]
    method_decisions: tuple[GRADEMethodDecision, ...] = ()
    evidence_profiles: tuple[GRADEAssessmentDraft, ...] = ()
    summary_of_findings: tuple[SummaryOfFindingsTableDraft, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != "grade-sof-draft.v4":
            raise DomainValidationError("GRADE requires grade-sof-draft.v4")
        decision_ids = tuple(item.decision_id for item in self.method_decisions)
        if len(decision_ids) != len(set(decision_ids)):
            raise DomainValidationError("GRADE method decision ids must be unique")
        profile_ids = tuple(item.evidence_body_id for item in self.evidence_profiles)
        if len(profile_ids) != len(set(profile_ids)):
            raise DomainValidationError("evidence profile ids must be unique")
        table_ids = tuple(item.table_id for item in self.summary_of_findings)
        if len(table_ids) != len(set(table_ids)):
            raise DomainValidationError("Summary of Findings table ids must be unique")
        row_ids = tuple(
            row.evidence_body_id
            for table in self.summary_of_findings
            for row in table.rows
        )
        if len(row_ids) != len(set(row_ids)):
            raise DomainValidationError(
                "evidence body must not appear in more than one SoF row"
            )


@dataclass(frozen=True, slots=True)
class GradeSummaryOfFindingsArtifact:
    method_decisions: tuple[GRADEMethodDecision, ...]
    evidence_profiles: tuple[GRADEAssessment, ...]
    summary_of_findings: tuple[SummaryOfFindingsTable, ...]


@dataclass(frozen=True, slots=True)
class GradeSummaryOfFindingsInput:
    protocol: GradeProtocol
    evidence_package: GradeEvidencePackageRef


_CERTAINTY_SCORE = {
    Certainty.VERY_LOW: 0,
    Certainty.LOW: 1,
    Certainty.MODERATE: 2,
    Certainty.HIGH: 3,
}


def calculated_certainty(
    assessment: GradedGRADEAssessment | GradedGRADEAssessmentDraft,
) -> Certainty:
    score = _CERTAINTY_SCORE[assessment.initial_certainty]
    score -= sum(item.downgrade_levels for item in assessment.domains)
    score += sum(item.upgrade_levels for item in assessment.upgrades)
    score = min(3, max(0, score))
    return tuple(Certainty)[3 - score]


def finalize_grade_artifact(
    draft: GradeSummaryOfFindingsDraft,
    *,
    known_synthesis_analysis_ids: frozenset[str] | None = None,
) -> GradeSummaryOfFindingsArtifact:
    """Derive mechanical certainty fields and enforce artifact relationships."""
    if not draft.evidence_profiles:
        raise DomainValidationError("completed GRADE artifact requires evidence profiles")
    if not draft.summary_of_findings:
        raise DomainValidationError("completed GRADE artifact requires SoF tables")

    profiles: list[GRADEAssessment] = []
    for item in draft.evidence_profiles:
        if isinstance(item, NoEvidenceGRADEProfileDraft):
            profiles.append(
                NoEvidenceGRADEProfile(
                    evidence_body_id=item.evidence_body_id,
                    status=item.status,
                    explanation=item.explanation,
                    provenance=item.provenance,
                    issues=item.issues,
                )
            )
            continue
        profiles.append(
            GradedGRADEAssessment(
                evidence_body_id=item.evidence_body_id,
                synthesis_analysis_ids=item.synthesis_analysis_ids,
                status=item.status,
                initial_certainty=item.initial_certainty,
                initial_certainty_basis=item.initial_certainty_basis,
                domains=item.domains,
                upgrades=item.upgrades,
                final_certainty=calculated_certainty(item),
                explanation=item.explanation,
                issues=item.issues,
            )
        )
    finalized_profiles = tuple(profiles)
    profiles_by_id = {item.evidence_body_id: item for item in finalized_profiles}
    observed_row_ids: list[str] = []
    tables: list[SummaryOfFindingsTable] = []
    for table in draft.summary_of_findings:
        rows: list[SummaryOfFindingsRow] = []
        for row in table.rows:
            profile = profiles_by_id.get(row.evidence_body_id)
            if profile is None:
                raise DomainValidationError("SoF row has no evidence profile")
            if isinstance(profile, NoEvidenceGRADEProfile):
                if (
                    row.study_count != 0
                    or row.participant_count is not None
                    or row.relative_effect is not None
                    or row.absolute_effects
                ):
                    raise DomainValidationError(
                        "no-evidence SoF row cannot report contributing evidence"
                    )
            elif row.study_count == 0:
                raise DomainValidationError(
                    "graded SoF row requires at least one contributing Study"
                )
            if (
                known_synthesis_analysis_ids is not None
                and isinstance(profile, GradedGRADEAssessment)
            ):
                unknown = (
                    set(profile.synthesis_analysis_ids)
                    - known_synthesis_analysis_ids
                )
                if unknown:
                    raise DomainValidationError(
                        "GRADE profile references an unknown Synthesis Analysis"
                    )
            observed_row_ids.append(row.evidence_body_id)
            rows.append(
                SummaryOfFindingsRow(
                    evidence_body_id=row.evidence_body_id,
                    outcome=row.outcome,
                    time_frame=row.time_frame,
                    relative_effect=row.relative_effect,
                    absolute_effects=row.absolute_effects,
                    study_count=row.study_count,
                    participant_count=row.participant_count,
                    certainty=(
                        profile.final_certainty
                        if isinstance(profile, GradedGRADEAssessment)
                        else None
                    ),
                    explanation=row.explanation,
                    provenance=row.provenance,
                )
            )
        tables.append(
            SummaryOfFindingsTable(
                table_id=table.table_id,
                population=table.population,
                setting=table.setting,
                intervention=table.intervention,
                comparison=table.comparison,
                rows=tuple(rows),
            )
        )
    if set(observed_row_ids) != set(profiles_by_id):
        raise DomainValidationError(
            "every evidence profile must appear exactly once in a SoF table"
        )
    return GradeSummaryOfFindingsArtifact(
        draft.method_decisions,
        finalized_profiles,
        tuple(tables),
    )
