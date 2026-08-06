"""Framework-independent domain contracts for Online Pipeline v2."""

from .common import (
    ArtifactEnvelope,
    ArtifactIssue,
    ArtifactStatus,
    DomainValidationError,
    IssueSeverity,
    Provenance,
    TaskCompletion,
    TaskContext,
    TaskInvocation,
    TaskName,
    UpstreamArtifactRef,
)

__all__ = [
    "ArtifactEnvelope",
    "ArtifactIssue",
    "ArtifactStatus",
    "DomainValidationError",
    "IssueSeverity",
    "Provenance",
    "TaskCompletion",
    "TaskContext",
    "TaskInvocation",
    "TaskName",
    "UpstreamArtifactRef",
]
