"""Public input contract for resumable Study Results collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .common import DomainValidationError, require_text, require_unique
from .protocol import (
    MethodologyProfile,
    PICO,
    ProtocolDraft,
    ProtocolExtension,
    ReviewDataDefinition,
    ReviewDataDefinitionKind,
)
from .selection import SelectionPackageRef


class ResultsReviewMode(StrEnum):
    SINGLE_AGENT = "single_agent"


@dataclass(frozen=True, slots=True)
class StudyResultsProtocolBlock:
    heading: str
    text: str

    def __post_init__(self) -> None:
        for name in ("heading", "text"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"results_protocol.{name}"),
            )


@dataclass(frozen=True, slots=True)
class StudyResultsProtocol:
    """The Protocol view needed to collect Study outcome results."""

    version: str
    review_question: str
    review_pico: PICO
    objectives: tuple[str, ...]
    eligibility_and_outcomes: tuple[StudyResultsProtocolBlock, ...]
    data_collection: tuple[StudyResultsProtocolBlock, ...]
    effect_calculation: tuple[StudyResultsProtocolBlock, ...]
    methodology_profile: MethodologyProfile = field(
        default_factory=lambda: MethodologyProfile(decisions=(), authorities=())
    )
    data_definitions: tuple[ReviewDataDefinition, ...] = ()
    extensions: tuple[ProtocolExtension, ...] = ()
    schema_version: str = "study-results-protocol.v2"

    def __post_init__(self) -> None:
        for name in ("version", "review_question"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"results_protocol.{name}"),
            )
        object.__setattr__(
            self,
            "objectives",
            require_unique(self.objectives, "results_protocol.objectives"),
        )
        if not self.objectives:
            raise DomainValidationError("results_protocol.objectives must not be empty")
        for name in (
            "eligibility_and_outcomes",
            "data_collection",
            "effect_calculation",
        ):
            if not getattr(self, name):
                raise DomainValidationError(
                    f"results_protocol.{name} must not be empty"
                )
        if self.schema_version != "study-results-protocol.v2":
            raise DomainValidationError(
                "Study Results requires study-results-protocol.v2"
            )


def study_results_protocol_from_draft(
    protocol: ProtocolDraft,
) -> StudyResultsProtocol:
    """Project a complete Protocol without unrelated task sections."""

    eligibility = protocol.methods.eligibility
    outcomes = protocol.methods.outcomes.outcomes
    collection = protocol.methods.data_collection
    analysis = protocol.methods.analysis
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
        StudyResultsProtocolBlock(
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
    return StudyResultsProtocol(
        version=protocol.version,
        review_question=protocol.review_question,
        review_pico=protocol.review_pico,
        objectives=protocol.objectives,
        eligibility_and_outcomes=eligibility_blocks + outcome_blocks,
        data_collection=(
            StudyResultsProtocolBlock(
                "Data extraction and management",
                "\n".join(
                    (
                        collection.extraction_process,
                        "Data items: " + "; ".join(collection.data_items),
                        collection.study_report_linkage,
                    )
                ),
            ),
            StudyResultsProtocolBlock(
                "Dealing with missing data",
                collection.missing_information,
            ),
        ),
        effect_calculation=(
            StudyResultsProtocolBlock(
                "Measures of treatment effect",
                "\n".join(
                    f"{item.result_type}: {item.effect_measure}"
                    for item in analysis.effect_measures
                ),
            ),
            StudyResultsProtocolBlock(
                "Unit of analysis issues",
                analysis.unit_of_analysis,
            ),
            StudyResultsProtocolBlock(
                "Dealing with missing data",
                analysis.missing_data,
            ),
        ),
        methodology_profile=protocol.methodology_profile,
        data_definitions=tuple(
            item
            for item in protocol.data_definitions
            if item.kind is not ReviewDataDefinitionKind.CHARACTERISTIC
        ),
        extensions=protocol.extensions,
    )


@dataclass(frozen=True, slots=True)
class StudyResultsInput:
    protocol: StudyResultsProtocol
    selection_package: SelectionPackageRef
    work_id: str | None = None
    review_mode: ResultsReviewMode = ResultsReviewMode.SINGLE_AGENT

    def __post_init__(self) -> None:
        if not isinstance(self.protocol, StudyResultsProtocol):
            raise DomainValidationError("Study Results requires a StudyResultsProtocol")
        if self.selection_package.schema_version != "selection-package.v4":
            raise DomainValidationError("Study Results requires selection-package.v4")
        if self.work_id is not None:
            object.__setattr__(
                self,
                "work_id",
                require_text(self.work_id, "work_id"),
            )


def _eligibility_block(
    heading: str,
    section: object,
) -> StudyResultsProtocolBlock:
    parts = [require_text(getattr(section, "description"), heading)]
    parts.extend(
        f"Include: {value}" for value in getattr(section, "inclusion_criteria")
    )
    parts.extend(
        f"Exclude: {value}" for value in getattr(section, "exclusion_criteria")
    )
    return StudyResultsProtocolBlock(heading=heading, text="\n".join(parts))
