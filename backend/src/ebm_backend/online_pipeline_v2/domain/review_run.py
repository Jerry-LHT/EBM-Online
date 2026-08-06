"""Persistent end-to-end Review Run state."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping

from .common import ArtifactIssue, Provenance, require_text
from .protocol import ProtocolStandards, ProtocolTemplate, TopicKind


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_ATTENTION = "needs_attention"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


class ReviewStage(StrEnum):
    Q2PROTOCOL = "q2protocol"
    EVIDENCE_SEARCH = "evidence_search"
    STUDY_SELECTION = "study_selection"
    STUDY_DATA_COLLECTION = "study_data_collection"
    RISK_OF_BIAS = "risk_of_bias"
    EVIDENCE_SYNTHESIS = "evidence_synthesis"
    GRADE_SUMMARY_OF_FINDINGS = "grade_summary_of_findings"
    SYSTEMATIC_REVIEW_REPORTING = "systematic_review_reporting"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class CreateReviewRun:
    review_id: str
    protocol_version: str
    topic_text: str
    topic_kind: TopicKind
    provenance: tuple[Provenance, ...]
    scope_notes: tuple[str, ...] = ()
    background_sources: tuple[Provenance, ...] = ()
    standards: ProtocolStandards | None = None
    template: ProtocolTemplate | None = None

    def __post_init__(self) -> None:
        for name in ("review_id", "protocol_version", "topic_text"):
            object.__setattr__(
                self,
                name,
                require_text(getattr(self, name), name),
            )
        if not self.provenance:
            raise ValueError("Review Run requires provenance")


@dataclass(frozen=True, slots=True)
class ReviewRunEvent:
    sequence: int
    occurred_at: str
    stage: ReviewStage
    status: ReviewRunStatus
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ReviewRun:
    run_id: str
    request: CreateReviewRun
    status: ReviewRunStatus
    stage: ReviewStage
    created_at: str
    updated_at: str
    stage_attempts: Mapping[str, int] = field(default_factory=dict)
    artifacts: Mapping[str, object] = field(default_factory=dict)
    work_ids: Mapping[str, str] = field(default_factory=dict)
    issues: tuple[ArtifactIssue, ...] = ()
    diagnostic: Mapping[str, str] | None = None
    events: tuple[ReviewRunEvent, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", require_text(self.run_id, "run_id"))
    def event(
        self,
        *,
        code: str,
        message: str,
        status: ReviewRunStatus | None = None,
        stage: ReviewStage | None = None,
    ) -> "ReviewRun":
        next_status = status or self.status
        next_stage = stage or self.stage
        now = utc_now()
        event = ReviewRunEvent(
            sequence=len(self.events) + 1,
            occurred_at=now,
            stage=next_stage,
            status=next_status,
            code=require_text(code, "event.code"),
            message=require_text(message, "event.message"),
        )
        return replace(
            self,
            status=next_status,
            stage=next_stage,
            updated_at=now,
            events=self.events + (event,),
        )
