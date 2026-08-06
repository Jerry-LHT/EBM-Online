"""Scientific Systematic Review composition contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from .common import ArtifactFile, ArtifactIssue, Provenance, require_text, require_unique
from .protocol import (
    MethodologyBasisStatus,
    MethodologyReference,
    ProtocolDraft,
)


class ReviewPath(StrEnum):
    EVIDENCE_REVIEW = "evidence_review"
    EMPTY_REVIEW = "empty_review"


class ReviewDocumentMaturity(StrEnum):
    SCIENTIFIC_DRAFT = "scientific_draft"


class ReviewSectionName(StrEnum):
    ABSTRACT = "abstract"
    PLAIN_LANGUAGE_SUMMARY = "plain_language_summary"
    BACKGROUND = "background"
    OBJECTIVES = "objectives"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    CONCLUSIONS = "conclusions"
    REFERENCES = "references"


class ReviewDisplayKind(StrEnum):
    SELECTION_FLOW = "selection_flow"
    STUDY_CHARACTERISTICS = "study_characteristics"
    RISK_OF_BIAS = "risk_of_bias"
    INDIVIDUAL_RESULTS = "individual_results"
    SYNTHESIS_RESULTS = "synthesis_results"
    SUMMARY_OF_FINDINGS = "summary_of_findings"


class ReviewDisplayLocation(StrEnum):
    BEFORE_BACKGROUND = "before_background"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    APPENDIX = "appendix"


@dataclass(frozen=True, slots=True)
class EmptyReviewContext:
    selection_package_id: str
    selection_package_digest: str
    source_record_count: int
    study_count: int
    included_count: int
    excluded_count: int
    awaiting_classification_count: int
    ongoing_count: int
    unresolved_conflict_count: int
    schema_version: str = "empty-review-context.v1"

    def __post_init__(self) -> None:
        for name in ("selection_package_id", "selection_package_digest"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        for name in (
            "source_record_count",
            "study_count",
            "included_count",
            "excluded_count",
            "awaiting_classification_count",
            "ongoing_count",
            "unresolved_conflict_count",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"empty_review.{name} must be non-negative")
        if self.included_count != 0:
            raise ValueError("empty-review context requires zero Included Studies")
        classified = (
            self.included_count
            + self.excluded_count
            + self.awaiting_classification_count
            + self.ongoing_count
        )
        if self.study_count != classified:
            raise ValueError("empty-review Study count does not match classifications")
        if self.schema_version != "empty-review-context.v1":
            raise ValueError("unsupported empty-review context schema")


@dataclass(frozen=True, slots=True)
class SystematicReviewEvidencePackageRef:
    package_id: str
    schema_version: str
    review_id: str
    protocol_version: str
    review_path: ReviewPath
    content_digest: str
    files: tuple[ArtifactFile, ...]

    def __post_init__(self) -> None:
        for name in (
            "package_id",
            "schema_version",
            "review_id",
            "protocol_version",
            "content_digest",
        ):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if self.schema_version != "systematic-review-evidence-package.v2":
            raise ValueError("unsupported Systematic Review evidence package schema")
        if not self.files:
            raise ValueError("Systematic Review evidence package requires files")
        require_unique(tuple(item.name for item in self.files), "review evidence files")


@dataclass(frozen=True, slots=True)
class ReviewSubsection:
    heading: str
    content: str

    def __post_init__(self) -> None:
        for name in ("heading", "content"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class SystematicReviewSectionDraft:
    name: ReviewSectionName
    content: str
    subsections: tuple[ReviewSubsection, ...] = ()
    source_artifact_ids: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", require_text(self.content, "section.content"))
        require_unique(
            tuple(item.heading for item in self.subsections),
            "section subsection headings",
        )
        object.__setattr__(
            self,
            "source_artifact_ids",
            require_unique(self.source_artifact_ids, "section source artifact ids"),
        )


@dataclass(frozen=True, slots=True)
class ReportingMethodDecision:
    decision_id: str
    topic: str
    decision: str
    rationale: str
    basis_status: MethodologyBasisStatus
    authoritative_sources: tuple[MethodologyReference, ...] = ()
    fallback_model: str | None = None
    fallback_note: str | None = None
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        for name in ("decision_id", "topic", "decision", "rationale"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if self.basis_status is MethodologyBasisStatus.VERIFIED:
            if not self.authoritative_sources:
                raise ValueError("verified reporting decision requires an authority")
            if self.fallback_model is not None or self.fallback_note is not None:
                raise ValueError("verified reporting decision cannot use LLM fallback")
        elif self.basis_status is MethodologyBasisStatus.LLM_FALLBACK:
            if self.authoritative_sources:
                raise ValueError("LLM fallback cannot claim a verified authority")
            for name in ("fallback_model", "fallback_note"):
                value = getattr(self, name)
                if value is None:
                    raise ValueError(f"LLM fallback requires {name}")
                object.__setattr__(self, name, require_text(value, name))
        elif self.fallback_model is not None or self.fallback_note is not None:
            raise ValueError("unresolved reporting decision cannot claim LLM fallback")


@dataclass(frozen=True, slots=True)
class ReviewDisplay:
    display_id: str
    kind: ReviewDisplayKind
    title: str
    location: ReviewDisplayLocation
    source_file: str
    source_object_ids: tuple[str, ...] = ()
    caption: str | None = None
    rationale: str | None = None

    def __post_init__(self) -> None:
        for name in ("display_id", "title", "source_file"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        object.__setattr__(
            self,
            "source_object_ids",
            require_unique(self.source_object_ids, "display source object ids"),
        )
        for name in ("caption", "rationale"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_text(value, name))


@dataclass(frozen=True, slots=True)
class SystematicReviewDraft:
    schema_version: Literal["systematic-review-draft.v3"]
    document_maturity: Literal[ReviewDocumentMaturity.SCIENTIFIC_DRAFT]
    title: str
    review_path: ReviewPath
    sections: tuple[SystematicReviewSectionDraft, ...]
    displays: tuple[ReviewDisplay, ...] = ()
    method_decisions: tuple[ReportingMethodDecision, ...] = ()
    issues: tuple[ArtifactIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != "systematic-review-draft.v3":
            raise ValueError("unsupported Systematic Review draft schema")
        object.__setattr__(self, "title", require_text(self.title, "review.title"))
        names = tuple(item.name for item in self.sections)
        if set(names) != set(ReviewSectionName) or len(names) != len(ReviewSectionName):
            raise ValueError("Systematic Review draft requires every section exactly once")
        require_unique(
            tuple(item.decision_id for item in self.method_decisions),
            "reporting method decision ids",
        )
        require_unique(
            tuple(item.display_id for item in self.displays),
            "review display ids",
        )
        if any(
            item.basis_status is MethodologyBasisStatus.UNRESOLVED
            for item in self.method_decisions
        ):
            raise ValueError(
                "completed Systematic Review draft cannot contain unresolved methodology"
            )


@dataclass(frozen=True, slots=True)
class SystematicReviewReportingInput:
    protocol: ProtocolDraft
    evidence_package: SystematicReviewEvidencePackageRef
