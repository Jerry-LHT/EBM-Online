"""Concrete provider selection for the approved CLI runtimes."""

from __future__ import annotations

import os
from pathlib import Path

from .claude_cli import ClaudeCliRuntime
from .codex_cli import CodexCliRuntime
from .contracts import (
    AgentProvider,
    AgentRuntime,
    ProcessRunner,
    WorkspaceRetention,
)
from .configuration import AgentRuntimeConfig
from .workspace import WorkspaceManager
from .run_store import JsonRunStore
from .debug_store import DebugBundleStore, default_debug_root
from .web_access_policy import load_web_access_policy


def build_agent_runtime(
    config: AgentRuntimeConfig,
    *,
    process_runner: ProcessRunner | None = None,
    workspace_manager: WorkspaceManager | None = None,
) -> AgentRuntime:
    """Build the CLI runtime selected by the local configuration."""
    debug = _env_bool("AGENT_DEBUG")
    policy = load_web_access_policy()
    debug_store = None
    debug_root = Path(
        os.getenv("AGENT_DEBUG_ROOT", str(default_debug_root()))
    ).expanduser()
    if workspace_manager is None:
        workspace_manager = WorkspaceManager(
            base_directory=debug_root / "workspaces" if debug else None,
            retention=(
                WorkspaceRetention.ALWAYS
                if debug
                else WorkspaceRetention.ON_FAILURE
            )
        )
    run_store = JsonRunStore(
        root=Path(
            os.getenv("AGENT_RUN_STORE_PATH", ".agent-runs")
        ).expanduser(),
        policy=policy,
        debug=debug,
    )
    if debug:
        debug_store = DebugBundleStore(
            root=debug_root,
            policy=policy,
            secret=config.api_key,
        )
    if config.provider is AgentProvider.OPENAI:
        return CodexCliRuntime(
            config,
            process_runner=process_runner,
            workspace_manager=workspace_manager,
            run_store=run_store,
            debug_store=debug_store,
        )
    return ClaudeCliRuntime(
        config,
        process_runner=process_runner,
        workspace_manager=workspace_manager,
        run_store=run_store,
        debug_store=debug_store,
    )


def _env_bool(name: str) -> bool:
    value = os.getenv(name, "0").strip().casefold()
    if value not in {"0", "1", "false", "true", "off", "on"}:
        raise ValueError(f"{name} must be a boolean")
    return value in {"1", "true", "on"}
