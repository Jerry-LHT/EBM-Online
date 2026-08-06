"""Typed HTTP requests and public task-control responses."""

from __future__ import annotations

from typing import Generic, Mapping, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactIssue,
    ArtifactStatus,
    CompletedArtifactRef,
    Provenance,
    TaskName,
    TaskWorkStatus,
    UpstreamArtifactRef,
)
from ebm_backend.online_pipeline_v2.domain.grade import (
    GradeEvidencePackageRef,
    GradeProtocol,
)
from ebm_backend.online_pipeline_v2.domain.protocol import (
    ProtocolDraft,
    ProtocolStandards,
    ProtocolTemplate,
    TopicKind,
)
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasArtifact,
)
from ebm_backend.online_pipeline_v2.domain.review_run import CreateReviewRun
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchPublicArtifact,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    StudySelectionArtifact,
    StudySelectionProtocol,
)
from ebm_backend.online_pipeline_v2.domain.study_data_collection import (
    StudyDataCollectionProtocol,
)
from ebm_backend.online_pipeline_v2.domain.synthesis import (
    EvidenceSynthesisProtocol,
)
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    SystematicReviewEvidencePackageRef,
)


DataT = TypeVar("DataT")


class UpstreamArtifact(BaseModel, Generic[DataT]):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    review_id: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    task: TaskName
    status: ArtifactStatus
    data: DataT | None
    provenance: tuple[Provenance, ...] = Field(min_length=1)
    issues: tuple[ArtifactIssue, ...] = ()
    content_digest: str | None = None
    upstream_artifacts: tuple[UpstreamArtifactRef, ...] = ()


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    provenance: tuple[Provenance, ...] = Field(min_length=1)


class Q2ProtocolRequest(TaskRequest):
    topic_text: str = Field(min_length=1)
    topic_kind: TopicKind
    scope_notes: tuple[str, ...] = ()
    background_sources: tuple[Provenance, ...] = ()
    standards: ProtocolStandards | None = None
    template: ProtocolTemplate | None = None
    template: ProtocolTemplate | None = None


class CreateReviewRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    topic_text: str = Field(min_length=1)
    topic_kind: TopicKind
    provenance: tuple[Provenance, ...] = Field(min_length=1)
    scope_notes: tuple[str, ...] = ()
    background_sources: tuple[Provenance, ...] = ()
    standards: ProtocolStandards | None = None

    def to_domain(self) -> CreateReviewRun:
        return CreateReviewRun(**self.model_dump())


class EvidenceSearchRequest(TaskRequest):
    protocol: UpstreamArtifact[ProtocolDraft]


class StudySelectionRequest(TaskRequest):
    protocol: StudySelectionProtocol
    search: UpstreamArtifact[EvidenceSearchPublicArtifact]


class StudyDataCollectionRequest(TaskRequest):
    protocol_context: StudyDataCollectionProtocol
    selection: UpstreamArtifact[StudySelectionArtifact]


class RiskOfBiasRequest(TaskRequest):
    protocol: UpstreamArtifact[ProtocolDraft]
    selection: UpstreamArtifact[StudySelectionArtifact]
    study_data_collection: CompletedArtifactRef


class EvidenceSynthesisRequest(TaskRequest):
    protocol_context: EvidenceSynthesisProtocol
    study_data_collection: CompletedArtifactRef
    risk_of_bias: UpstreamArtifact[RiskOfBiasArtifact]
    work_id: str | None = Field(default=None, min_length=1)


class GradeSummaryOfFindingsRequest(TaskRequest):
    protocol_context: GradeProtocol
    evidence_package: GradeEvidencePackageRef


class SystematicReviewReportingRequest(TaskRequest):
    protocol: ProtocolDraft
    evidence_package: SystematicReviewEvidencePackageRef


class ArtifactResponse(BaseModel, Generic[DataT]):
    model_config = ConfigDict(from_attributes=True)

    artifact_id: str
    schema_version: str
    review_id: str
    protocol_version: str
    task: TaskName
    status: ArtifactStatus
    data: DataT | None
    provenance: tuple[Provenance, ...]
    issues: tuple[ArtifactIssue, ...]
    content_digest: str | None = None
    upstream_artifacts: tuple[UpstreamArtifactRef, ...] = ()


class TaskWorkResponse(BaseModel):
    """Control metadata only; scientific payload stays in its artifact bundle."""

    model_config = ConfigDict(from_attributes=True)

    status: TaskWorkStatus
    artifact: CompletedArtifactRef | None = None
    work_id: str | None = None
    progress: Mapping[str, int] = Field(default_factory=dict)
    issues: tuple[ArtifactIssue, ...] = ()
    blocker: str | None = None


Q2ProtocolResponse = ArtifactResponse[ProtocolDraft]
EvidenceSearchResponse = ArtifactResponse[EvidenceSearchPublicArtifact]
StudySelectionResponse = ArtifactResponse[StudySelectionArtifact]
RiskOfBiasResponse = ArtifactResponse[RiskOfBiasArtifact]
GradeSummaryOfFindingsResponse = TaskWorkResponse
