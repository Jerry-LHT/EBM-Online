"""Evidence Search domain types.

The search task records source-level search facts and bibliographic Records.
Record consolidation, screening, Report identification, and Study selection
belong to the downstream Study Selection task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .common import DomainValidationError, Provenance, require_text, require_unique
from .protocol import ProtocolDraft


class SearchRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class EvidenceSearchMode(StrEnum):
    INITIAL = "initial"
    SUPPLEMENTARY = "supplementary"


@dataclass(frozen=True, slots=True)
class ExternalIdentifier:
    scheme: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "scheme", require_text(self.scheme, "identifier.scheme")
        )
        object.__setattr__(self, "value", require_text(self.value, "identifier.value"))


@dataclass(frozen=True, slots=True)
class RecordRelation:
    """A source-reported relationship to another bibliographic record."""

    relation_type: str
    related_source_record_id: str | None = None
    citation: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relation_type",
            require_text(self.relation_type, "record_relation.relation_type"),
        )
        for name in ("related_source_record_id", "citation", "note"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    require_text(value, f"record_relation.{name}"),
                )


@dataclass(frozen=True, slots=True)
class SearchRun:
    search_run_id: str
    source_name: str
    platform: str
    query: str
    executed_at: str
    status: SearchRunStatus
    result_count: int
    provenance: tuple[Provenance, ...]
    retrieved_count: int
    status_reason: str | None
    search_narrative: str

    def __post_init__(self) -> None:
        for name in (
            "search_run_id",
            "source_name",
            "platform",
            "query",
            "executed_at",
            "search_narrative",
        ):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        for name in ("result_count", "retrieved_count"):
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")
        if self.retrieved_count > self.result_count:
            raise DomainValidationError(
                "retrieved_count cannot exceed result_count"
            )
        if self.status_reason is not None:
            object.__setattr__(
                self,
                "status_reason",
                require_text(self.status_reason, "status_reason"),
            )
        if self.status is not SearchRunStatus.SUCCEEDED and not self.status_reason:
            raise DomainValidationError(
                "an incomplete search run requires status_reason"
            )
        if not self.provenance:
            raise DomainValidationError("search run requires provenance")


@dataclass(frozen=True, slots=True)
class Record:
    record_id: str
    source_name: str
    platform: str
    source_record_id: str
    source_record_type: str = "other"
    source_data: dict[str, Any] = field(default_factory=dict)
    title: str | None = None
    citation: str | None = None
    abstract: str | None = None
    external_identifiers: tuple[ExternalIdentifier, ...] = ()
    publication_types: tuple[str, ...] = ()
    related_records: tuple[RecordRelation, ...] = ()
    locators: tuple[str, ...] = ()
    search_run_ids: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "record_id",
            "source_name",
            "platform",
            "source_record_id",
            "source_record_type",
        ):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        for key in self.source_data:
            require_text(key, "source_data key")
        for name in ("title", "citation", "abstract"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_text(value, name))
        object.__setattr__(
            self,
            "search_run_ids",
            require_unique(self.search_run_ids, "search_run_ids"),
        )
        object.__setattr__(
            self,
            "publication_types",
            require_unique(self.publication_types, "publication_types"),
        )
        relation_keys = tuple(
            (
                relation.relation_type,
                relation.related_source_record_id,
                relation.citation,
                relation.note,
            )
            for relation in self.related_records
        )
        if len(set(relation_keys)) != len(relation_keys):
            raise DomainValidationError("related_records must contain unique values")
        object.__setattr__(
            self,
            "locators",
            require_unique(self.locators, "locators"),
        )
        if not self.provenance:
            raise DomainValidationError("record requires provenance")


@dataclass(frozen=True, slots=True)
class SearchSummary:
    run_count: int
    source_count: int
    record_count: int

    def __post_init__(self) -> None:
        for name in ("run_count", "source_count", "record_count"):
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class SearchPackageRef:
    """Opaque reference to the persisted, potentially large Search Package."""

    package_id: str
    review_id: str
    protocol_version: str
    schema_version: str
    content_digest: str

    def __post_init__(self) -> None:
        for name in (
            "package_id",
            "review_id",
            "protocol_version",
            "schema_version",
            "content_digest",
        ):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), f"package_ref.{name}"),
            )


@dataclass(frozen=True, slots=True)
class SearchSourceStatus:
    """Compact public projection of one source execution."""

    search_run_id: str
    source_name: str
    platform: str
    executed_at: str
    status: SearchRunStatus
    result_count: int
    retrieved_count: int
    status_reason: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "search_run_id",
            "source_name",
            "platform",
            "executed_at",
        ):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        for name in ("result_count", "retrieved_count"):
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")
        if self.retrieved_count > self.result_count:
            raise DomainValidationError(
                "retrieved_count cannot exceed result_count"
            )
        if self.status_reason is not None:
            object.__setattr__(
                self,
                "status_reason",
                require_text(self.status_reason, "status_reason"),
            )
        if self.status is not SearchRunStatus.SUCCEEDED and not self.status_reason:
            raise DomainValidationError(
                "an incomplete source status requires status_reason"
            )


@dataclass(frozen=True, slots=True)
class EvidenceSearchPublicArtifact:
    """Lightweight public result; detailed runs and Records stay in the package."""

    sources: tuple[SearchSourceStatus, ...]
    summary: SearchSummary
    package_ref: SearchPackageRef

    def __post_init__(self) -> None:
        require_unique(
            tuple(source.search_run_id for source in self.sources),
            "source status search run ids",
        )
        if self.summary.run_count != len(self.sources):
            raise DomainValidationError(
                "summary.run_count does not match source statuses"
            )
        if self.summary.source_count != len(
            {source.source_name for source in self.sources}
        ):
            raise DomainValidationError(
                "summary.source_count does not match source statuses"
            )
        if self.package_ref.schema_version != "search-package.v2":
            raise DomainValidationError(
                "Evidence Search requires search-package.v2"
            )


def public_search_artifact(
    artifact: EvidenceSearchArtifact,
) -> EvidenceSearchPublicArtifact:
    if artifact.package_ref is None:
        raise DomainValidationError(
            "public Evidence Search output requires a persisted Search Package"
        )
    return EvidenceSearchPublicArtifact(
        sources=tuple(
            SearchSourceStatus(
                search_run_id=run.search_run_id,
                source_name=run.source_name,
                platform=run.platform,
                executed_at=run.executed_at,
                status=run.status,
                result_count=run.result_count,
                retrieved_count=run.retrieved_count,
                status_reason=run.status_reason,
            )
            for run in artifact.search_runs
        ),
        summary=artifact.summary,
        package_ref=artifact.package_ref,
    )


@dataclass(frozen=True, slots=True)
class EvidenceSearchArtifact:
    search_runs: tuple[SearchRun, ...]
    records: tuple[Record, ...]
    summary: SearchSummary
    package_ref: SearchPackageRef | None = None

    def __post_init__(self) -> None:
        run_ids = require_unique(
            tuple(run.search_run_id for run in self.search_runs),
            "search run ids",
        )
        record_ids = require_unique(
            tuple(record.record_id for record in self.records),
            "record ids",
        )
        run_set = set(run_ids)
        for record in self.records:
            if not record.search_run_ids:
                raise DomainValidationError("every record requires a Search Run")
            if not set(record.search_run_ids) <= run_set:
                raise DomainValidationError("record references an unknown search run")
            linked_runs = tuple(
                run
                for run in self.search_runs
                if run.search_run_id in record.search_run_ids
            )
            if any(
                record.source_name != run.source_name or record.platform != run.platform
                for run in linked_runs
            ):
                raise DomainValidationError(
                    "record source and platform must match its Search Runs"
                )
        for run in self.search_runs:
            linked_record_count = sum(
                run.search_run_id in record.search_run_ids
                for record in self.records
            )
            if run.retrieved_count != linked_record_count:
                raise DomainValidationError(
                    "search run retrieved_count does not match linked records"
                )
        if not run_ids:
            raise DomainValidationError(
                "search artifact requires at least one search run"
            )
        if self.summary.run_count != len(self.search_runs):
            raise DomainValidationError("summary.run_count does not match search runs")
        if self.summary.record_count != len(self.records):
            raise DomainValidationError("summary.record_count does not match records")
        if self.summary.source_count != len(
            {run.source_name for run in self.search_runs}
        ):
            raise DomainValidationError(
                "summary.source_count does not match search run sources"
            )


@dataclass(frozen=True, slots=True)
class EvidenceSearchInput:
    protocol: ProtocolDraft
    mode: EvidenceSearchMode = EvidenceSearchMode.INITIAL
    parent_package_ref: SearchPackageRef | None = None
    supplementary_reason: str | None = None
    evidence_gaps: tuple[str, ...] = ()
    candidate_leads: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode is EvidenceSearchMode.INITIAL and self.parent_package_ref is not None:
            raise DomainValidationError("initial Evidence Search cannot have a parent package")
        if self.mode is EvidenceSearchMode.SUPPLEMENTARY and self.parent_package_ref is None:
            raise DomainValidationError("supplementary Evidence Search requires a parent package")
        if self.mode is EvidenceSearchMode.SUPPLEMENTARY and not self.supplementary_reason:
            raise DomainValidationError("supplementary Evidence Search requires a reason")
        for name, values in (("evidence_gaps", self.evidence_gaps), ("candidate_leads", self.candidate_leads)):
            object.__setattr__(self, name, require_unique(tuple(require_text(v, name) for v in values), name))
