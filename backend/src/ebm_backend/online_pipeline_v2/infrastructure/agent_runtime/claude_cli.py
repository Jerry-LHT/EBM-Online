"""Real non-interactive Claude Code CLI runtime."""

from __future__ import annotations

import json
from typing import Mapping

from ._base import CliAgentRuntime
from .contracts import (
    AgentAccessMode,
    AgentEvent,
    AgentProvider,
    AgentRunRequest,
    ProcessResult,
)
from .errors import AgentOutputError, AgentWorkspaceError
from .structured_output import parse_json_object
from .workspace import PreparedWorkspace


class ClaudeCliRuntime(CliAgentRuntime):
    provider = AgentProvider.ANTHROPIC
    binary = "claude"
    required_flags = (
        "--print",
        "--bare",
        "--output-format",
        "--json-schema",
        "--permission-mode",
        "--plugin-dir",
        "--no-session-persistence",
    )

    def _help_commands(self) -> tuple[tuple[str, ...], ...]:
        return ((self.binary, "--help"),)

    def _credential_environment(self) -> Mapping[str, str]:
        return {
            "ANTHROPIC_API_KEY": self._config.api_key,
            "ANTHROPIC_BASE_URL": self._config.base_url,
        }

    def _command(
        self,
        request: AgentRunRequest,
        workspace: PreparedWorkspace,
    ) -> tuple[str, ...]:
        plugin = workspace.staged_skills.claude_plugin_path
        if plugin is None:
            raise AgentWorkspaceError(
                workspace.root,
                "Claude Skill plugin was not staged",
            )
        permission_mode = (
            "dontAsk"
            if request.access_mode is AgentAccessMode.READ_ONLY
            else "acceptEdits"
        )
        command = [
            self.binary,
            "--print",
            "--bare",
            "--model",
            self._config.cli_model,
            "--input-format",
            "text",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            permission_mode,
            "--plugin-dir",
            str(plugin),
            "--no-session-persistence",
        ]
        command.extend(
            (
                "--json-schema",
                json.dumps(
                    dict(request.output_schema),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
        if not request.enable_web_search:
            command.extend(("--disallowedTools", "WebSearch,WebFetch"))
        if request.enable_workspace_network:
            script_rules = ",".join(
                "Bash(python3 "
                f".runtime/claude-skills/skills/{name}/scripts/*)"
                for name in workspace.staged_skills.names
            )
            allowed_tools = [
                "Read",
                "Write",
                "Edit",
                "Glob",
                "Grep",
                script_rules,
            ]
            if request.enable_web_search:
                allowed_tools.extend(("WebSearch", "WebFetch"))
            command.extend(
                (
                    "--allowedTools",
                    ",".join(allowed_tools),
                )
            )
        return tuple(command)

    def _prompt(
        self,
        request: AgentRunRequest,
        workspace: PreparedWorkspace,
    ) -> str:
        skills = " ".join(
            f"/{name}" for name in workspace.staged_skills.names
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
            "Return the structured output required by the supplied JSON "
            "Schema.\n\n"
            f"Task:\n{request.prompt.strip()}\n"
        )

    def _parse_result(
        self,
        process: ProcessResult,
        workspace: PreparedWorkspace,
    ) -> tuple[dict[str, object], tuple[AgentEvent, ...], str | None]:
        events: list[AgentEvent] = []
        session_id: str | None = None
        final_value: object = None
        for line in process.stdout.splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AgentOutputError(
                    "Claude stream-json emitted a non-JSONL stdout line"
                ) from exc
            if not isinstance(payload, dict):
                raise AgentOutputError("Claude event must be a JSON object")
            event_type = str(payload.get("type") or "unknown")
            events.append(AgentEvent(event_type=event_type, payload=payload))
            session_id = _first_text(payload.get("session_id"), session_id)
            if "structured_output" in payload:
                final_value = payload["structured_output"]
            elif event_type == "result" and "result" in payload:
                final_value = payload["result"]

        if isinstance(final_value, dict):
            return dict(final_value), tuple(events), session_id
        if isinstance(final_value, str) and final_value.strip():
            return parse_json_object(final_value), tuple(events), session_id
        raise AgentOutputError("Claude produced no final structured output")


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
