"""Shared mechanics for provider-specific CLI runtimes."""

from __future__ import annotations

from abc import ABC, abstractmethod
import os
from pathlib import Path
import sys
from typing import Mapping

from .contracts import (
    AgentEvent,
    AgentExecutionStatus,
    AgentOutputArtifact,
    AgentProvider,
    AgentRunRequest,
    AgentRunResult,
    AgentSkillSnapshot,
    ProcessResult,
    ProcessRunner,
    ProcessSpec,
    RuntimeCapabilities,
)
from .configuration import AgentRuntimeConfig
from .errors import (
    AgentAuthenticationError,
    AgentCliCapabilityError,
    AgentConfigurationError,
    AgentProcessCancelledError,
    AgentProcessError,
    AgentProcessTimeoutError,
    AgentProviderMismatchError,
    AgentRuntimeError,
)
from .process import SubprocessRunner
from .structured_output import validate_structured_output
from .workspace import PreparedWorkspace, WorkspaceManager
from .web_access_policy import audit_web_access
from .run_store import JsonRunStore
from .debug_store import DebugBundleStore


_DIAGNOSTIC_LIMIT = 8_000
_AUTH_ERROR_MARKERS = (
    "not logged in",
    "authentication",
    "invalid api key",
    "incorrect api key",
    "unauthorized",
    "401",
)


class CliAgentRuntime(ABC):
    provider: AgentProvider
    binary: str
    required_flags: tuple[str, ...]

    def __init__(
        self,
        config: AgentRuntimeConfig,
        *,
        process_runner: ProcessRunner | None = None,
        workspace_manager: WorkspaceManager | None = None,
        run_store: JsonRunStore | None = None,
        debug_store: DebugBundleStore | None = None,
    ) -> None:
        if config.provider is not self.provider:
            raise AgentProviderMismatchError(
                expected=self.provider,
                actual=config.provider,
            )
        self._config = config
        self._process_runner = process_runner or SubprocessRunner()
        self._workspace_manager = workspace_manager or WorkspaceManager()
        self._run_store = run_store
        self._debug_store = debug_store

    @property
    def model(self) -> str:
        return self._config.model

    async def check(self) -> RuntimeCapabilities:
        version = await self._process_runner.run(
            ProcessSpec(
                argv=(self.binary, "--version"),
                cwd=Path.cwd(),
                stdin="",
                timeout_seconds=15.0,
            )
        )
        if version.returncode != 0:
            raise self._process_error(version)
        help_texts: list[str] = []
        for argv in self._help_commands():
            result = await self._process_runner.run(
                ProcessSpec(
                    argv=argv,
                    cwd=Path.cwd(),
                    stdin="",
                    timeout_seconds=15.0,
                )
            )
            if result.returncode != 0:
                raise self._process_error(result)
            help_texts.extend((result.stdout, result.stderr))
        help_text = "\n".join(help_texts)
        missing = tuple(flag for flag in self.required_flags if flag not in help_text)
        if missing:
            raise AgentCliCapabilityError(
                provider=self.provider,
                missing_flags=missing,
            )
        return RuntimeCapabilities(
            provider=self.provider,
            binary=self.binary,
            version=version.stdout.strip() or version.stderr.strip(),
            model=self.model,
            structured_output=True,
            skill_loading=True,
            session_events=True,
        )

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        if self._run_store is not None:
            self._run_store.start(request)
        workspace: PreparedWorkspace | None = None
        process: ProcessResult | None = None
        events: tuple[AgentEvent, ...] = ()
        validated: Mapping[str, object] | None = None
        output_artifacts: Mapping[str, AgentOutputArtifact] = {}
        debug_bundle: Path | None = None
        if self._debug_store is not None:
            debug_bundle = self._start_debug_bundle(request)
        try:
            workspace = self._workspace_manager.prepare(
                request,
                provider=self.provider,
            )
            raw_process = await self._process_runner.run(
                ProcessSpec(
                    argv=self._command(request, workspace),
                    cwd=workspace.root,
                    stdin=self._prompt(request, workspace),
                    timeout_seconds=request.timeout_seconds,
                    environment_overrides=self._execution_environment(),
                )
            )
            process = self._redact_process_output(raw_process)
            if process.returncode != 0:
                raise self._process_error(process)
            output, events, session_id = self._parse_result(
                process,
                workspace,
            )
            validated = validate_structured_output(
                output,
                request.output_schema,
            )
            output_artifacts = self._workspace_manager.collect_output_artifacts(
                workspace,
                request,
            )
            web_audit = audit_web_access(
                request.web_access_policy,
                events=((event.event_type, event.payload) for event in events),
                output={
                    "structured_output": validated,
                    "output_artifacts": [
                        artifact.content.decode("utf-8", errors="replace")
                        for artifact in output_artifacts.values()
                    ],
                },
                stderr=process.stderr,
            )
        except AgentRuntimeError as exc:
            retained = (
                self._workspace_manager.release(workspace, succeeded=False)
                if workspace is not None
                else None
            )
            exc.retained_workspace = retained
            if self._run_store is not None:
                self._run_store.fail(
                    request,
                    status=_execution_status(exc),
                    error=exc,
                    retained_workspace=retained,
                    debug_bundle_path=debug_bundle,
                )
            self._fail_debug_bundle(
                request,
                debug_bundle,
                exc,
                status=_execution_status(exc),
                process=process,
                events=events,
                output=validated,
                output_artifacts=output_artifacts,
                retained_workspace=retained,
            )
            raise
        except Exception as exc:
            retained = (
                self._workspace_manager.release(workspace, succeeded=False)
                if workspace is not None
                else None
            )
            if self._run_store is not None:
                self._run_store.fail(
                    request,
                    status=AgentExecutionStatus.FAILED,
                    error=exc,
                    retained_workspace=retained,
                    debug_bundle_path=debug_bundle,
                )
            self._fail_debug_bundle(
                request,
                debug_bundle,
                exc,
                status=AgentExecutionStatus.FAILED,
                process=process,
                events=events,
                output=validated,
                output_artifacts=output_artifacts,
                retained_workspace=retained,
            )
            raise

        assert workspace is not None
        retained = self._workspace_manager.release(workspace, succeeded=True)
        result = AgentRunResult(
            provider=self.provider,
            model=self.model,
            run_id=request.run_id,
            session_id=session_id,
            output=validated,
            events=events,
            stderr=_bounded(process.stderr),
            duration_seconds=process.duration_seconds,
            web_access_audit=web_audit,
            skill_snapshots=tuple(
                AgentSkillSnapshot(
                    name=package.name,
                    sha256=package.sha256,
                )
                for package in workspace.staged_skills.packages
            ),
            output_artifacts=output_artifacts,
            retained_workspace=retained,
        )
        if self._run_store is not None:
            self._run_store.complete(
                request,
                result,
                debug_bundle_path=debug_bundle,
            )
        if self._debug_store is not None and debug_bundle is not None:
            try:
                self._debug_store.complete(
                    request,
                    result,
                    bundle=debug_bundle,
                    process=process,
                )
            except Exception:
                # Diagnostics must never change the Agent execution result.
                pass
        return result

    def _start_debug_bundle(self, request: AgentRunRequest) -> Path | None:
        assert self._debug_store is not None
        try:
            return self._debug_store.start(request)
        except Exception:
            return None

    def _fail_debug_bundle(
        self,
        request: AgentRunRequest,
        bundle: Path | None,
        error: BaseException,
        *,
        status: AgentExecutionStatus,
        process: ProcessResult | None,
        events: tuple[AgentEvent, ...],
        output: Mapping[str, object] | None,
        output_artifacts: Mapping[str, AgentOutputArtifact],
        retained_workspace: Path | None,
    ) -> None:
        if self._debug_store is None or bundle is None:
            return
        try:
            self._debug_store.fail(
                request,
                bundle=bundle,
                error=error,
                status=status,
                process=process,
                events=events,
                output=output,
                output_artifacts=output_artifacts,
                retained_workspace=retained_workspace,
            )
        except Exception:
            pass

    def _process_error(self, result: ProcessResult) -> AgentRuntimeError:
        diagnostic = _bounded(result.stderr or result.stdout)
        if any(marker in diagnostic.lower() for marker in _AUTH_ERROR_MARKERS):
            return AgentAuthenticationError(
                f"{self.provider.value} CLI authentication failed: {diagnostic}"
            )
        return AgentProcessError(
            provider=self.provider,
            returncode=result.returncode,
            stderr=diagnostic,
        )

    def _redact_process_output(self, result: ProcessResult) -> ProcessResult:
        secret = self._config.api_key
        return ProcessResult(
            returncode=result.returncode,
            stdout=result.stdout.replace(secret, "***"),
            stderr=result.stderr.replace(secret, "***"),
            duration_seconds=result.duration_seconds,
        )

    @abstractmethod
    def _help_commands(self) -> tuple[tuple[str, ...], ...]: ...

    @abstractmethod
    def _credential_environment(self) -> Mapping[str, str]: ...

    def _execution_environment(self) -> Mapping[str, str]:
        interpreter_directory = str(Path(sys.executable).parent)
        inherited_path = os.environ.get("PATH", "")
        return {
            **self._credential_environment(),
            "PATH": os.pathsep.join(
                value
                for value in (interpreter_directory, inherited_path)
                if value
            ),
        }

    @abstractmethod
    def _command(
        self,
        request: AgentRunRequest,
        workspace: PreparedWorkspace,
    ) -> tuple[str, ...]: ...

    @abstractmethod
    def _prompt(
        self,
        request: AgentRunRequest,
        workspace: PreparedWorkspace,
    ) -> str: ...

    @abstractmethod
    def _parse_result(
        self,
        process: ProcessResult,
        workspace: PreparedWorkspace,
    ) -> tuple[dict[str, object], tuple[AgentEvent, ...], str | None]: ...


def _bounded(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= _DIAGNOSTIC_LIMIT:
        return normalized
    return normalized[-_DIAGNOSTIC_LIMIT:]


def _execution_status(error: AgentRuntimeError) -> AgentExecutionStatus:
    if isinstance(error, AgentProcessTimeoutError):
        return AgentExecutionStatus.TIMED_OUT
    if isinstance(error, AgentProcessCancelledError):
        return AgentExecutionStatus.CANCELLED
    if isinstance(error, AgentConfigurationError):
        return AgentExecutionStatus.CONFIGURATION_ERROR
    return AgentExecutionStatus.FAILED
