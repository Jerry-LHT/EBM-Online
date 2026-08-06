"""Public contract for resumable Evidence Synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import (
    CompletedArtifactRef,
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
from .risk_of_bias import RiskOfBiasArtifact


# GRADE consumes the completed synthesis bundle reference, never its private
# working ledger. Keep this task-specific name at that boundary.
EvidenceSynthesisArtifact = CompletedArtifactRef


class SynthesisRiskOfBiasScope(StrEnum):
    STUDY = "study"
    OUTCOME = "outcome"
    RESULT = "result"


class SynthesisRiskOfBiasSourceStatus(StrEnum):
    AVAILABLE = "available"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SynthesisRiskOfBiasDomain:
    name: str
    judgement: str | None
    support: str | None
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_text(self.name, "RoB domain name"))
        for field_name in ("judgement", "support"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    require_text(value, f"RoB domain {field_name}"),
                )
        if not self.provenance:
            raise DomainValidationError("RoB domain requires provenance")


@dataclass(frozen=True, slots=True)
class SynthesisRiskOfBiasAssessment:
    assessment_id: str
    study_id: str
    scope: SynthesisRiskOfBiasScope
    domains: tuple[SynthesisRiskOfBiasDomain, ...]
    provenance: tuple[Provenance, ...]
    outcome: str | None = None
    data_type: str | None = None
    effect_measure: str | None = None
    time_point: str | None = None
    result_ids: tuple[str, ...] = ()
    applied_standard: str | None = None
    applied_version: str | None = None
    overall_judgement: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("assessment_id", "study_id"):
            object.__setattr__(
                self,
                field_name,
                require_text(getattr(self, field_name), f"RoB {field_name}"),
            )
        if not isinstance(self.scope, SynthesisRiskOfBiasScope):
            raise DomainValidationError("RoB assessment scope is invalid")
        for field_name in (
            "outcome",
            "data_type",
            "effect_measure",
            "time_point",
            "applied_standard",
            "applied_version",
            "overall_judgement",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    require_text(value, f"RoB assessment {field_name}"),
                )
        object.__setattr__(
            self,
            "result_ids",
            require_unique(self.result_ids, "RoB assessment result ids"),
        )
        if not self.domains:
            raise DomainValidationError("RoB assessment requires at least one domain")
        require_unique(
            tuple(domain.name for domain in self.domains),
            "RoB assessment domain names",
        )
        if not self.provenance:
            raise DomainValidationError("RoB assessment requires provenance")


@dataclass(frozen=True, slots=True)
class SynthesisRiskOfBiasUnassessedResult:
    study_id: str
    description: str
    reason: str
    study_result_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("study_id", "description", "reason"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"RoB coverage {name}"),
            )
        if self.study_result_id is not None:
            object.__setattr__(
                self,
                "study_result_id",
                require_text(self.study_result_id, "RoB coverage study_result_id"),
            )


@dataclass(frozen=True, slots=True)
class SynthesisRiskOfBiasStudy:
    study_id: str
    source_status: SynthesisRiskOfBiasSourceStatus
    assessments: tuple[SynthesisRiskOfBiasAssessment, ...]
    unassessed_results: tuple[SynthesisRiskOfBiasUnassessedResult, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "study_id",
            require_text(self.study_id, "RoB Study id"),
        )
        if not isinstance(self.source_status, SynthesisRiskOfBiasSourceStatus):
            raise DomainValidationError("RoB Study source status is invalid")
        require_unique(
            tuple(item.assessment_id for item in self.assessments),
            "RoB assessment ids",
        )
        if any(item.study_id != self.study_id for item in self.assessments):
            raise DomainValidationError(
                "RoB assessment Study id does not match its Study container"
            )
        if any(item.study_id != self.study_id for item in self.unassessed_results):
            raise DomainValidationError(
                "RoB unassessed Result Study id does not match its Study container"
            )
        if (
            self.source_status is not SynthesisRiskOfBiasSourceStatus.AVAILABLE
            and self.assessments
        ):
            raise DomainValidationError(
                "empty or unavailable RoB Study cannot contain assessments"
            )


@dataclass(frozen=True, slots=True)
class SynthesisRiskOfBiasEvidence:
    studies: tuple[SynthesisRiskOfBiasStudy, ...]
    provenance: tuple[Provenance, ...]
    coverage_scope: str | None = None
    coverage_rationale: str | None = None
    schema_version: str = "synthesis-risk-of-bias-evidence.v2"

    def __post_init__(self) -> None:
        if self.schema_version != "synthesis-risk-of-bias-evidence.v2":
            raise DomainValidationError(
                "Evidence Synthesis requires synthesis-risk-of-bias-evidence.v2"
            )
        require_unique(
            tuple(study.study_id for study in self.studies),
            "RoB evidence Study ids",
        )
        if not self.provenance:
            raise DomainValidationError("RoB evidence requires provenance")
        for name in ("coverage_scope", "coverage_rationale"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    require_text(value, f"RoB evidence {name}"),
                )


@dataclass(frozen=True, slots=True)
class EvidenceSynthesisProtocolBlock:
    heading: str
    text: str

    def __post_init__(self) -> None:
        for name in ("heading", "text"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"synthesis_protocol.{name}"),
            )


@dataclass(frozen=True, slots=True)
class EvidenceSynthesisProtocol:
    """Protocol content needed to decide and execute syntheses.

    Structured fields are optional navigation aids, not execution gates.
    ``source_material`` preserves supplied narrative or mixed-format Protocol
    content without requiring deterministic professional interpretation.
    """

    version: str
    review_question: str | None = None
    review_pico: PICO | None = None
    objectives: tuple[str, ...] = ()
    eligibility_and_outcomes: tuple[EvidenceSynthesisProtocolBlock, ...] = ()
    effect_calculation: tuple[EvidenceSynthesisProtocolBlock, ...] = ()
    risk_of_bias: tuple[EvidenceSynthesisProtocolBlock, ...] = ()
    synthesis: tuple[EvidenceSynthesisProtocolBlock, ...] = ()
    reporting_bias: tuple[EvidenceSynthesisProtocolBlock, ...] = ()
    synthesis_picos: tuple[SynthesisPICO, ...] = ()
    methodology_basis: tuple[MethodologyReference, ...] = ()
    methodology_basis_status: MethodologyBasisStatus = MethodologyBasisStatus.VERIFIED
    methodology_fallback_model: str | None = None
    methodology_fallback_note: str | None = None
    source_material: tuple[EvidenceSynthesisProtocolBlock, ...] = ()
    schema_version: str = "evidence-synthesis-protocol.v2"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            require_text(self.version, "synthesis_protocol.version"),
        )
        if self.review_question is not None:
            object.__setattr__(
                self,
                "review_question",
                require_text(
                    self.review_question,
                    "synthesis_protocol.review_question",
                ),
            )
        if self.review_pico is not None and not isinstance(self.review_pico, PICO):
            raise DomainValidationError("synthesis_protocol.review_pico is invalid")
        object.__setattr__(
            self,
            "objectives",
            require_unique(self.objectives, "synthesis_protocol.objectives"),
        )
        if self.schema_version != "evidence-synthesis-protocol.v2":
            raise DomainValidationError(
                "Evidence Synthesis requires evidence-synthesis-protocol.v2"
            )


def evidence_synthesis_protocol_from_draft(
    protocol: ProtocolDraft,
) -> EvidenceSynthesisProtocol:
    """Project the complete Protocol content needed to execute synthesis."""

    eligibility = protocol.methods.eligibility
    outcomes = protocol.methods.outcomes.outcomes
    analysis = protocol.methods.analysis
    synthesis = protocol.methods.synthesis
    eligibility_blocks = (
        _eligibility_block("Types of studies", eligibility.types_of_studies),
        _eligibility_block(
            "Types of participants",
            eligibility.types_of_participants,
        ),
        _eligibility_block(
            "Types of interventions",
            eligibility.types_of_interventions,
        ),
        _eligibility_block("Comparators", eligibility.comparators),
    )
    outcome_blocks = tuple(
        EvidenceSynthesisProtocolBlock(
            heading=f"{outcome.role.value.title()} outcome: {outcome.name}",
            text="\n".join(
                (
                    outcome.definition,
                    f"Measurement: {outcome.measurement}",
                    f"Time points: {', '.join(outcome.time_points)}",
                )
            ),
        )
        for outcome in outcomes
    )
    comparison_blocks = tuple(
        EvidenceSynthesisProtocolBlock(
            heading=f"Synthesis PICO {number}",
            text="\n".join(
                (
                    "Population: " + "; ".join(item.population),
                    "Intervention: " + "; ".join(item.intervention),
                    "Comparator: " + "; ".join(item.comparator),
                    "Outcomes: " + "; ".join(item.outcomes),
                    "Time frames: " + "; ".join(item.time_frames),
                    "Study designs: " + "; ".join(item.study_designs),
                    "Grouping rules: " + "; ".join(item.grouping_rules),
                )
            ),
        )
        for number, item in enumerate(synthesis.comparisons, start=1)
    )
    return EvidenceSynthesisProtocol(
        version=protocol.version,
        review_question=protocol.review_question,
        review_pico=protocol.review_pico,
        objectives=protocol.objectives,
        eligibility_and_outcomes=eligibility_blocks + outcome_blocks,
        effect_calculation=(
            EvidenceSynthesisProtocolBlock(
                "Measures of treatment effect",
                "\n".join(
                    f"{item.result_type}: {item.effect_measure}"
                    for item in analysis.effect_measures
                ),
            ),
            EvidenceSynthesisProtocolBlock(
                "Unit of analysis issues",
                analysis.unit_of_analysis,
            ),
            EvidenceSynthesisProtocolBlock(
                "Dealing with missing data",
                analysis.missing_data,
            ),
            EvidenceSynthesisProtocolBlock(
                "Assessment of heterogeneity",
                analysis.heterogeneity,
            ),
        ),
        risk_of_bias=(
            EvidenceSynthesisProtocolBlock(
                "Risk of bias standard",
                protocol.methods.risk_of_bias.tool,
            ),
            EvidenceSynthesisProtocolBlock(
                "Use of risk of bias in synthesis",
                protocol.methods.risk_of_bias.use_in_synthesis,
            ),
        ),
        synthesis=comparison_blocks
        + (
            EvidenceSynthesisProtocolBlock(
                "Quantitative synthesis criteria",
                synthesis.quantitative_synthesis_criteria,
            ),
            EvidenceSynthesisProtocolBlock(
                "Meta-analysis methods",
                synthesis.meta_analysis_methods,
            ),
            EvidenceSynthesisProtocolBlock(
                "Synthesis without meta-analysis",
                synthesis.non_meta_synthesis,
            ),
            EvidenceSynthesisProtocolBlock(
                "Subgroup analyses",
                "\n".join(synthesis.subgroup_analyses) or "None planned.",
            ),
            EvidenceSynthesisProtocolBlock(
                "Sensitivity analyses",
                "\n".join(synthesis.sensitivity_analyses) or "None planned.",
            ),
        ),
        reporting_bias=(
            EvidenceSynthesisProtocolBlock(
                "Assessment of reporting bias and missing evidence",
                "\n".join(
                    (
                        protocol.methods.data_collection.missing_information,
                        analysis.reporting_bias,
                    )
                ),
            ),
        ),
        synthesis_picos=synthesis.comparisons,
        methodology_basis=protocol.methodology_basis,
        methodology_basis_status=protocol.methodology_profile.basis_status,
        methodology_fallback_model=protocol.methodology_profile.fallback_model,
        methodology_fallback_note=protocol.methodology_profile.fallback_note,
    )


@dataclass(frozen=True, slots=True)
class EvidenceSynthesisInput:
    protocol: EvidenceSynthesisProtocol
    study_data_collection: CompletedArtifactRef
    risk_of_bias: RiskOfBiasArtifact
    work_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.protocol, EvidenceSynthesisProtocol):
            raise DomainValidationError(
                "Evidence Synthesis requires an EvidenceSynthesisProtocol"
            )
        if self.study_data_collection.task.value != "study_data_collection":
            raise DomainValidationError(
                "Evidence Synthesis requires a Study Data Collection artifact"
            )
        if self.study_data_collection.schema_version != (
            "study-data-collection-artifact.v3"
        ):
            raise DomainValidationError(
                "Evidence Synthesis requires study-data-collection-artifact.v3"
            )
        if not isinstance(self.risk_of_bias, RiskOfBiasArtifact):
            raise DomainValidationError(
                "Evidence Synthesis requires a Risk of Bias artifact"
            )
        if self.work_id is not None:
            object.__setattr__(
                self,
                "work_id",
                require_text(self.work_id, "work_id"),
            )


def synthesis_risk_of_bias_from_artifact(
    artifact: RiskOfBiasArtifact,
) -> SynthesisRiskOfBiasEvidence:
    """Project the actual RoB tool output without replacing its semantics."""

    document = artifact.document
    targets = {item.target_id: item for item in document.targets}
    methods = {item.method_use_id: item for item in document.method_uses}
    grouped: dict[str, list[SynthesisRiskOfBiasAssessment]] = {}
    for assessment in document.assessments:
        target = targets[assessment.target_id]
        method = methods[assessment.method_use_id]
        grouped.setdefault(assessment.study_id, []).append(
            SynthesisRiskOfBiasAssessment(
                assessment_id=assessment.assessment_id,
                study_id=assessment.study_id,
                scope=SynthesisRiskOfBiasScope.RESULT,
                outcome=target.outcome_name,
                time_point=target.timepoint,
                effect_measure=target.analysis,
                result_ids=target.study_result_ids,
                applied_standard=method.applied_standard,
                applied_version=method.applied_version,
                overall_judgement=(
                    assessment.overall.judgement
                    if assessment.overall is not None
                    else None
                ),
                domains=tuple(
                    SynthesisRiskOfBiasDomain(
                        name=domain.domain_name,
                        judgement=domain.judgement,
                        support=domain.support,
                        provenance=domain.provenance,
                    )
                    for domain in assessment.domains
                ),
                provenance=target.provenance,
            )
        )
    unassessed: dict[str, list[SynthesisRiskOfBiasUnassessedResult]] = {}
    for item in document.coverage.unassessed_results:
        unassessed.setdefault(item.study_id, []).append(
            SynthesisRiskOfBiasUnassessedResult(
                study_id=item.study_id,
                study_result_id=item.study_result_id,
                description=item.description,
                reason=item.reason,
            )
        )
    study_ids = sorted(set(grouped) | set(unassessed))
    return SynthesisRiskOfBiasEvidence(
        studies=tuple(
            SynthesisRiskOfBiasStudy(
                study_id=study_id,
                source_status=(
                    SynthesisRiskOfBiasSourceStatus.AVAILABLE
                    if grouped.get(study_id)
                    else SynthesisRiskOfBiasSourceStatus.EMPTY
                ),
                assessments=tuple(grouped.get(study_id, ())),
                unassessed_results=tuple(unassessed.get(study_id, ())),
            )
            for study_id in study_ids
        ),
        provenance=(
            Provenance(
                source_id=artifact.package_ref.content_digest,
                source_type="risk_of_bias_artifact",
            ),
        ),
        coverage_scope=document.coverage.scope,
        coverage_rationale=document.coverage.rationale,
    )


def _eligibility_block(
    heading: str,
    section: object,
) -> EvidenceSynthesisProtocolBlock:
    parts = [require_text(getattr(section, "description"), heading)]
    parts.extend(
        f"Include: {value}" for value in getattr(section, "inclusion_criteria")
    )
    parts.extend(
        f"Exclude: {value}" for value in getattr(section, "exclusion_criteria")
    )
    return EvidenceSynthesisProtocolBlock(heading=heading, text="\n".join(parts))
