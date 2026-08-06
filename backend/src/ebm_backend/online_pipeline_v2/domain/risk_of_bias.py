"""Adaptive, result-linked Risk of Bias task contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import (
    CompletedArtifactRef,
    DomainValidationError,
    Provenance,
    require_text,
)
from .protocol import ProtocolDraft
from .selection import StudySelectionArtifact


NonBlank = Annotated[str, Field(min_length=1)]


class RiskOfBiasBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: NonBlank
    protocol_version: NonBlank
    complete_protocol_digest: NonBlank
    study_data_protocol_projection_digest: NonBlank
    selection_package_id: NonBlank
    selection_package_digest: NonBlank
    study_data_collection_artifact_id: NonBlank
    study_data_collection_digest: NonBlank


class RiskOfBiasMethodDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: NonBlank
    topic: NonBlank
    decision: NonBlank
    rationale: NonBlank
    authority_source_ids: tuple[NonBlank, ...] = ()


class RiskOfBiasMethodUse(BaseModel):
    """One standard/version/variant actually applied by the Agent."""

    model_config = ConfigDict(extra="forbid")

    method_use_id: NonBlank
    planned_standard: NonBlank | None
    applied_standard: NonBlank
    applied_version: NonBlank
    applied_variant: NonBlank | None = None
    applicability: NonBlank
    authoritative_sources: tuple[Provenance, ...] = ()
    basis_status: Literal["verified", "llm_fallback"] | None = None
    fallback_model: str | None = None
    fallback_note: str | None = None
    decisions: tuple[RiskOfBiasMethodDecision, ...] = ()
    protocol_conflict: str | None = None

    @model_validator(mode="after")
    def validate_method_use(self) -> "RiskOfBiasMethodUse":
        source_ids = {item.source_id for item in self.authoritative_sources}
        decision_ids = [item.decision_id for item in self.decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("method decision ids must be unique")
        if self.basis_status == "verified" and not self.authoritative_sources:
            raise ValueError("verified Risk of Bias method requires an authority")
        if self.basis_status == "llm_fallback":
            if not self.fallback_model or not self.fallback_note:
                raise ValueError(
                    "Risk of Bias methodology fallback requires model and note"
                )
        elif self.fallback_model is not None or self.fallback_note is not None:
            raise ValueError("fallback metadata requires llm_fallback methodology")
        if self.basis_status == "verified":
            for decision in self.decisions:
                if not set(decision.authority_source_ids).issubset(source_ids):
                    raise ValueError("method decision references an unknown authority")
        if self.protocol_conflict is not None and not self.protocol_conflict.strip():
            raise ValueError("protocol_conflict must be non-blank when supplied")
        return self


class RiskOfBiasTarget(BaseModel):
    """A Protocol-relevant result or result set selected for assessment."""

    model_config = ConfigDict(extra="forbid")

    target_id: NonBlank
    study_id: NonBlank
    study_result_ids: tuple[NonBlank, ...] = Field(min_length=1)
    method_use_id: NonBlank
    outcome_id: NonBlank | None = None
    outcome_name: NonBlank
    outcome_measurement: NonBlank
    timepoint: NonBlank
    comparison: NonBlank
    effect_of_interest: NonBlank
    analysis: NonBlank
    selection_rationale: NonBlank
    provenance: tuple[Provenance, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_result_ids(self) -> "RiskOfBiasTarget":
        if len(self.study_result_ids) != len(set(self.study_result_ids)):
            raise ValueError("target Study Result ids must be unique")
        return self


class RiskOfBiasEvidenceObservation(BaseModel):
    """Scientific evidence actually inspected; route diagnostics stay outside it."""

    model_config = ConfigDict(extra="forbid")

    observation_id: NonBlank
    study_id: NonBlank
    upstream_report_id: NonBlank | None = None
    source_kind: NonBlank
    source_identity: NonBlank
    locator: NonBlank
    observed_at: NonBlank
    read_scope: tuple[NonBlank, ...] = Field(min_length=1)
    observation: NonBlank
    limitations: tuple[NonBlank, ...] = ()
    provenance: tuple[Provenance, ...] = Field(min_length=1)


class RiskOfBiasAssessmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: NonBlank
    label: NonBlank
    response: NonBlank
    support: NonBlank
    evidence_observation_ids: tuple[NonBlank, ...] = ()
    provenance: tuple[Provenance, ...] = Field(min_length=1)


class RiskOfBiasAssessmentSection(BaseModel):
    """An open standard-native preliminary, triage, or context section."""

    model_config = ConfigDict(extra="forbid")

    section_id: NonBlank
    section_name: NonBlank
    items: tuple[RiskOfBiasAssessmentItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_items(self) -> "RiskOfBiasAssessmentSection":
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("assessment section item ids must be unique")
        return self


class RiskOfBiasSignallingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: NonBlank
    question: NonBlank
    response: NonBlank
    support: NonBlank
    evidence_observation_ids: tuple[NonBlank, ...] = ()
    provenance: tuple[Provenance, ...] = Field(min_length=1)


class RiskOfBiasDomainAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: NonBlank
    domain_name: NonBlank
    applicability: NonBlank | None = None
    signalling_responses: tuple[RiskOfBiasSignallingResponse, ...] = ()
    proposed_judgement: NonBlank | None = None
    judgement: NonBlank
    override_rationale: NonBlank | None = None
    support: NonBlank
    bias_direction: NonBlank | None = None
    evidence_observation_ids: tuple[NonBlank, ...] = ()
    provenance: tuple[Provenance, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_questions(self) -> "RiskOfBiasDomainAssessment":
        ids = [item.question_id for item in self.signalling_responses]
        if len(ids) != len(set(ids)):
            raise ValueError("domain signalling question ids must be unique")
        return self


class OverallRiskOfBiasJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposed_judgement: NonBlank | None = None
    judgement: NonBlank
    override_rationale: NonBlank | None = None
    rule: NonBlank
    support: NonBlank
    evidence_observation_ids: tuple[NonBlank, ...] = ()
    provenance: tuple[Provenance, ...] = Field(min_length=1)


class RiskOfBiasAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: NonBlank
    study_id: NonBlank
    target_id: NonBlank
    method_use_id: NonBlank
    pre_assessment_sections: tuple[RiskOfBiasAssessmentSection, ...] = ()
    domains: tuple[RiskOfBiasDomainAssessment, ...] = Field(min_length=1)
    overall: OverallRiskOfBiasJudgement | None = None
    limitations: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def validate_sections_and_domains(self) -> "RiskOfBiasAssessment":
        section_ids = [item.section_id for item in self.pre_assessment_sections]
        domain_ids = [item.domain_id for item in self.domains]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("pre-assessment section ids must be unique")
        if len(domain_ids) != len(set(domain_ids)):
            raise ValueError("assessment domain ids must be unique")
        return self


class RiskOfBiasUnassessedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: NonBlank
    study_result_id: NonBlank | None = None
    description: NonBlank
    reason: NonBlank


class RiskOfBiasCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: NonBlank
    assessed_target_ids: tuple[NonBlank, ...]
    unassessed_results: tuple[RiskOfBiasUnassessedResult, ...] = ()
    rationale: NonBlank


class RiskOfBiasDocumentV4(BaseModel):
    """The single authoritative Agent-authored scientific artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["risk-of-bias-document.v4"]
    binding: RiskOfBiasBinding
    method_uses: tuple[RiskOfBiasMethodUse, ...] = Field(min_length=1)
    targets: tuple[RiskOfBiasTarget, ...] = ()
    assessments: tuple[RiskOfBiasAssessment, ...] = ()
    evidence_observations: tuple[RiskOfBiasEvidenceObservation, ...] = ()
    coverage: RiskOfBiasCoverage

    @model_validator(mode="after")
    def validate_references(self) -> "RiskOfBiasDocumentV4":
        method_ids = [item.method_use_id for item in self.method_uses]
        target_ids = [item.target_id for item in self.targets]
        assessment_ids = [item.assessment_id for item in self.assessments]
        observation_ids = [item.observation_id for item in self.evidence_observations]
        for values, label in (
            (method_ids, "method use"),
            (target_ids, "target"),
            (assessment_ids, "assessment"),
            (observation_ids, "evidence observation"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} ids must be unique")
        method_set = set(method_ids)
        target_by_id = {item.target_id: item for item in self.targets}
        observation_set = set(observation_ids)
        assessment_targets: list[str] = []
        for target in self.targets:
            if target.method_use_id not in method_set:
                raise ValueError("target references an unknown method use")
        for assessment in self.assessments:
            target = target_by_id.get(assessment.target_id)
            if target is None:
                raise ValueError("assessment references an unknown target")
            if assessment.study_id != target.study_id:
                raise ValueError("assessment Study does not match its target")
            if assessment.method_use_id != target.method_use_id:
                raise ValueError("assessment method does not match its target")
            assessment_targets.append(assessment.target_id)
            for item in assessment.pre_assessment_sections:
                for field in item.items:
                    _require_observations(field.evidence_observation_ids, observation_set)
            for domain in assessment.domains:
                _require_observations(domain.evidence_observation_ids, observation_set)
                for response in domain.signalling_responses:
                    _require_observations(
                        response.evidence_observation_ids,
                        observation_set,
                    )
            if assessment.overall is not None:
                _require_observations(
                    assessment.overall.evidence_observation_ids,
                    observation_set,
                )
        if len(assessment_targets) != len(set(assessment_targets)):
            raise ValueError("each target may have only one assessment")
        if set(assessment_targets) != set(target_ids):
            raise ValueError("every target requires exactly one assessment")
        if len(self.coverage.assessed_target_ids) != len(
            set(self.coverage.assessed_target_ids)
        ):
            raise ValueError("coverage target ids must be unique")
        if set(self.coverage.assessed_target_ids) != set(target_ids):
            raise ValueError("coverage assessed targets must match document targets")
        if not target_ids and not self.coverage.unassessed_results:
            raise ValueError(
                "a document without applicable targets requires explicit "
                "unassessed coverage"
            )
        return self


def _require_observations(values: tuple[str, ...], known: set[str]) -> None:
    if not set(values).issubset(known):
        raise ValueError("assessment evidence references an unknown observation")


@dataclass(frozen=True, slots=True)
class RiskOfBiasPackageRef:
    package_id: str
    review_id: str
    protocol_version: str
    schema_version: str
    content_digest: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"package_ref.{name}"),
            )
        if self.schema_version != "risk-of-bias-package.v4":
            raise DomainValidationError("Risk of Bias requires risk-of-bias-package.v4")


@dataclass(frozen=True, slots=True)
class RiskOfBiasSummary:
    method_use_count: int
    target_count: int
    assessment_count: int
    evidence_observation_count: int
    unassessed_result_count: int
    issue_count: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")
        if self.target_count != self.assessment_count:
            raise DomainValidationError("each RoB target requires one assessment")


@dataclass(frozen=True, slots=True)
class RiskOfBiasReviewProcess:
    agent_run_id: str
    human_independent_review_satisfied: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "agent_run_id",
            require_text(self.agent_run_id, "review_process.agent_run_id"),
        )
        if self.human_independent_review_satisfied:
            raise DomainValidationError(
                "single Agent Risk of Bias cannot claim human independent review"
            )


@dataclass(frozen=True, slots=True)
class RiskOfBiasArtifact:
    package_ref: RiskOfBiasPackageRef
    document: RiskOfBiasDocumentV4
    summary: RiskOfBiasSummary
    review_process: RiskOfBiasReviewProcess


@dataclass(frozen=True, slots=True)
class RiskOfBiasInput:
    protocol: ProtocolDraft
    selection: StudySelectionArtifact
    study_data_collection: CompletedArtifactRef
