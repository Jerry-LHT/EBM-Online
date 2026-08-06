"""Application-owned immutable binding for a GRADE execution."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GradeWorkBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str
    protocol_version: str
    protocol_digest: str
    evidence_package_id: str
    evidence_package_digest: str
