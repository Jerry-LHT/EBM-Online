"""Stable technical failures produced by Agent Runtime."""

from __future__ import annotations

from pathlib import Path

from .contracts import AgentProvider


class AgentRuntimeError(RuntimeError):
    """Base class for Agent Runtime technical failures."""

    retained_workspace: Path | None = None


class AgentConfigurationError(AgentRuntimeError):
    """Credentials or runtime policy are invalid."""


class AgentProviderMismatchError(AgentConfigurationError):
    def __init__(
        self,
        *,
        expected: AgentProvider,
        actual: AgentProvider,
    ) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"{expected.value} runtime cannot use {actual.value} credentials"
        )


class AgentCliNotFoundError(AgentRuntimeError):
    def __init__(self, binary: str) -> None:
        self.binary = binary
        super().__init__(f"Agent CLI executable was not found: {binary}")


class AgentCliCapabilityError(AgentRuntimeError):
    def __init__(
        self,
        *,
        provider: AgentProvider,
        missing_flags: tuple[str, ...],
    ) -> None:
        self.provider = provider
        self.missing_flags = missing_flags
        super().__init__(
            f"{provider.value} CLI is missing required flags: "
            f"{', '.join(missing_flags)}"
        )


class AgentAuthenticationError(AgentRuntimeError):
    """The configured CLI credential was rejected."""


class AgentProcessError(AgentRuntimeError):
    def __init__(
        self,
        *,
        provider: AgentProvider,
        returncode: int,
        stderr: str,
    ) -> None:
        self.provider = provider
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"{provider.value} CLI exited with status {returncode}: {stderr}"
        )


class AgentProcessTimeoutError(AgentRuntimeError):
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Agent CLI exceeded its {timeout_seconds:g}s timeout"
        )


class AgentProcessCancelledError(AgentRuntimeError):
    """The caller cancelled an active Agent CLI process."""


class AgentOutputTooLargeError(AgentRuntimeError):
    def __init__(self, max_output_bytes: int) -> None:
        self.max_output_bytes = max_output_bytes
        super().__init__(
            f"Agent CLI output exceeded {max_output_bytes} bytes"
        )


class AgentOutputError(AgentRuntimeError):
    """The CLI did not produce valid structured output."""


class AgentOutputSchemaError(AgentOutputError):
    """The supplied JSON Schema or final output is invalid."""


class AgentSkillError(AgentRuntimeError):
    """A Skill package is invalid or unsafe to stage."""


class AgentWorkspaceError(AgentRuntimeError):
    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        super().__init__(f"Agent workspace error at {path}: {message}")

