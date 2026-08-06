"""Shared artifact, provenance, and validation types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Mapping, TypeVar


class DomainValidationError(ValueError):
    """Raised when cross-field or cross-artifact domain invariants fail."""


def require_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainValidationError(f"{field_name} must not be blank")
    return normalized


def require_unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(require_text(value, field_name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise DomainValidationError(f"{field_name} must contain unique values")
    return normalized


class TaskName(StrEnum):
    Q2PROTOCOL = "q2protocol"
    EVIDENCE_SEARCH = "evidence_search"
    STUDY_SELECTION = "study_selection"
    STUDY_DATA_COLLECTION = "study_data_collection"
    RISK_OF_BIAS = "risk_of_bias"
    EVIDENCE_SYNTHESIS = "evidence_synthesis"
    GRADE_SUMMARY_OF_FINDINGS = "grade_summary_of_findings"
    SYSTEMATIC_REVIEW_REPORTING = "systematic_review_reporting"


class ArtifactStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class IssueSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class TaskWorkStatus(StrEnum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class Provenance:
    source_id: str
    source_type: str
    locator: str | None = None
    excerpt: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", require_text(self.source_id, "source_id"))
        object.__setattr__(
            self,
            "source_type",
            require_text(self.source_type, "source_type"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactIssue:
    code: str
    message: str
    severity: IssueSeverity = IssueSeverity.WARNING
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", require_text(self.code, "issue.code"))
        object.__setattr__(
            self,
            "message",
            require_text(self.message, "issue.message"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactFile:
    name: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_text(self.name, "file.name"))
        object.__setattr__(self, "sha256", require_text(self.sha256, "file.sha256"))
        if self.size_bytes < 0:
            raise DomainValidationError("file.size_bytes must be non-negative")


@dataclass(frozen=True, slots=True)
class CompletedArtifactRef:
    artifact_id: str
    schema_version: str
    review_id: str
    protocol_version: str
    task: TaskName
    content_digest: str
    files: tuple[ArtifactFile, ...]
    counts: Mapping[str, int]
    warnings: tuple[str, ...] = ()
    supersedes_artifact_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "artifact_id",
            "schema_version",
            "review_id",
            "protocol_version",
            "content_digest",
        ):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"artifact.{name}"),
            )
        if not self.files:
            raise DomainValidationError("completed artifact requires files")
        require_unique(tuple(item.name for item in self.files), "artifact file names")
        for name, value in self.counts.items():
            require_text(name, "artifact count name")
            if not isinstance(value, int) or value < 0:
                raise DomainValidationError(
                    "artifact counts must be non-negative integers"
                )
        object.__setattr__(
            self,
            "warnings",
            require_unique(self.warnings, "artifact warnings"),
        )
        if self.supersedes_artifact_id is not None:
            object.__setattr__(
                self,
                "supersedes_artifact_id",
                require_text(
                    self.supersedes_artifact_id,
                    "artifact.supersedes_artifact_id",
                ),
            )


@dataclass(frozen=True, slots=True)
class UpstreamArtifactRef:
    artifact_id: str
    schema_version: str
    task: TaskName
    content_digest: str

    def __post_init__(self) -> None:
        for name in ("artifact_id", "schema_version", "content_digest"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"upstream_artifact.{name}"),
            )


@dataclass(frozen=True, slots=True)
class TaskWorkResult:
    status: TaskWorkStatus
    artifact: CompletedArtifactRef | None = None
    work_id: str | None = None
    progress: Mapping[str, int] = field(default_factory=dict)
    issues: tuple[ArtifactIssue, ...] = ()
    blocker: str | None = None

    def __post_init__(self) -> None:
        for name, value in self.progress.items():
            require_text(name, "progress name")
            if not isinstance(value, int) or value < 0:
                raise DomainValidationError(
                    "progress values must be non-negative integers"
                )
        if self.status is TaskWorkStatus.COMPLETED:
            if self.artifact is None:
                raise DomainValidationError(
                    "completed work result requires an artifact"
                )
            if self.work_id is not None or self.blocker is not None:
                raise DomainValidationError(
                    "completed work result must not expose work state"
                )
            return
        if self.artifact is not None:
            raise DomainValidationError(
                "incomplete or blocked work must not expose an artifact"
            )
        if self.work_id is None:
            raise DomainValidationError(
                "incomplete or blocked work requires work_id"
            )
        object.__setattr__(
            self,
            "work_id",
            require_text(self.work_id, "work_id"),
        )
        if self.status is TaskWorkStatus.BLOCKED:
            if self.blocker is None:
                raise DomainValidationError("blocked work requires blocker")
            object.__setattr__(
                self,
                "blocker",
                require_text(self.blocker, "blocker"),
            )
        elif self.blocker is not None:
            raise DomainValidationError(
                "only blocked work may expose a blocker"
            )


@dataclass(frozen=True, slots=True)
class TaskContext:
    review_id: str
    protocol_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "review_id",
            require_text(self.review_id, "review_id"),
        )
        object.__setattr__(
            self,
            "protocol_version",
            require_text(self.protocol_version, "protocol_version"),
        )


InputT = TypeVar("InputT")


@dataclass(frozen=True, slots=True)
class TaskInvocation(Generic[InputT]):
    context: TaskContext
    inputs: InputT
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        if not self.provenance:
            raise DomainValidationError("task invocation requires provenance")


ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True, slots=True)
class TaskCompletion(Generic[ArtifactT]):
    status: ArtifactStatus
    data: ArtifactT | None
    issues: tuple[ArtifactIssue, ...] = ()
    additional_provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        if self.status is ArtifactStatus.BLOCKED:
            if self.data is not None:
                raise DomainValidationError(
                    "blocked task completion must not contain data"
                )
            if not any(issue.severity is IssueSeverity.ERROR for issue in self.issues):
                raise DomainValidationError(
                    "blocked task completion requires at least one error issue"
                )
        elif self.data is None:
            raise DomainValidationError("non-blocked task completion requires data")
        if self.status is ArtifactStatus.PARTIAL:
            if not self.issues:
                raise DomainValidationError("partial task completion requires an issue")


@dataclass(frozen=True, slots=True)
class ArtifactEnvelope(Generic[ArtifactT]):
    artifact_id: str
    schema_version: str
    review_id: str
    protocol_version: str
    task: TaskName
    status: ArtifactStatus
    data: ArtifactT | None
    provenance: tuple[Provenance, ...]
    issues: tuple[ArtifactIssue, ...] = field(default_factory=tuple)
    content_digest: str | None = None
    upstream_artifacts: tuple[UpstreamArtifactRef, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        for name in ("artifact_id", "schema_version", "review_id", "protocol_version"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if self.content_digest is not None:
            object.__setattr__(
                self,
                "content_digest",
                require_text(self.content_digest, "content_digest"),
            )
        require_unique(
            tuple(item.artifact_id for item in self.upstream_artifacts),
            "upstream artifact ids",
        )
        if not self.provenance:
            raise DomainValidationError("artifact requires provenance")
        if self.status is ArtifactStatus.BLOCKED:
            if self.data is not None:
                raise DomainValidationError("blocked artifact must not contain data")
            if not any(issue.severity is IssueSeverity.ERROR for issue in self.issues):
                raise DomainValidationError(
                    "blocked artifact requires at least one error issue"
                )
        elif self.data is None:
            raise DomainValidationError("non-blocked artifact requires data")
        if self.status is ArtifactStatus.PARTIAL and not self.issues:
            raise DomainValidationError("partial artifact requires an issue")


def build_artifact(
    *,
    context: TaskContext,
    task: TaskName,
    data: ArtifactT | None,
    provenance: tuple[Provenance, ...],
    status: ArtifactStatus = ArtifactStatus.COMPLETED,
    issues: tuple[ArtifactIssue, ...] = (),
    content_digest: str | None = None,
    upstream_artifacts: tuple[UpstreamArtifactRef, ...] = (),
) -> ArtifactEnvelope[ArtifactT]:
    return ArtifactEnvelope(
        artifact_id=f"{context.review_id}:{task.value}:{context.protocol_version}",
        schema_version=f"{task.value}.v2",
        review_id=context.review_id,
        protocol_version=context.protocol_version,
        task=task,
        status=status,
        data=data,
        provenance=provenance,
        issues=issues,
        content_digest=content_digest,
        upstream_artifacts=upstream_artifacts,
    )
