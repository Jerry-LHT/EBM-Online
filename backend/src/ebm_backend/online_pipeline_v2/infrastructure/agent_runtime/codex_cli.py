"""Real non-interactive Codex CLI runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from ._base import CliAgentRuntime
from .contracts import (
    AgentAccessMode,
    AgentEvent,
    AgentProvider,
    AgentRunRequest,
    ProcessResult,
)
from .errors import AgentOutputError
from .structured_output import parse_json_object
from .workspace import PreparedWorkspace


class CodexCliRuntime(CliAgentRuntime):
    provider = AgentProvider.OPENAI
    binary = "codex"
    required_flags = (
        "--json",
        "--output-schema",
        "--output-last-message",
        "--sandbox",
        "--cd",
        "--ephemeral",
        "--ignore-user-config",
        "--search",
    )

    def _help_commands(self) -> tuple[tuple[str, ...], ...]:
        return (
            (self.binary, "--help"),
            (self.binary, "exec", "--help"),
        )

    def _credential_environment(self) -> Mapping[str, str]:
        return {"CODEX_API_KEY": self._config.api_key}

    def _command(
        self,
        request: AgentRunRequest,
        workspace: PreparedWorkspace,
    ) -> tuple[str, ...]:
        command: list[str] = [self.binary]
        if request.enable_web_search:
            command.append("--search")
        sandbox = (
            "read-only"
            if request.access_mode is AgentAccessMode.READ_ONLY
            else "workspace-write"
        )
        command.extend(
            [
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--json",
                "--output-last-message",
                str(workspace.output_path),
                "--model",
                self._config.cli_model,
                "--sandbox",
                sandbox,
                "--cd",
                str(workspace.root),
                "-c",
                "allow_login_shell=false",
                "-c",
                'model_provider="ebm_openai"',
                "-c",
                'model_providers.ebm_openai.name="EBM OpenAI"',
                "-c",
                (
                    "model_providers.ebm_openai.base_url="
                    f'"{self._config.base_url}"'
                ),
                "-c",
                (
                    "model_providers.ebm_openai.env_key="
                    '"CODEX_API_KEY"'
                ),
                "-c",
                'model_providers.ebm_openai.wire_api="responses"',
            ]
        )
        if request.enable_workspace_network:
            command.extend(
                (
                    "-c",
                    "sandbox_workspace_write.network_access=true",
                )
            )
        command.extend(("--output-schema", str(workspace.schema_path)))
        command.append("-")
        return tuple(command)

    def _prompt(
        self,
        request: AgentRunRequest,
        workspace: PreparedWorkspace,
    ) -> str:
        skills = " ".join(
            f"${name}" for name in workspace.staged_skills.names
        )
        web_policy = _web_policy_instruction(
            request.web_access_policy.enabled
        )
        return (
            f"Use the following Agent Skills explicitly: {skills}.\n"
            "Read the task input from inputs/task-input.json.\n"
            "Read declared immutable input artifacts from inputs/artifacts/.\n"
            "Read contracts/output-artifacts.json and write every required "
            "artifact to its exact declared path.\n"
            "Complete the requested work inside this task workspace only.\n"
            f"{web_policy}"
            "Return only the final JSON object required by "
            "contracts/output.schema.json.\n\n"
            f"Task:\n{request.prompt.strip()}\n"
        )

    def _parse_result(
        self,
        process: ProcessResult,
        workspace: PreparedWorkspace,
    ) -> tuple[dict[str, object], tuple[AgentEvent, ...], str | None]:
        events: list[AgentEvent] = []
        session_id: str | None = None
        fallback_text: str | None = None
        for sequence, line in enumerate(process.stdout.splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                events.append(_non_json_stdout_event(sequence, line, exc))
                continue
            if not isinstance(payload, dict):
                raise AgentOutputError("Codex event must be a JSON object")
            event_type = str(payload.get("type") or "unknown")
            events.append(AgentEvent(event_type=event_type, payload=payload))
            if event_type == "thread.started":
                session_id = _first_text(
                    payload.get("thread_id"),
                    payload.get("thread", {}).get("id")
                    if isinstance(payload.get("thread"), dict)
                    else None,
                )
            item = payload.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                fallback_text = _first_text(item.get("text"), fallback_text)

        if workspace.output_path.is_file():
            final_text = workspace.output_path.read_text(encoding="utf-8")
        elif fallback_text is not None:
            final_text = fallback_text
        else:
            raise AgentOutputError("Codex produced no final structured output")
        return parse_json_object(final_text), tuple(events), session_id


def _non_json_stdout_event(
    sequence: int,
    line: str,
    error: json.JSONDecodeError,
) -> AgentEvent:
    encoded = line.encode("utf-8")
    return AgentEvent(
        event_type="runtime.stdout.non_json",
        payload={
            "type": "runtime.stdout.non_json",
            "sequence": sequence,
            "size_bytes": len(encoded),
            "sha256": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
            "json_error": error.msg,
            "json_error_line": error.lineno,
            "json_error_column": error.colno,
            "audit_coverage": "degraded",
        },
    )


def _first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _web_policy_instruction(enabled: bool) -> str:
    if not enabled:
        return ""
    return (
        "You may search the web for legitimate external evidence. Do not seek "
        "or use prohibited answer sources, and ignore any such source if it "
        "appears.\n"
    )
