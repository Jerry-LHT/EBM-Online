"""Provider-neutral technical contracts for local CLI execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

from .web_access_policy import WebAccessAudit, WebAccessPolicy


_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


class AgentProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class AgentExecutionStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    CONFIGURATION_ERROR = "configuration_error"


class AgentAccessMode(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"


class WorkspaceRetention(StrEnum):
    NEVER = "never"
    ON_FAILURE = "on_failure"
    ALWAYS = "always"


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    run_id: str
    prompt: str
    input_data: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    skill_paths: tuple[Path, ...]
    input_artifacts: Mapping[str, Path] = field(default_factory=dict)
    output_artifacts: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 900.0
    access_mode: AgentAccessMode = AgentAccessMode.WORKSPACE_WRITE
    enable_workspace_network: bool = False
    enable_web_search: bool = True
    web_access_policy: WebAccessPolicy = field(default_factory=WebAccessPolicy)
    task_name: str = "unknown"
    run_record_digest_output_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _RUN_ID_PATTERN.fullmatch(self.run_id):
            raise ValueError(
                "run_id must use 1-128 letters, digits, dots, underscores, "
                "or hyphens"
            )
        if not self.prompt.strip():
            raise ValueError("prompt must not be blank")
        if not isinstance(self.input_data, Mapping):
            raise TypeError("input_data must be a mapping")
        if not isinstance(self.output_schema, Mapping):
            raise TypeError("output_schema must be a mapping")
        if not self.skill_paths:
            raise ValueError("at least one Skill is required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(
            self,
            "skill_paths",
            tuple(Path(path).expanduser().resolve() for path in self.skill_paths),
        )
        normalized_artifacts: dict[str, Path] = {}
        for name, path in self.input_artifacts.items():
            if not _RUN_ID_PATTERN.fullmatch(name):
                raise ValueError(
                    "input artifact names must use letters, digits, dots, "
                    "underscores, or hyphens"
                )
            source = Path(path).expanduser().resolve()
            if not source.exists():
                raise ValueError(f"input artifact does not exist: {source}")
            normalized_artifacts[name] = source
        object.__setattr__(self, "input_artifacts", normalized_artifacts)
        normalized_outputs: dict[str, str] = {}
        for name, relative in self.output_artifacts.items():
            if not _RUN_ID_PATTERN.fullmatch(name):
                raise ValueError(
                    "output artifact names must use letters, digits, dots, "
                    "underscores, or hyphens"
                )
            path = Path(relative)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != "outputs"
                or path.as_posix() == "outputs/final.json"
            ):
                raise ValueError(
                    "output artifacts must be relative paths below outputs/ "
                    "and must not target outputs/final.json"
                )
            normalized_outputs[name] = path.as_posix()
        object.__setattr__(self, "output_artifacts", normalized_outputs)
        normalized_digest_fields = tuple(
            str(name).strip() for name in self.run_record_digest_output_fields
        )
        if any(not name for name in normalized_digest_fields):
            raise ValueError("run-record digest output field names must not be blank")
        if len(normalized_digest_fields) != len(set(normalized_digest_fields)):
            raise ValueError("run-record digest output fields must be unique")
        object.__setattr__(
            self,
            "run_record_digest_output_fields",
            normalized_digest_fields,
        )
        if (
            self.enable_workspace_network
            and self.access_mode is not AgentAccessMode.WORKSPACE_WRITE
        ):
            raise ValueError(
                "workspace network requires workspace-write access"
            )


@dataclass(frozen=True, slots=True)
class AgentEvent:
    event_type: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AgentSkillSnapshot:
    name: str
    sha256: str


@dataclass(frozen=True, slots=True)
class AgentOutputArtifact:
    name: str
    relative_path: str
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    provider: AgentProvider
    model: str
    run_id: str
    session_id: str | None
    output: Mapping[str, Any]
    events: tuple[AgentEvent, ...]
    stderr: str
    duration_seconds: float
    web_access_audit: WebAccessAudit
    skill_snapshots: tuple[AgentSkillSnapshot, ...]
    output_artifacts: Mapping[str, AgentOutputArtifact] = field(
        default_factory=dict
    )
    retained_workspace: Path | None = None


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    provider: AgentProvider
    binary: str
    version: str
    model: str
    structured_output: bool
    skill_loading: bool
    session_events: bool


class AgentRuntime(Protocol):
    provider: AgentProvider

    async def check(self) -> RuntimeCapabilities: ...

    async def run(self, request: AgentRunRequest) -> AgentRunResult: ...


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    argv: tuple[str, ...]
    cwd: Path
    stdin: str
    timeout_seconds: float
    environment_overrides: Mapping[str, str] = field(default_factory=dict)
    max_output_bytes: int = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class ProcessRunner(Protocol):
    async def run(self, spec: ProcessSpec) -> ProcessResult: ...
