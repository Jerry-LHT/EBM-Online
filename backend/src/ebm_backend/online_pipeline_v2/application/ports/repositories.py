"""Application-facing repositories for task packages and resumable work."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    CompletedArtifactRef,
)
from ebm_backend.online_pipeline_v2.domain.grade import (
    GradeEvidencePackageRef,
    GradeSummaryOfFindingsArtifact,
)
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasDocumentV4,
    RiskOfBiasPackageRef,
    RiskOfBiasReviewProcess,
)
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchArtifact,
    SearchPackageRef,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    Report,
    SelectionCollections,
    SelectionPackageRef,
)
from ebm_backend.online_pipeline_v2.domain.study_characteristics import (
    CharacteristicsReportEvidenceObservation,
    StudyCharacteristicsMethodologyAuthority,
    DiscoveredReportLink,
    StudyCharacteristicsPackageRef,
    StudyCharacteristicsRecord,
)
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    SystematicReviewDraft,
    SystematicReviewEvidencePackageRef,
)


@dataclass(frozen=True, slots=True)
class SelectionAgentSnapshot:
    role: str
    output: object
    artifacts: Mapping[str, bytes]


@dataclass(frozen=True, slots=True)
class CharacteristicsReviewSnapshot:
    role: str
    run_id: str
    output: object
    artifacts: Mapping[str, bytes]


class SearchPackageRepository(Protocol):
    def persist(
        self,
        *,
        review_id: str,
        protocol_version: str,
        artifact: EvidenceSearchArtifact,
    ) -> SearchPackageRef: ...
    def validate(self, package_ref: SearchPackageRef) -> dict[str, Any]: ...
    def resolve_manifest(self, package_ref: SearchPackageRef) -> Path: ...
    def package_directory(self, package_ref: SearchPackageRef) -> Path: ...
    def load(self, package_ref: SearchPackageRef) -> EvidenceSearchArtifact: ...


class SelectionPackageRepository(Protocol):
    def persist(
        self,
        *,
        review_id: str,
        protocol_version: str,
        collections: SelectionCollections,
        agent_runs: Sequence[SelectionAgentSnapshot],
    ) -> SelectionPackageRef: ...
    def validate(self, package_ref: SelectionPackageRef) -> dict[str, Any]: ...
    def resolve_manifest(self, package_ref: SelectionPackageRef) -> Path: ...


class CharacteristicsPackageRepository(Protocol):
    def persist(
        self,
        *,
        review_id: str,
        protocol_version: str,
        studies: Sequence[StudyCharacteristicsRecord],
        discovered_reports: Sequence[Report],
        discovered_report_links: Sequence[DiscoveredReportLink],
        report_evidence: Sequence[CharacteristicsReportEvidenceObservation],
        issues: Sequence[ArtifactIssue],
        review_runs: Sequence[CharacteristicsReviewSnapshot],
        methodology_authorities: Sequence[StudyCharacteristicsMethodologyAuthority],
    ) -> StudyCharacteristicsPackageRef: ...
    def validate(
        self,
        package_ref: StudyCharacteristicsPackageRef,
    ) -> dict[str, Any]: ...
    def resolve_manifest(
        self,
        package_ref: StudyCharacteristicsPackageRef,
    ) -> Path: ...


class RiskOfBiasPackageRepository(Protocol):
    def persist(
        self,
        *,
        review_id: str,
        protocol_version: str,
        document: RiskOfBiasDocumentV4,
        issues: Sequence[ArtifactIssue],
        review_process: RiskOfBiasReviewProcess,
    ) -> RiskOfBiasPackageRef: ...
    def validate(self, package_ref: RiskOfBiasPackageRef) -> dict[str, Any]: ...
    def resolve_manifest(self, package_ref: RiskOfBiasPackageRef) -> Path: ...


class WorkSession(Protocol):
    work_id: str
    root: Path
    binding: Mapping[str, Any]
    checkpoint_path: Path | None


class CompletedArtifactSnapshot(Protocol):
    artifact: CompletedArtifactRef


class ResultsArtifactSnapshot(CompletedArtifactSnapshot, Protocol):
    ledger_path: Path
    public_directory: Path


class StudyDataCollectionArtifactSnapshot(CompletedArtifactSnapshot, Protocol):
    document_path: Path
    public_directory: Path
    document: Mapping[str, Any]


class SynthesisArtifactSnapshot(CompletedArtifactSnapshot, Protocol):
    document_path: Path
    public_directory: Path


class GradeEvidenceSnapshot(Protocol):
    package: GradeEvidencePackageRef
    directory: Path


class StudyResultsRepository(Protocol):
    def begin(
        self,
        *,
        binding: Mapping[str, Any],
        work_id: str | None,
    ) -> WorkSession: ...
    def checkpoint(self, session: WorkSession, content: bytes) -> Path: ...
    def complete(
        self,
        session: WorkSession,
        *,
        authoritative: bytes,
        public_files: Mapping[str, bytes],
        projection_summary: Mapping[str, Any],
        counts: Mapping[str, int],
        warnings: tuple[str, ...],
        supersedes_artifact_id: str | None = None,
    ) -> ResultsArtifactSnapshot: ...
    def resolve(self, artifact_id: str) -> ResultsArtifactSnapshot: ...
    def release(self, session: WorkSession) -> None: ...


class StudyDataCollectionArtifactRepository(Protocol):
    def resolve(
        self,
        artifact: CompletedArtifactRef | str,
    ) -> StudyDataCollectionArtifactSnapshot: ...


class EvidenceSynthesisRepository(Protocol):
    def begin(
        self,
        *,
        binding: Mapping[str, Any],
        work_id: str | None,
    ) -> WorkSession: ...
    def checkpoint(self, session: WorkSession, content: bytes) -> Path: ...
    def complete(
        self,
        session: WorkSession,
        *,
        authoritative: bytes,
        public_files: Mapping[str, bytes],
        counts: Mapping[str, int],
        warnings: tuple[str, ...],
        supersedes_artifact_id: str | None = None,
    ) -> SynthesisArtifactSnapshot: ...
    def resolve(self, artifact_id: str) -> SynthesisArtifactSnapshot: ...
    def release(self, session: WorkSession) -> None: ...


class GradeEvidenceRepository(Protocol):
    def persist(
        self,
        *,
        package_id: str,
        review_id: str,
        protocol_version: str,
        files: Mapping[str, bytes],
    ) -> GradeEvidenceSnapshot: ...
    def resolve(self, package_id: str) -> GradeEvidenceSnapshot: ...


class GradeArtifactRepository(Protocol):
    def persist(
        self,
        *,
        binding: Mapping[str, Any],
        artifact: GradeSummaryOfFindingsArtifact,
        warnings: tuple[str, ...],
    ) -> CompletedArtifactRef: ...


class SystematicReviewEvidenceSnapshot(Protocol):
    package: SystematicReviewEvidencePackageRef
    directory: Path


class SystematicReviewEvidenceRepository(Protocol):
    def resolve(self, package_id: str) -> SystematicReviewEvidenceSnapshot: ...


class SystematicReviewArtifactRepository(Protocol):
    def persist(
        self,
        *,
        binding: Mapping[str, str],
        draft: SystematicReviewDraft,
        evidence: SystematicReviewEvidenceSnapshot,
        warnings: tuple[str, ...],
    ) -> CompletedArtifactRef: ...


class WorkBindingConflict(ValueError):
    """A work id belongs to different immutable inputs."""


class WorkExecutionConflict(RuntimeError):
    """A work id already has an active execution."""
