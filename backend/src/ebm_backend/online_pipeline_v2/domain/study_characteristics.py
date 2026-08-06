"""Study-level Characteristics collected from all linked Reports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import (
    ArtifactIssue,
    ArtifactStatus,
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
)
from .selection import Report, StudySelectionArtifact


class CharacteristicsMethodSectionName(StrEnum):
    STUDY_DESIGNS = "study_designs"
    PARTICIPANTS = "participants"
    INTERVENTIONS = "interventions"
    OUTCOMES = "outcomes"
    PRIMARY_OUTCOMES = "primary_outcomes"
    SECONDARY_OUTCOMES = "secondary_outcomes"
    DATA_COLLECTION = "data_collection"


@dataclass(frozen=True, slots=True)
class StudyCharacteristicsMethodSection:
    name: CharacteristicsMethodSectionName
    heading: str
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, CharacteristicsMethodSectionName):
            raise DomainValidationError(
                "method_section.name must be a CharacteristicsMethodSectionName"
            )
        object.__setattr__(
            self,
            "heading",
            require_text(self.heading, "method_section.heading"),
        )
        object.__setattr__(
            self,
            "text",
            require_text(self.text, "method_section.text"),
        )


@dataclass(frozen=True, slots=True)
class StudyCharacteristicsProtocolContext:
    protocol_version: str
    review_question: str
    review_pico: PICO
    method_sections: tuple[StudyCharacteristicsMethodSection, ...]
    provenance: tuple[Provenance, ...]
    methodology_basis: tuple[MethodologyReference, ...] = ()
    methodology_basis_status: MethodologyBasisStatus = MethodologyBasisStatus.VERIFIED
    methodology_fallback_model: str | None = None
    methodology_fallback_note: str | None = None
    schema_version: str = "study-characteristics-protocol-context.v2"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "protocol_version",
            require_text(self.protocol_version, "protocol_context.protocol_version"),
        )
        object.__setattr__(
            self,
            "review_question",
            require_text(self.review_question, "protocol_context.review_question"),
        )
        if self.schema_version != "study-characteristics-protocol-context.v2":
            raise DomainValidationError(
                "Study Characteristics requires "
                "study-characteristics-protocol-context.v2"
            )
        names = tuple(item.name.value for item in self.method_sections)
        require_unique(names, "protocol_context.method_sections")
        required = {
            CharacteristicsMethodSectionName.STUDY_DESIGNS.value,
            CharacteristicsMethodSectionName.PARTICIPANTS.value,
            CharacteristicsMethodSectionName.INTERVENTIONS.value,
            CharacteristicsMethodSectionName.DATA_COLLECTION.value,
        }
        missing = sorted(required.difference(names))
        if missing:
            raise DomainValidationError(
                "Study Characteristics Protocol context is missing required "
                f"method sections: {', '.join(missing)}"
            )
        if not {
            CharacteristicsMethodSectionName.OUTCOMES.value,
            CharacteristicsMethodSectionName.PRIMARY_OUTCOMES.value,
        }.intersection(names):
            raise DomainValidationError(
                "Study Characteristics Protocol context requires outcomes or "
                "primary_outcomes"
            )
        if not self.provenance:
            raise DomainValidationError(
                "Study Characteristics Protocol context requires provenance"
            )


@dataclass(frozen=True, slots=True)
class StudyCharacteristicsMethodologyAuthority:
    """Authority actually consulted by one Characteristics Agent run."""

    agent_role: str
    title: str
    version_or_date: str
    locator: str
    scope: str
    applied_principles: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "agent_role",
            "title",
            "version_or_date",
            "locator",
            "scope",
        ):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if not self.locator.startswith("https://"):
            raise DomainValidationError("methodology authority locator must use HTTPS")
        object.__setattr__(
            self,
            "applied_principles",
            tuple(
                require_text(item, "methodology authority applied_principles")
                for item in self.applied_principles
            ),
        )
        if not self.applied_principles:
            raise DomainValidationError(
                "methodology authority requires applied_principles"
            )


@dataclass(frozen=True, slots=True)
class CharacteristicsReportEvidenceObservation:
    """Report-reading evidence authored during Characteristics collection."""

    observation_id: str
    report_id: str
    agent_role: str
    locator: str
    evidence_format: str
    accessed: bool
    observed_at: str
    summary: str
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "report_id",
            "agent_role",
            "locator",
            "evidence_format",
            "observed_at",
            "summary",
        ):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if not self.provenance:
            raise DomainValidationError(
                "Characteristics Report evidence observation requires provenance"
            )


class CharacteristicFieldStatus(StrEnum):
    REPORTED = "reported"
    NOT_REPORTED = "not_reported"
    CONFLICTING = "conflicting"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


class DiscoveredReportRelationshipStatus(StrEnum):
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class DiscoveredReportLink:
    """Characteristics-time handoff for a Report absent from Selection."""

    study_id: str
    report_id: str
    relationship_status: DiscoveredReportRelationshipStatus
    report_role: str
    rationale: str
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        for name in ("study_id", "report_id", "report_role", "rationale"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if not self.provenance:
            raise DomainValidationError("discovered Report link requires provenance")


class StudyArmRole(StrEnum):
    INTERVENTION = "intervention"
    COMPARATOR = "comparator"
    OTHER_ELIGIBLE = "other_eligible"


@dataclass(frozen=True, slots=True)
class CharacteristicField:
    status: CharacteristicFieldStatus
    value: str | None = None
    source_texts: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        if self.value is not None:
            object.__setattr__(
                self,
                "value",
                require_text(self.value, "characteristic_field.value"),
            )
        # Source observations are model-authored evidence notes. They must be
        # text, but repeated wording is not a product-level error.
        object.__setattr__(
            self,
            "source_texts",
            tuple(
                require_text(item, "characteristic_field.source_texts")
                for item in self.source_texts
            ),
        )
        if self.note is not None:
            object.__setattr__(
                self,
                "note",
                require_text(self.note, "characteristic_field.note"),
            )
        # Status/value/provenance combinations and the amount of source text
        # needed to support them are professional quality claims. The Backend
        # preserves them and validates only their structural contract.


@dataclass(frozen=True, slots=True)
class StudyMethods:
    design: CharacteristicField
    setting: CharacteristicField
    centres: CharacteristicField
    recruitment: CharacteristicField
    study_dates: CharacteristicField
    follow_up: CharacteristicField
    allocation_or_exposure: CharacteristicField
    unit_of_analysis: CharacteristicField
    analysis_methods: CharacteristicField


@dataclass(frozen=True, slots=True)
class StudyPopulation:
    eligibility_criteria: CharacteristicField
    diagnostic_criteria: CharacteristicField
    recruitment_setting: CharacteristicField
    regions: CharacteristicField
    sample_size: CharacteristicField
    baseline_characteristics: CharacteristicField


@dataclass(frozen=True, slots=True)
class StudyArm:
    arm_id: str
    role: StudyArmRole
    label: CharacteristicField
    description: CharacteristicField
    dose_or_intensity: CharacteristicField
    route_or_mode: CharacteristicField
    frequency: CharacteristicField
    duration: CharacteristicField
    cointerventions: CharacteristicField
    fidelity_or_adherence: CharacteristicField

    def __post_init__(self) -> None:
        object.__setattr__(self, "arm_id", require_text(self.arm_id, "arm_id"))


@dataclass(frozen=True, slots=True)
class StudyOutcome:
    outcome_id: str
    assessed: CharacteristicField
    definition: CharacteristicField
    measurement: CharacteristicField
    metric: CharacteristicField
    aggregation: CharacteristicField
    time_points: CharacteristicField

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "outcome_id",
            require_text(self.outcome_id, "outcome_id"),
        )


@dataclass(frozen=True, slots=True)
class StudyCharacteristicsRecord:
    study_id: str
    status: ArtifactStatus
    report_ids: tuple[str, ...]
    methods: StudyMethods
    population: StudyPopulation
    arms: tuple[StudyArm, ...]
    outcomes: tuple[StudyOutcome, ...]
    funding: CharacteristicField
    conflicts_of_interest: CharacteristicField
    notes: CharacteristicField

    def __post_init__(self) -> None:
        object.__setattr__(self, "study_id", require_text(self.study_id, "study_id"))
        object.__setattr__(
            self,
            "report_ids",
            require_unique(self.report_ids, "report_ids"),
        )
        if not self.report_ids:
            raise DomainValidationError(
                "Study Characteristics record requires at least one Report"
        )
        require_unique(tuple(item.arm_id for item in self.arms), "arm_ids")
        require_unique(tuple(item.outcome_id for item in self.outcomes), "outcome_ids")
        if self.status is ArtifactStatus.BLOCKED:
            raise DomainValidationError(
                "blocked Study Characteristics must not expose a Study record"
            )


@dataclass(frozen=True, slots=True)
class CharacteristicsCollections:
    """Typed canonical collections produced for one Characteristics review."""

    studies: tuple[StudyCharacteristicsRecord, ...]
    discovered_reports: tuple[Report, ...]
    discovered_report_links: tuple[DiscoveredReportLink, ...]
    report_evidence: tuple[CharacteristicsReportEvidenceObservation, ...]
    issues: tuple[ArtifactIssue, ...]


@dataclass(frozen=True, slots=True)
class StudyCharacteristicsPackageRef:
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
        if self.schema_version != "study-characteristics-package.v6":
            raise DomainValidationError(
                "Study Characteristics requires study-characteristics-package.v6"
            )


@dataclass(frozen=True, slots=True)
class StudyCharacteristicsSummary:
    included_study_count: int
    completed_study_count: int
    partial_study_count: int
    blocked_study_count: int
    report_count: int
    issue_count: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")
        if (
            self.completed_study_count
            + self.partial_study_count
            + self.blocked_study_count
            != self.included_study_count
        ):
            raise DomainValidationError(
                "Study Characteristics status counts must equal included Study count"
            )


@dataclass(frozen=True, slots=True)
class StudyCharacteristicsArtifact:
    package_ref: StudyCharacteristicsPackageRef
    summary: StudyCharacteristicsSummary


@dataclass(frozen=True, slots=True)
class StudyCharacteristicsInput:
    protocol_context: StudyCharacteristicsProtocolContext
    selection: StudySelectionArtifact


def study_characteristics_protocol_from_draft(
    protocol: ProtocolDraft,
) -> StudyCharacteristicsProtocolContext:
    """Project the Protocol sections needed for Study Characteristics."""

    eligibility = protocol.methods.eligibility
    outcomes = protocol.methods.outcomes.outcomes
    collection = protocol.methods.data_collection

    def eligibility_text(section: object) -> str:
        parts = [getattr(section, "description")]
        parts.extend(
            f"Include: {item}" for item in getattr(section, "inclusion_criteria")
        )
        parts.extend(
            f"Exclude: {item}" for item in getattr(section, "exclusion_criteria")
        )
        return "\n".join(parts)

    outcome_text = "\n\n".join(
        "\n".join(
            (
                f"{item.role.value}: {item.name}",
                item.definition,
                f"Measurement: {item.measurement}",
                f"Time points: {', '.join(item.time_points)}",
            )
        )
        for item in outcomes
    )
    return StudyCharacteristicsProtocolContext(
        protocol_version=protocol.version,
        review_question=protocol.review_question,
        review_pico=protocol.review_pico,
        method_sections=(
            StudyCharacteristicsMethodSection(
                CharacteristicsMethodSectionName.STUDY_DESIGNS,
                "Types of studies",
                eligibility_text(eligibility.types_of_studies),
            ),
            StudyCharacteristicsMethodSection(
                CharacteristicsMethodSectionName.PARTICIPANTS,
                "Types of participants",
                eligibility_text(eligibility.types_of_participants),
            ),
            StudyCharacteristicsMethodSection(
                CharacteristicsMethodSectionName.INTERVENTIONS,
                "Types of interventions and comparators",
                "\n\n".join(
                    (
                        eligibility_text(eligibility.types_of_interventions),
                        eligibility_text(eligibility.comparators),
                    )
                ),
            ),
            StudyCharacteristicsMethodSection(
                CharacteristicsMethodSectionName.OUTCOMES,
                "Outcomes",
                outcome_text,
            ),
            StudyCharacteristicsMethodSection(
                CharacteristicsMethodSectionName.DATA_COLLECTION,
                "Data collection",
                "\n".join(
                    (
                        collection.extraction_process,
                        *collection.data_items,
                        collection.study_report_linkage,
                        collection.missing_information,
                    )
                ),
            ),
        ),
        provenance=(
            Provenance(
                source_id=f"{protocol.version}:study-characteristics",
                source_type="protocol_draft",
            ),
        ),
        methodology_basis=protocol.methodology_basis,
        methodology_basis_status=protocol.methodology_profile.basis_status,
        methodology_fallback_model=protocol.methodology_profile.fallback_model,
        methodology_fallback_note=protocol.methodology_profile.fallback_note,
    )
