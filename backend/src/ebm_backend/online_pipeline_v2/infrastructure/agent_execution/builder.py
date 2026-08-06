"""Composition helpers for the single Agent task adapter."""

from pathlib import Path
from typing import Mapping

from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import AgentRuntime

from .adapter import AgentTaskGateway


def build_agent_task_gateway(
    *,
    runtime: AgentRuntime,
    skill_paths_by_task: Mapping[str, tuple[Path, ...]],
) -> AgentTaskGateway:
    return AgentTaskGateway(
        runtime=runtime,
        skill_paths_by_task=skill_paths_by_task,
    )


def build_agent_task_executor(
    *,
    runtime: AgentRuntime,
    skill_paths: tuple[Path, ...] = (),
    skill_paths_by_task: Mapping[str, tuple[Path, ...]] | None = None,
) -> AgentTaskGateway:
    """Compatibility builder for the pre-gateway composition API."""

    return AgentTaskGateway(
        runtime=runtime,
        skill_paths=skill_paths,
        skill_paths_by_task=skill_paths_by_task or {},
    )
