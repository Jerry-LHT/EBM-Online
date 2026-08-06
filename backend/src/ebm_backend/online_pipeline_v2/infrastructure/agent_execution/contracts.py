"""Infrastructure contracts for one configured Agent task execution.

These types are intentionally outside Application.  They describe the
provider/runtime boundary after a task-specific Infrastructure spec has
translated the business command.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import re
from typing import Any, Generic, Mapping, Protocol, TypeVar

from pydantic import ValidationError

from ebm_backend.online_pipeline_v2.domain.common import DomainValidationError


_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
OutputT = TypeVar("OutputT")


class TaskProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class TaskAccessMode(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"


@dataclass(frozen=True, slots=True)
class WebAccessPolicy:
    """Hidden execution constraints that must never enter model-visible input."""

    enabled: bool = True
    blocked_urls: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    blocked_identifiers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WebPolicyViolation:
    source: str
    match_type: str
    rule_digest: str
    observed_digest: str


@dataclass(frozen=True, slots=True)
class WebAccessAudit:
    enabled: bool
    potential_contamination: bool
    inspected_value_count: int
    violations: tuple[WebPolicyViolation, ...]


@dataclass(frozen=True, slots=True)
class TaskRunRequest:
    """One technical Agent attempt after task binding."""

    run_id: str
    prompt: str
    input_data: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    input_artifacts: Mapping[str, Path] = field(default_factory=dict)
    output_artifacts: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 900.0
    access_mode: TaskAccessMode = TaskAccessMode.WORKSPACE_WRITE
    enable_workspace_network: bool = False
    enable_web_search: bool = True
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    task_name: str = "unknown"
    run_record_digest_output_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _NAME_PATTERN.fullmatch(self.run_id):
            raise ValueError("task run_id is invalid")
        if not self.prompt.strip():
            raise ValueError("task prompt must not be blank")
        if self.timeout_seconds <= 0:
            raise ValueError("task timeout_seconds must be positive")
        if (
            self.enable_workspace_network
            and self.access_mode is not TaskAccessMode.WORKSPACE_WRITE
        ):
            raise ValueError("workspace network requires workspace-write access")


@dataclass(frozen=True, slots=True)
class TaskEvent:
    event_type: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TaskSkillSnapshot:
    name: str
    sha256: str


@dataclass(frozen=True, slots=True)
class TaskOutputArtifact:
    name: str
    relative_path: str
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class TaskRunResult:
    provider: TaskProvider
    model: str
    run_id: str
    session_id: str | None
    output: Mapping[str, Any]
    events: tuple[TaskEvent, ...]
    stderr: str
    duration_seconds: float
    web_access_audit: WebAccessAudit
    skill_snapshots: tuple[TaskSkillSnapshot, ...]
    output_artifacts: Mapping[str, TaskOutputArtifact] = field(
        default_factory=dict
    )
    retained_workspace: Path | None = None


class OutputAdapter(Protocol[OutputT]):
    def validate_python(self, value: object) -> OutputT: ...


@dataclass(frozen=True, slots=True)
class TaskExecution(Generic[OutputT]):
    result: TaskRunResult
    output: OutputT


class TaskExecutorPort(Protocol):
    """Execute attempts for the single professional task bound at composition."""

    def execute(
        self,
        request: TaskRunRequest,
        *,
        output_adapter: OutputAdapter[OutputT],
        error_context: str,
    ) -> TaskExecution[OutputT]: ...


class TaskExecutionError(RuntimeError):
    """A configured professional task could not execute successfully."""


class TaskOutputError(TaskExecutionError):
    """A task attempt did not satisfy its deterministic output contract."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "task_output_invalid",
        stage: str | None = None,
        artifact: str | None = None,
        location: str | None = None,
        contract_version: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.artifact = artifact
        self.location = location
        self.contract_version = contract_version

    def diagnostic(self) -> dict[str, str]:
        """Return a bounded diagnostic without rejected input values."""

        message = (
            str(self)[:2_000]
            if self.stage is not None
            else "Task output did not satisfy its deterministic contract."
        )
        diagnostic = {
            "error_code": self.code,
            "message": message,
        }
        for key, value in (
            ("stage", self.stage),
            ("artifact", self.artifact),
            ("location", self.location),
            ("contract_version", self.contract_version),
        ):
            if value is not None:
                diagnostic[key] = value[:500]
        return diagnostic


def validate_task_output(
    value: object,
    *,
    output_adapter: OutputAdapter[OutputT],
    error_context: str,
) -> OutputT:
    try:
        return output_adapter.validate_python(value)
    except (
        ValidationError,
        DomainValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise TaskOutputError(f"{error_context}: {exc}") from exc
