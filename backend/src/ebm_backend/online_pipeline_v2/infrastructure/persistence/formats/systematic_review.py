"""Structured Agent output contract for Systematic Review composition."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from ebm_backend.online_pipeline_v2.domain.common import ArtifactIssue, ArtifactStatus
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    SystematicReviewDraft,
)


class SystematicReviewAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        ArtifactStatus.COMPLETED,
        ArtifactStatus.PARTIAL,
        ArtifactStatus.BLOCKED,
    ]
    artifact: SystematicReviewDraft | None
    issues: tuple[ArtifactIssue, ...]
    blocker: str | None
    warnings: tuple[str, ...]

    @model_validator(mode="after")
    def validate_status(self) -> "SystematicReviewAgentOutput":
        if self.status is ArtifactStatus.COMPLETED:
            if self.artifact is None:
                raise ValueError("completed output requires artifact")
            if self.blocker is not None:
                raise ValueError("completed output must not contain blocker")
            return self
        if self.artifact is not None:
            raise ValueError("partial or blocked output must not contain artifact")
        if self.status is ArtifactStatus.BLOCKED:
            if not (self.blocker and self.blocker.strip()):
                raise ValueError("blocked output requires blocker")
        elif self.blocker is not None:
            raise ValueError("partial output must not contain blocker")
        return self


_OUTPUT = TypeAdapter(SystematicReviewAgentOutput)


def systematic_review_agent_output_adapter() -> TypeAdapter[SystematicReviewAgentOutput]:
    return _OUTPUT

