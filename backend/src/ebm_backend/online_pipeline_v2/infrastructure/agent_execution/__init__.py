"""Shared execution and output-artifact mechanics for Skill-backed tasks."""

from .adapter import AgentTaskExecutorAdapter, AgentTaskGateway
from .builder import build_agent_task_executor, build_agent_task_gateway
from .skill_tools import SkillTool, load_skill_tool
from .output_bundle import (
    ArtifactEncoding,
    LoadedOutputBundle,
    OutputBundleSpec,
    OutputMemberSpec,
    load_output_bundle,
)

__all__ = [
    "AgentTaskExecutorAdapter",
    "AgentTaskGateway",
    "build_agent_task_executor",
    "build_agent_task_gateway",
    "SkillTool",
    "load_skill_tool",
    "ArtifactEncoding",
    "LoadedOutputBundle",
    "OutputBundleSpec",
    "OutputMemberSpec",
    "load_output_bundle",
]
