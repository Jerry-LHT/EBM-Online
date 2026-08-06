"""Q2Protocol domain types for a Cochrane-style intervention review draft."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Literal
from urllib.parse import urlparse

from .common import DomainValidationError, Provenance, require_text, require_unique


def _require_items(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = require_unique(values, field_name)
    if not normalized:
        raise DomainValidationError(f"{field_name} must not be empty")
    return normalized


class TopicKind(StrEnum):
    TITLE = "title"
    QUESTION = "question"


class ProtocolProfile(StrEnum):
    COCHRANE_INTERVENTION_V1 = "cochrane_intervention_v1"


class ProtocolReviewType(StrEnum):
    INTERVENTION = "intervention"


class ProtocolDocumentStatus(StrEnum):
    DRAFT = "draft"


class OutcomeRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class SearchSourceType(StrEnum):
    DATABASE = "database"
    TRIAL_REGISTRY = "trial_registry"
    OTHER_STRUCTURED = "other_structured"


class ProtocolSemanticSection(StrEnum):
    TITLE = "title"
    BACKGROUND = "background"
    REVIEW_QUESTION = "review_question"
    REVIEW_PICO = "review_pico"
    OBJECTIVES = "objectives"
    METHODS = "methods"
    METHODOLOGY = "methodology"
    ASSUMPTIONS = "assumptions"
    UNRESOLVED_QUESTIONS = "unresolved_questions"
    ADDITIONAL = "additional"


@dataclass(frozen=True, slots=True)
class ProtocolTemplateSection:
    section_id: str
    title: str
    semantic_section: ProtocolSemanticSection
    order: int
    required: bool

    def __post_init__(self) -> None:
        for name in ("section_id", "title"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"template_section.{name}"),
            )
        if self.order < 0:
            raise DomainValidationError(
                "template_section.order must be non-negative"
            )


@dataclass(frozen=True, slots=True)
class ProtocolTemplate:
    template_id: str
    version_or_revision: str
    review_type: ProtocolReviewType
    language: str
    tense: str
    sections: tuple[ProtocolTemplateSection, ...]

    def __post_init__(self) -> None:
        for name in ("template_id", "version_or_revision", "language", "tense"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"protocol_template.{name}"),
            )
        if not self.sections:
            raise DomainValidationError(
                "protocol_template.sections must not be empty"
            )
        require_unique(
            tuple(item.section_id for item in self.sections),
            "protocol_template section ids",
        )
        require_unique(
            tuple(str(item.order) for item in self.sections),
            "protocol_template section orders",
        )


@dataclass(frozen=True, slots=True)
class ProtocolDocumentSection:
    section_id: str
    title: str
    semantic_section: ProtocolSemanticSection
    order: int
    required: bool
    content: str | None

    def __post_init__(self) -> None:
        for name in ("section_id", "title"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"document_section.{name}"),
            )
        if self.order < 0:
            raise DomainValidationError(
                "document_section.order must be non-negative"
            )
        if self.content is not None:
            object.__setattr__(
                self,
                "content",
                require_text(self.content, "document_section.content"),
            )
        if (
            self.semantic_section is ProtocolSemanticSection.ADDITIONAL
            and self.content is None
        ):
            raise DomainValidationError(
                "additional document sections require content"
            )


@dataclass(frozen=True, slots=True)
class ProtocolDocument:
    template_id: str
    version_or_revision: str
    review_type: ProtocolReviewType
    language: str
    tense: str
    sections: tuple[ProtocolDocumentSection, ...]

    def __post_init__(self) -> None:
        for name in ("template_id", "version_or_revision", "language", "tense"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"protocol_document.{name}"),
            )
        if not self.sections:
            raise DomainValidationError(
                "protocol_document.sections must not be empty"
            )
        require_unique(
            tuple(item.section_id for item in self.sections),
            "protocol_document section ids",
        )
        require_unique(
            tuple(str(item.order) for item in self.sections),
            "protocol_document section orders",
        )


class ProtocolExtensionValueKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    TEXT_LIST = "text_list"


@dataclass(frozen=True, slots=True)
class ProtocolExtensionValue:
    kind: ProtocolExtensionValueKind
    text: str | None
    number: float | None
    boolean: bool | None
    text_list: tuple[str, ...]

    def __post_init__(self) -> None:
        populated = {
            ProtocolExtensionValueKind.TEXT: self.text is not None,
            ProtocolExtensionValueKind.NUMBER: self.number is not None,
            ProtocolExtensionValueKind.BOOLEAN: self.boolean is not None,
            ProtocolExtensionValueKind.TEXT_LIST: bool(self.text_list),
        }
        if sum(populated.values()) != 1 or not populated[self.kind]:
            raise DomainValidationError(
                "extension value must populate exactly the field selected by kind"
            )
        if self.text is not None:
            object.__setattr__(
                self,
                "text",
                require_text(self.text, "extension_value.text"),
            )
        object.__setattr__(
            self,
            "text_list",
            require_unique(self.text_list, "extension_value.text_list"),
        )


@dataclass(frozen=True, slots=True)
class ProtocolExtension:
    extension_id: str
    namespace: str
    scope: str
    name: str
    value: ProtocolExtensionValue
    authority_standards: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("extension_id", "namespace", "scope", "name"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"protocol_extension.{name}"),
            )
        object.__setattr__(
            self,
            "authority_standards",
            require_unique(
                self.authority_standards,
                "protocol_extension.authority_standards",
            ),
        )


@dataclass(frozen=True, slots=True)
class MethodologyRequirement:
    standard: str
    title: str
    version_or_revision: str
    sections: tuple[str, ...]
    url: str

    def __post_init__(self) -> None:
        for name in ("standard", "title", "version_or_revision", "url"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"methodology_requirement.{name}"),
            )
        object.__setattr__(
            self,
            "sections",
            _require_items(self.sections, "methodology_requirement.sections"),
        )
        if urlparse(self.url).scheme != "https":
            raise DomainValidationError(
                "methodology_requirement.url must use HTTPS"
            )


@dataclass(frozen=True, slots=True)
class ProtocolStandards:
    methodology_standards: tuple[MethodologyRequirement, ...] = ()
    risk_of_bias_tool: str | None = None
    certainty_approach: str | None = None
    additional_requirements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        standards = tuple(item.standard for item in self.methodology_standards)
        require_unique(standards, "standards.methodology_standards")
        for name in ("risk_of_bias_tool", "certainty_approach"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    require_text(value, f"standards.{name}"),
                )
        object.__setattr__(
            self,
            "additional_requirements",
            require_unique(
                self.additional_requirements,
                "standards.additional_requirements",
            ),
        )


@dataclass(frozen=True, slots=True)
class MethodologyReference:
    standard: str
    title: str
    version_or_revision: str
    sections: tuple[str, ...]
    url: str
    accessed_on: str

    def __post_init__(self) -> None:
        for name in ("standard", "title", "version_or_revision", "url"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"methodology_reference.{name}"),
            )
        object.__setattr__(
            self,
            "sections",
            _require_items(self.sections, "methodology_reference.sections"),
        )
        if urlparse(self.url).scheme != "https":
            raise DomainValidationError(
                "methodology_reference.url must use HTTPS"
            )
        try:
            date.fromisoformat(self.accessed_on)
        except ValueError as exc:
            raise DomainValidationError(
                "methodology_reference.accessed_on must use YYYY-MM-DD"
            ) from exc


class MethodologyDecisionOrigin(StrEnum):
    SUPPLIED = "supplied"
    AGENT_RESOLVED = "agent_resolved"


class MethodologyBasisStatus(StrEnum):
    """How the Protocol's method basis was established."""

    VERIFIED = "verified"
    LLM_FALLBACK = "llm_fallback"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class MethodologyDecision:
    decision_id: str
    topic: str
    decision: str
    origin: MethodologyDecisionOrigin
    rationale: str
    authority_standards: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("decision_id", "topic", "decision", "rationale"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"methodology_decision.{name}"),
            )
        object.__setattr__(
            self,
            "authority_standards",
            require_unique(
                self.authority_standards,
                "methodology_decision.authority_standards",
            ),
        )


@dataclass(frozen=True, slots=True)
class MethodologyProfile:
    decisions: tuple[MethodologyDecision, ...]
    authorities: tuple[MethodologyReference, ...]
    unresolved_questions: tuple[str, ...] = ()
    basis_status: MethodologyBasisStatus | None = None
    fallback_model: str | None = None
    fallback_note: str | None = None

    def __post_init__(self) -> None:
        require_unique(
            tuple(item.decision_id for item in self.decisions),
            "methodology_profile decision ids",
        )
        standards = require_unique(
            tuple(item.standard for item in self.authorities),
            "methodology_profile authority standards",
        )
        object.__setattr__(
            self,
            "unresolved_questions",
            require_unique(
                self.unresolved_questions,
                "methodology_profile.unresolved_questions",
            ),
        )
        status = self.basis_status
        if status is None:
            status = (
                MethodologyBasisStatus.VERIFIED
                if self.authorities
                else MethodologyBasisStatus.UNRESOLVED
            )
            object.__setattr__(self, "basis_status", status)
        if status is MethodologyBasisStatus.VERIFIED and not self.authorities:
            raise DomainValidationError(
                "verified methodology basis requires an authority"
            )
        if status is MethodologyBasisStatus.VERIFIED:
            known = set(standards)
            for decision in self.decisions:
                if not set(decision.authority_standards) <= known:
                    raise DomainValidationError(
                        "verified methodology decision references an unknown authority"
                    )
        if status is MethodologyBasisStatus.LLM_FALLBACK:
            if not self.fallback_model or not self.fallback_model.strip():
                raise DomainValidationError(
                    "LLM fallback methodology basis requires fallback_model"
                )
            if not self.fallback_note or not self.fallback_note.strip():
                raise DomainValidationError(
                    "LLM fallback methodology basis requires fallback_note"
                )
        elif self.fallback_model is not None or self.fallback_note is not None:
            raise DomainValidationError(
                "fallback metadata is only valid for an LLM fallback basis"
            )


class ReviewDataDefinitionKind(StrEnum):
    INTERVENTION = "intervention"
    OUTCOME = "outcome"
    TIMEPOINT = "timepoint"
    CHARACTERISTIC = "characteristic"
    COVARIATE = "covariate"
    SYNTHESIS_PICO = "synthesis_pico"
    PLANNED_ANALYSIS = "planned_analysis"


@dataclass(frozen=True, slots=True)
class ReviewDataDefinitionAttribute:
    name: str
    value: ProtocolExtensionValue
    authority_standards: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            require_text(self.name, "data_definition_attribute.name"),
        )
        object.__setattr__(
            self,
            "authority_standards",
            require_unique(
                self.authority_standards,
                "data_definition_attribute.authority_standards",
            ),
        )


@dataclass(frozen=True, slots=True)
class ReviewDataDefinition:
    definition_id: str
    kind: ReviewDataDefinitionKind
    label: str
    description: str
    parent_definition_ids: tuple[str, ...] = ()
    attributes: tuple[ReviewDataDefinitionAttribute, ...] = ()

    def __post_init__(self) -> None:
        for name in ("definition_id", "label", "description"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"data_definition.{name}"),
            )
        object.__setattr__(
            self,
            "parent_definition_ids",
            require_unique(
                self.parent_definition_ids,
                "data_definition.parent_definition_ids",
            ),
        )
        require_unique(
            tuple(item.name for item in self.attributes),
            "data_definition attribute names",
        )


@dataclass(frozen=True, slots=True)
class Q2ProtocolInput:
    topic_text: str
    topic_kind: TopicKind
    scope_notes: tuple[str, ...] = ()
    background_sources: tuple[Provenance, ...] = ()
    standards: ProtocolStandards | None = None
    template: ProtocolTemplate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.topic_kind, TopicKind):
            raise DomainValidationError("topic_kind must be title or question")
        object.__setattr__(
            self, "topic_text", require_text(self.topic_text, "topic_text")
        )
        object.__setattr__(
            self, "scope_notes", require_unique(self.scope_notes, "scope_notes")
        )


@dataclass(frozen=True, slots=True)
class PICO:
    population: tuple[str, ...]
    intervention: tuple[str, ...]
    comparator: tuple[str, ...]
    outcomes: tuple[str, ...]
    context: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("population", "intervention", "comparator", "outcomes"):
            object.__setattr__(
                self, name, _require_items(getattr(self, name), f"pico.{name}")
            )
        object.__setattr__(
            self, "context", require_unique(self.context, "pico.context")
        )


@dataclass(frozen=True, slots=True)
class BackgroundSection:
    condition_or_problem: str
    intervention: str
    how_intervention_might_work: str
    rationale: str

    def __post_init__(self) -> None:
        for name in (
            "condition_or_problem",
            "intervention",
            "how_intervention_might_work",
            "rationale",
        ):
            object.__setattr__(
                self, name, require_text(getattr(self, name), f"background.{name}")
            )


@dataclass(frozen=True, slots=True)
class EligibilitySection:
    description: str
    inclusion_criteria: tuple[str, ...]
    exclusion_criteria: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "description",
            require_text(self.description, "eligibility.description"),
        )
        object.__setattr__(
            self,
            "inclusion_criteria",
            _require_items(self.inclusion_criteria, "eligibility.inclusion_criteria"),
        )
        object.__setattr__(
            self,
            "exclusion_criteria",
            require_unique(self.exclusion_criteria, "eligibility.exclusion_criteria"),
        )


@dataclass(frozen=True, slots=True)
class EligibilityCriteria:
    types_of_studies: EligibilitySection
    types_of_participants: EligibilitySection
    types_of_interventions: EligibilitySection
    comparators: EligibilitySection
    setting_restrictions: tuple[str, ...] = ()
    language_restrictions: tuple[str, ...] = ()
    publication_status_restrictions: tuple[str, ...] = ()
    time_restrictions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "setting_restrictions",
            "language_restrictions",
            "publication_status_restrictions",
            "time_restrictions",
        ):
            object.__setattr__(
                self, name, require_unique(getattr(self, name), f"eligibility.{name}")
            )


@dataclass(frozen=True, slots=True)
class OutcomeMeasure:
    name: str
    definition: str
    measurement: str
    time_points: tuple[str, ...]
    role: OutcomeRole

    def __post_init__(self) -> None:
        for name in ("name", "definition", "measurement"):
            object.__setattr__(
                self, name, require_text(getattr(self, name), f"outcome.{name}")
            )
        object.__setattr__(
            self,
            "time_points",
            _require_items(self.time_points, "outcome.time_points"),
        )


@dataclass(frozen=True, slots=True)
class OutcomePlan:
    outcomes: tuple[OutcomeMeasure, ...]

    def __post_init__(self) -> None:
        if not self.outcomes:
            raise DomainValidationError("outcomes must not be empty")
        require_unique(tuple(item.name for item in self.outcomes), "outcome names")
        if not any(item.role is OutcomeRole.PRIMARY for item in self.outcomes):
            raise DomainValidationError("outcomes require at least one primary outcome")


@dataclass(frozen=True, slots=True)
class SearchSource:
    source_name: str
    source_type: SearchSourceType
    platform: str
    date_coverage: str
    restrictions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("source_name", "platform", "date_coverage"):
            object.__setattr__(
                self, name, require_text(getattr(self, name), f"search_source.{name}")
            )
        object.__setattr__(
            self,
            "restrictions",
            require_unique(self.restrictions, "search_source.restrictions"),
        )


@dataclass(frozen=True, slots=True)
class SearchSourceStrategy:
    source_name: str
    strategy: str

    def __post_init__(self) -> None:
        for name in ("source_name", "strategy"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"search_strategy.{name}"),
            )


@dataclass(frozen=True, slots=True)
class OtherSearchProcedure:
    source_name: str
    procedure: str

    def __post_init__(self) -> None:
        for name in ("source_name", "procedure"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"other_search.{name}"),
            )


@dataclass(frozen=True, slots=True)
class SearchPlan:
    structured_sources: tuple[SearchSource, ...]
    strategies: tuple[SearchSourceStrategy, ...] = ()
    other_sources: tuple[OtherSearchProcedure, ...] = ()
    general_restrictions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.structured_sources:
            raise DomainValidationError("search requires a structured source")
        if not any(
            item.source_type is SearchSourceType.DATABASE
            for item in self.structured_sources
        ):
            raise DomainValidationError("search requires at least one database")
        require_unique(
            tuple(item.source_name for item in self.structured_sources),
            "search structured source names",
        )
        require_unique(
            tuple(item.source_name for item in self.other_sources),
            "search other source names",
        )
        object.__setattr__(
            self,
            "general_restrictions",
            require_unique(self.general_restrictions, "search.general_restrictions"),
        )


@dataclass(frozen=True, slots=True)
class StudySelectionPlan:
    title_abstract_screening: str
    full_report_assessment: str
    reviewer_process: str
    disagreement_resolution: str

    def __post_init__(self) -> None:
        for name in (
            "title_abstract_screening",
            "full_report_assessment",
            "reviewer_process",
            "disagreement_resolution",
        ):
            object.__setattr__(
                self, name, require_text(getattr(self, name), f"selection.{name}")
            )


@dataclass(frozen=True, slots=True)
class DataCollectionPlan:
    extraction_process: str
    data_items: tuple[str, ...]
    study_report_linkage: str
    missing_information: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "extraction_process",
            require_text(self.extraction_process, "data_collection.extraction_process"),
        )
        object.__setattr__(
            self,
            "data_items",
            _require_items(self.data_items, "data_collection.data_items"),
        )
        for name in ("study_report_linkage", "missing_information"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"data_collection.{name}"),
            )


@dataclass(frozen=True, slots=True)
class RiskOfBiasPlan:
    reviewer_process: str
    disagreement_resolution: str
    use_in_synthesis: str
    tool: str

    def __post_init__(self) -> None:
        for name in (
            "reviewer_process",
            "disagreement_resolution",
            "use_in_synthesis",
            "tool",
        ):
            object.__setattr__(
                self, name, require_text(getattr(self, name), f"risk_of_bias.{name}")
            )


@dataclass(frozen=True, slots=True)
class EffectMeasurePlan:
    result_type: str
    effect_measure: str

    def __post_init__(self) -> None:
        for name in ("result_type", "effect_measure"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"effect_measure.{name}"),
            )


@dataclass(frozen=True, slots=True)
class AnalysisPlan:
    effect_measures: tuple[EffectMeasurePlan, ...]
    unit_of_analysis: str
    missing_data: str
    heterogeneity: str
    reporting_bias: str

    def __post_init__(self) -> None:
        if not self.effect_measures:
            raise DomainValidationError("analysis.effect_measures must not be empty")
        require_unique(
            tuple(item.result_type for item in self.effect_measures),
            "analysis effect result types",
        )
        for name in (
            "unit_of_analysis",
            "missing_data",
            "heterogeneity",
            "reporting_bias",
        ):
            object.__setattr__(
                self, name, require_text(getattr(self, name), f"analysis.{name}")
            )


@dataclass(frozen=True, slots=True)
class SynthesisPICO:
    population: tuple[str, ...]
    intervention: tuple[str, ...]
    comparator: tuple[str, ...]
    outcomes: tuple[str, ...]
    time_frames: tuple[str, ...]
    study_designs: tuple[str, ...]
    grouping_rules: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "population",
            "intervention",
            "comparator",
            "outcomes",
            "time_frames",
            "study_designs",
            "grouping_rules",
        ):
            object.__setattr__(
                self,
                name,
                _require_items(getattr(self, name), f"synthesis_pico.{name}"),
            )


@dataclass(frozen=True, slots=True)
class SynthesisPlan:
    comparisons: tuple[SynthesisPICO, ...]
    quantitative_synthesis_criteria: str
    meta_analysis_methods: str
    non_meta_synthesis: str
    subgroup_analyses: tuple[str, ...] = ()
    sensitivity_analyses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.comparisons:
            raise DomainValidationError("synthesis.comparisons must not be empty")
        for name in (
            "quantitative_synthesis_criteria",
            "meta_analysis_methods",
            "non_meta_synthesis",
        ):
            object.__setattr__(
                self, name, require_text(getattr(self, name), f"synthesis.{name}")
            )
        for name in ("subgroup_analyses", "sensitivity_analyses"):
            object.__setattr__(
                self, name, require_unique(getattr(self, name), f"synthesis.{name}")
            )


@dataclass(frozen=True, slots=True)
class CertaintyPlan:
    outcomes: tuple[str, ...]
    summary_of_findings_plan: str
    approach: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "outcomes", _require_items(self.outcomes, "certainty.outcomes")
        )
        for name in ("summary_of_findings_plan", "approach"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"certainty.{name}"),
            )


@dataclass(frozen=True, slots=True)
class ProtocolMethods:
    eligibility: EligibilityCriteria
    outcomes: OutcomePlan
    search: SearchPlan
    selection: StudySelectionPlan
    data_collection: DataCollectionPlan
    risk_of_bias: RiskOfBiasPlan
    analysis: AnalysisPlan
    synthesis: SynthesisPlan
    certainty: CertaintyPlan


@dataclass(frozen=True, slots=True)
class ProtocolDraft:
    schema_version: Literal["protocol-artifact.v2"]
    version: str
    title: str
    background: BackgroundSection
    review_question: str
    review_pico: PICO
    objectives: tuple[str, ...]
    methods: ProtocolMethods
    methodology_profile: MethodologyProfile
    document: ProtocolDocument
    assumptions: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    data_definitions: tuple[ReviewDataDefinition, ...] = ()
    extensions: tuple[ProtocolExtension, ...] = ()
    profile: ProtocolProfile = ProtocolProfile.COCHRANE_INTERVENTION_V1
    document_status: ProtocolDocumentStatus = ProtocolDocumentStatus.DRAFT

    def __post_init__(self) -> None:
        if self.schema_version != "protocol-artifact.v2":
            raise DomainValidationError(
                "schema_version must be protocol-artifact.v2"
            )
        if self.profile is not ProtocolProfile.COCHRANE_INTERVENTION_V1:
            raise DomainValidationError("profile must be cochrane_intervention_v1")
        if self.document_status is not ProtocolDocumentStatus.DRAFT:
            raise DomainValidationError("document_status must be draft")
        object.__setattr__(self, "version", require_text(self.version, "version"))
        object.__setattr__(self, "title", require_text(self.title, "title"))
        object.__setattr__(
            self,
            "review_question",
            require_text(self.review_question, "review_question"),
        )
        object.__setattr__(
            self, "objectives", _require_items(self.objectives, "objectives")
        )
        require_unique(
            tuple(item.standard for item in self.methodology_profile.authorities),
            "methodology_profile authority standards",
        )
        definition_ids = require_unique(
            tuple(item.definition_id for item in self.data_definitions),
            "data definition ids",
        )
        known_definitions = set(definition_ids)
        for definition in self.data_definitions:
            if not set(definition.parent_definition_ids) <= known_definitions:
                raise DomainValidationError(
                    "data definition references an unknown parent"
                )
        require_unique(
            tuple(item.extension_id for item in self.extensions),
            "protocol extension ids",
        )
        if (
            self.methodology_profile.basis_status
            is MethodologyBasisStatus.VERIFIED
        ):
            known_standards = {
                item.standard for item in self.methodology_profile.authorities
            }
            for extension in self.extensions:
                if not set(extension.authority_standards) <= known_standards:
                    raise DomainValidationError(
                        "protocol extension references an unknown authority"
                    )
            for definition in self.data_definitions:
                for attribute in definition.attributes:
                    if not set(attribute.authority_standards) <= known_standards:
                        raise DomainValidationError(
                            "data definition attribute references an unknown authority"
                        )
        object.__setattr__(
            self, "assumptions", require_unique(self.assumptions, "assumptions")
        )
        object.__setattr__(
            self,
            "unresolved_questions",
            require_unique(self.unresolved_questions, "unresolved_questions"),
        )

    @property
    def methodology_basis(self) -> tuple[MethodologyReference, ...]:
        """Expose selected authorities to deterministic downstream projections."""
        return self.methodology_profile.authorities
