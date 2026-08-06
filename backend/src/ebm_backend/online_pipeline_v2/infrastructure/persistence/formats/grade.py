"""Single structured-output and persisted-artifact contract for GRADE."""

from __future__ import annotations

import json
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, model_validator

from ebm_backend.online_pipeline_v2.domain.common import ArtifactIssue, TaskWorkStatus
from ebm_backend.online_pipeline_v2.domain.grade import (
    GRADEAssessment,
    GradeSummaryOfFindingsArtifact,
    GradeSummaryOfFindingsDraft,
    GradedGRADEAssessment,
    SummaryOfFindingsDocument,
)
class GradeArtifactError(ValueError):
    pass


class GradeAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[TaskWorkStatus.COMPLETED, TaskWorkStatus.BLOCKED]
    artifact: GradeSummaryOfFindingsDraft | None
    issues: tuple[ArtifactIssue, ...]
    blocker: str | None
    warnings: tuple[str, ...]

    @model_validator(mode="after")
    def validate_status(self) -> "GradeAgentOutput":
        if self.status is TaskWorkStatus.COMPLETED:
            if self.artifact is None:
                raise ValueError("completed output requires artifact")
            if self.blocker is not None:
                raise ValueError("completed output must not contain blocker")
            return self
        if self.artifact is not None:
            raise ValueError("unfinished output must not contain completed artifact")
        if self.status is TaskWorkStatus.BLOCKED:
            if not (self.blocker and self.blocker.strip()):
                raise ValueError("blocked output requires blocker")
        elif self.blocker is not None:
            raise ValueError("only blocked output may contain blocker")
        return self


_AGENT_OUTPUT = TypeAdapter(GradeAgentOutput)
_ASSESSMENT = TypeAdapter(GRADEAssessment)
_SOF = TypeAdapter(SummaryOfFindingsDocument)


def grade_agent_output_adapter() -> TypeAdapter[GradeAgentOutput]:
    return _AGENT_OUTPUT


def parse_evidence_profiles(content: bytes) -> tuple[GRADEAssessment, ...]:
    profiles: list[GRADEAssessment] = []
    line_number = 0
    try:
        text = content.decode("utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            profiles.append(_ASSESSMENT.validate_python(value))
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise GradeArtifactError(
            f"evidence-profiles.jsonl is invalid at line {line_number}: {exc}"
        ) from exc
    if not profiles:
        raise GradeArtifactError("evidence-profiles.jsonl must not be empty")
    ids = [item.evidence_body_id for item in profiles]
    if len(ids) != len(set(ids)):
        raise GradeArtifactError("evidence profile ids must be unique")
    return tuple(profiles)


def parse_sof(content: bytes) -> SummaryOfFindingsDocument:
    try:
        value = json.loads(content.decode("utf-8"))
        document = _SOF.validate_python(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise GradeArtifactError(f"summary-of-findings.json is invalid: {exc}") from exc
    table_ids = [table.table_id for table in document.tables]
    if len(table_ids) != len(set(table_ids)):
        raise GradeArtifactError("Summary of Findings table ids must be unique")
    return document


def serialize_grade_artifact(
    artifact: GradeSummaryOfFindingsArtifact,
) -> tuple[bytes, bytes]:
    profiles = b"".join(
        _ASSESSMENT.dump_json(profile) + b"\n"
        for profile in artifact.evidence_profiles
    )
    sof = _SOF.dump_json(
        SummaryOfFindingsDocument(
            method_decisions=artifact.method_decisions,
            tables=artifact.summary_of_findings,
        )
    ) + b"\n"
    validate_grade_artifact(profiles, sof)
    return profiles, sof


def validate_grade_artifact(
    profiles_content: bytes,
    sof_content: bytes,
) -> Mapping[str, int]:
    profiles = parse_evidence_profiles(profiles_content)
    document = parse_sof(sof_content)
    by_id = {item.evidence_body_id: item for item in profiles}
    row_ids: list[str] = []
    for table in document.tables:
        for row in table.rows:
            row_ids.append(row.evidence_body_id)
            profile = by_id.get(row.evidence_body_id)
            if profile is None:
                raise GradeArtifactError("SoF row has no evidence profile")
            expected_certainty = (
                profile.final_certainty
                if isinstance(profile, GradedGRADEAssessment)
                else None
            )
            if expected_certainty is not row.certainty:
                raise GradeArtifactError(
                    "SoF row certainty does not match its evidence profile"
                )
    if set(row_ids) != set(by_id):
        raise GradeArtifactError(
            "every evidence profile must appear exactly once in a SoF table"
        )
    if len(row_ids) != len(set(row_ids)):
        raise GradeArtifactError("evidence body appears in more than one SoF row")
    return {
        "evidence_profiles": len(profiles),
        "method_decisions": len(document.method_decisions),
        "sof_tables": len(document.tables),
        "sof_rows": len(row_ids),
    }
