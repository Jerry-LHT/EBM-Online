"""Study Selection domain contracts.

Search produces source Records. Study Selection preserves those Records,
identifies Reports, collates Reports into review-local Studies, and makes the
final eligibility decision at Study level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .common import DomainValidationError, Provenance, require_text, require_unique
from .protocol import ProtocolDraft
from .search import EvidenceSearchPublicArtifact


@dataclass(frozen=True, slots=True)
class StudySelectionProtocolBlock:
    """One source-preserving section of the Protocol needed for selection."""

    heading: str
    text: str

    def __post_init__(self) -> None:
        for name in ("heading", "text"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"selection_protocol.{name}"),
            )


@dataclass(frozen=True, slots=True)
class StudySelectionProtocol:
    """The Protocol view required to screen Records and classify Studies."""

    version: str
    review_question: str
    objectives: tuple[StudySelectionProtocolBlock, ...]
    study_designs: tuple[StudySelectionProtocolBlock, ...]
    participants: tuple[StudySelectionProtocolBlock, ...]
    interventions_and_comparators: tuple[StudySelectionProtocolBlock, ...]
    setting_restrictions: tuple[str, ...] = ()
    language_restrictions: tuple[str, ...] = ()
    publication_status_restrictions: tuple[str, ...] = ()
    time_restrictions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("version", "review_question"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"selection_protocol.{name}"),
            )
        for name in (
            "objectives",
            "study_designs",
            "participants",
            "interventions_and_comparators",
        ):
            values = getattr(self, name)
            if not values:
                raise DomainValidationError(
                    f"selection_protocol.{name} must not be empty"
                )
        for name in (
            "setting_restrictions",
            "language_restrictions",
            "publication_status_restrictions",
            "time_restrictions",
        ):
            object.__setattr__(
                self,
                name,
                require_unique(getattr(self, name), f"selection_protocol.{name}"),
            )


def study_selection_protocol_from_draft(
    protocol: ProtocolDraft,
) -> StudySelectionProtocol:
    """Project a complete Protocol Draft into the Study Selection boundary."""

    eligibility = protocol.methods.eligibility
    return StudySelectionProtocol(
        version=protocol.version,
        review_question=protocol.review_question,
        objectives=tuple(
            StudySelectionProtocolBlock("Objectives", objective)
            for objective in protocol.objectives
        ),
        study_designs=(
            _eligibility_block("Types of studies", eligibility.types_of_studies),
        ),
        participants=(
            _eligibility_block(
                "Types of participants",
                eligibility.types_of_participants,
            ),
        ),
        interventions_and_comparators=(
            _eligibility_block(
                "Types of interventions",
                eligibility.types_of_interventions,
            ),
            _eligibility_block("Comparators", eligibility.comparators),
        ),
        setting_restrictions=eligibility.setting_restrictions,
        language_restrictions=eligibility.language_restrictions,
        publication_status_restrictions=(
            eligibility.publication_status_restrictions
        ),
        time_restrictions=eligibility.time_restrictions,
    )


def _eligibility_block(heading: str, section: object) -> StudySelectionProtocolBlock:
    description = require_text(
        getattr(section, "description"),
        f"selection_protocol.{heading}.description",
    )
    inclusion = tuple(getattr(section, "inclusion_criteria"))
    exclusion = tuple(getattr(section, "exclusion_criteria"))
    parts = [description]
    parts.extend(f"Include: {value}" for value in inclusion)
    parts.extend(f"Exclude: {value}" for value in exclusion)
    return StudySelectionProtocolBlock(heading=heading, text="\n".join(parts))


@dataclass(frozen=True, slots=True)
class RecordScreeningDecision:
    record_id: str
    screening_label: str
    advances_to_report_assessment: bool | None
    reason: str | None = None
    duplicate_of_record_id: str | None = None
    protocol_criteria: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        for name in ("record_id", "screening_label"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if self.reason is not None:
            object.__setattr__(self, "reason", require_text(self.reason, "reason"))
        object.__setattr__(
            self,
            "protocol_criteria",
            require_unique(self.protocol_criteria, "protocol_criteria"),
        )
        if self.duplicate_of_record_id is not None:
            object.__setattr__(
                self,
                "duplicate_of_record_id",
                require_text(self.duplicate_of_record_id, "duplicate_of_record_id"),
            )
            if self.duplicate_of_record_id == self.record_id:
                raise DomainValidationError(
                    "duplicate Record must reference another Record"
                )
        if not self.provenance:
            raise DomainValidationError(
                "Record screening decision requires provenance"
            )


@dataclass(frozen=True, slots=True)
class Report:
    report_id: str
    title: str
    report_type: str
    citation: str | None = None
    external_identifiers: tuple[str, ...] = ()
    locators: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        for name in ("report_id", "title", "report_type"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        object.__setattr__(
            self,
            "external_identifiers",
            require_unique(self.external_identifiers, "external_identifiers"),
        )
        object.__setattr__(self, "locators", require_unique(self.locators, "locators"))
        if not self.provenance:
            raise DomainValidationError("Report requires provenance")


@dataclass(frozen=True, slots=True)
class RecordReportLink:
    record_id: str
    report_id: str
    rationale: str
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        for name in ("record_id", "report_id", "rationale"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if not self.provenance:
            raise DomainValidationError("Record-Report link requires provenance")


@dataclass(frozen=True, slots=True)
class ReportDiscoveryLink:
    report_id: str
    source_id: str
    source_type: str
    rationale: str
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        for name in ("report_id", "source_id", "source_type", "rationale"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if not self.provenance:
            raise DomainValidationError("Report discovery link requires provenance")


@dataclass(frozen=True, slots=True)
class ReportEvidenceObservation:
    observation_id: str
    report_id: str
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
            "locator",
            "evidence_format",
            "observed_at",
            "summary",
        ):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if not self.provenance:
            raise DomainValidationError(
                "Report evidence observation requires provenance"
            )


@dataclass(frozen=True, slots=True)
class Study:
    study_id: str
    display_name: str
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "study_id", require_text(self.study_id, "study_id"))
        object.__setattr__(
            self,
            "display_name",
            require_text(self.display_name, "display_name"),
        )
        if not self.provenance:
            raise DomainValidationError("Study requires provenance")


@dataclass(frozen=True, slots=True)
class StudyReportLink:
    study_id: str
    report_id: str
    is_primary: bool
    rationale: str
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        for name in ("study_id", "report_id", "rationale"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if not self.provenance:
            raise DomainValidationError("Study-Report link requires provenance")


class StudyClassification(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    AWAITING_CLASSIFICATION = "awaiting_classification"
    ONGOING = "ongoing"


@dataclass(frozen=True, slots=True)
class StudyEligibilityDecision:
    study_id: str
    classification: StudyClassification
    reason: str | None = None
    primary_exclusion_criterion: str | None = None
    follow_up_actions: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "study_id",
            require_text(self.study_id, "study_id"),
        )
        if self.reason is not None:
            object.__setattr__(self, "reason", require_text(self.reason, "reason"))
        object.__setattr__(
            self,
            "follow_up_actions",
            require_unique(self.follow_up_actions, "follow_up_actions"),
        )
        if self.primary_exclusion_criterion is not None:
            object.__setattr__(
                self,
                "primary_exclusion_criterion",
                require_text(
                    self.primary_exclusion_criterion,
                    "primary_exclusion_criterion",
                ),
            )
        if not self.provenance:
            raise DomainValidationError(
                "Study eligibility decision requires provenance"
            )


@dataclass(frozen=True, slots=True)
class SelectionConflict:
    conflict_id: str
    kind: str
    target_ids: tuple[str, ...]
    resolved: bool
    description: str
    resolution: str | None = None
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "conflict_id",
            require_text(self.conflict_id, "conflict_id"),
        )
        object.__setattr__(self, "kind", require_text(self.kind, "kind"))
        object.__setattr__(
            self,
            "target_ids",
            require_unique(self.target_ids, "target_ids"),
        )
        object.__setattr__(
            self,
            "description",
            require_text(self.description, "description"),
        )
        if not self.target_ids:
            raise DomainValidationError("Selection conflict requires a target")
        if self.resolved:
            if self.resolution is None:
                raise DomainValidationError("resolved conflict requires a resolution")
            object.__setattr__(
                self,
                "resolution",
                require_text(self.resolution, "resolution"),
            )
        elif self.resolution is not None:
            raise DomainValidationError(
                "unresolved conflict must not contain a resolution"
            )
        if not self.provenance:
            raise DomainValidationError("Selection conflict requires provenance")


@dataclass(frozen=True, slots=True)
class SelectionSummary:
    source_record_count: int
    duplicate_record_count: int
    records_screened_count: int
    title_abstract_excluded_count: int
    reports_sought_count: int
    reports_not_retrieved_count: int
    reports_assessed_count: int
    study_count: int
    included_count: int
    excluded_count: int
    awaiting_classification_count: int
    ongoing_count: int
    unresolved_conflict_count: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")
        if self.title_abstract_excluded_count > self.records_screened_count:
            raise DomainValidationError(
                "title/abstract exclusions cannot exceed screened Records"
            )
        if (
            self.reports_assessed_count + self.reports_not_retrieved_count
            != self.reports_sought_count
        ):
            raise DomainValidationError(
                "assessed and not-retrieved Report counts must equal Reports sought"
            )


@dataclass(frozen=True, slots=True)
class SelectionPackageRef:
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


class SearchContinuationStatus(StrEnum):
    PROCEED = "proceed"
    CONTINUE_SEARCH = "continue_search"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class SearchContinuationDecision:
    status: SearchContinuationStatus
    rationale: str
    evidence_gaps: tuple[str, ...] = ()
    suggested_actions: tuple[str, ...] = ()
    candidate_leads: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rationale",
            require_text(self.rationale, "search_continuation.rationale"),
        )
        object.__setattr__(
            self,
            "evidence_gaps",
            require_unique(self.evidence_gaps, "search_continuation.evidence_gaps"),
        )
        object.__setattr__(
            self,
            "suggested_actions",
            require_unique(
                self.suggested_actions,
                "search_continuation.suggested_actions",
            ),
        )
        object.__setattr__(
            self,
            "candidate_leads",
            require_unique(
                tuple(
                    require_text(value, "search_continuation.candidate_leads")
                    for value in self.candidate_leads
                ),
                "search_continuation.candidate_leads",
            ),
        )


@dataclass(frozen=True, slots=True)
class SelectionCollections:
    """Typed canonical collections stored in a Selection Package."""

    record_screening: tuple[RecordScreeningDecision, ...]
    reports: tuple[Report, ...]
    report_discoveries: tuple[ReportDiscoveryLink, ...]
    record_report_links: tuple[RecordReportLink, ...]
    report_evidence: tuple[ReportEvidenceObservation, ...]
    studies: tuple[Study, ...]
    study_report_links: tuple[StudyReportLink, ...]
    study_decisions: tuple[StudyEligibilityDecision, ...]
    conflicts: tuple[SelectionConflict, ...]


@dataclass(frozen=True, slots=True)
class StudySelectionArtifact:
    package_ref: SelectionPackageRef
    summary: SelectionSummary
    search_continuation: SearchContinuationDecision = field(
        default_factory=lambda: SearchContinuationDecision(
            status=SearchContinuationStatus.PROCEED,
            rationale="The completed selection run did not request another search.",
            )
        )

    def __post_init__(self) -> None:
        if self.package_ref.schema_version != "selection-package.v4":
            raise DomainValidationError(
                "Study Selection requires selection-package.v4"
            )


@dataclass(frozen=True, slots=True)
class StudySelectionInput:
    protocol: StudySelectionProtocol
    search: EvidenceSearchPublicArtifact
