"""Study Data Collection parent-task contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import DomainValidationError, require_text, require_unique
from .protocol import (
    MethodologyProfile,
    PICO,
    ProtocolDraft,
    ProtocolExtension,
    ReviewDataDefinition,
)
from .selection import StudySelectionArtifact
from .study_data import (
    StudyResultsProtocolBlock,
    study_results_protocol_from_draft,
)


@dataclass(frozen=True, slots=True)
class StudyDataCollectionProtocol:
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
    schema_version: str = "study-data-collection-protocol.v1"

    def __post_init__(self) -> None:
        for name in ("version", "review_question"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        object.__setattr__(
            self,
            "objectives",
            require_unique(self.objectives, "study_data_collection.objectives"),
        )
        if not self.objectives:
            raise DomainValidationError("Study Data Collection objectives are required")
        for name in (
            "eligibility_and_outcomes",
            "data_collection",
            "effect_calculation",
        ):
            if not getattr(self, name):
                raise DomainValidationError(f"Study Data Collection {name} is required")
        if self.schema_version != "study-data-collection-protocol.v1":
            raise DomainValidationError(
                "Study Data Collection requires study-data-collection-protocol.v1"
            )


def study_data_collection_protocol_from_draft(
    protocol: ProtocolDraft,
) -> StudyDataCollectionProtocol:
    """Project the complete Protocol context needed by one collection Agent."""

    results = study_results_protocol_from_draft(protocol)
    return StudyDataCollectionProtocol(
        version=results.version,
        review_question=results.review_question,
        review_pico=results.review_pico,
        objectives=results.objectives,
        eligibility_and_outcomes=results.eligibility_and_outcomes,
        data_collection=results.data_collection,
        effect_calculation=results.effect_calculation,
        methodology_profile=results.methodology_profile,
        data_definitions=protocol.data_definitions,
        extensions=results.extensions,
    )


@dataclass(frozen=True, slots=True)
class StudyDataCollectionInput:
    protocol: StudyDataCollectionProtocol
    selection: StudySelectionArtifact
