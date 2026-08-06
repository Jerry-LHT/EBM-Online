"""The single Infrastructure adapter for configured professional tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, TypeVar

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    OutputAdapter,
    TaskAccessMode,
    TaskEvent,
    TaskExecution,
    TaskExecutionError,
    TaskExecutorPort,
    TaskOutputArtifact,
    TaskProvider,
    TaskRunRequest,
    TaskRunResult,
    TaskSkillSnapshot,
    WebAccessAudit,
    WebPolicyViolation,
    validate_task_output,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    AgentAccessMode,
    AgentRunRequest,
    AgentRunResult,
    AgentRuntime,
    WebAccessPolicy,
    make_responses_strict_schema,
)


OutputT = TypeVar("OutputT")


@dataclass(frozen=True, slots=True)
class AgentTaskGateway(TaskExecutorPort):
    """Central technical gateway from task ports to the Agent Runtime.

    The gateway is deliberately task-agnostic at the Application boundary.
    Skill selection, provider request construction, and runtime result
    translation are Infrastructure concerns and are resolved here.
    """

    runtime: AgentRuntime
    skill_paths_by_task: Mapping[str, tuple[Path, ...]] = field(
        default_factory=dict
    )
    # Kept only as a compatibility path for direct adapter tests and callers
    # that bind one Skill explicitly. The composition root uses the mapping.
    skill_paths: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.skill_paths_by_task, Mapping):
            normalized = {
                str(task): tuple(
                    Path(path).expanduser().resolve() for path in paths
                )
                for task, paths in self.skill_paths_by_task.items()
            }
        else:
            # The former positional constructor was
            # ``Adapter(runtime, skill_paths)``.
            normalized = {
                "unknown": tuple(
                    Path(path).expanduser().resolve()
                    for path in self.skill_paths_by_task
                )
            }
        if self.skill_paths:
            legacy = tuple(
                Path(path).expanduser().resolve() for path in self.skill_paths
            )
            if not normalized:
                normalized = {"unknown": legacy}
        if not normalized or any(not paths for paths in normalized.values()):
            raise ValueError("an Agent task gateway requires Skills")
        object.__setattr__(self, "skill_paths_by_task", normalized)
        object.__setattr__(
            self,
            "skill_paths",
            tuple(
                Path(path).expanduser().resolve() for path in self.skill_paths
            ),
        )

    def execute(
        self,
        request: TaskRunRequest,
        *,
        output_adapter: OutputAdapter[OutputT],
        error_context: str,
    ) -> TaskExecution[OutputT]:
        result = self.run(request)
        output = validate_task_output(
            result.output,
            output_adapter=output_adapter,
            error_context=error_context,
        )
        return TaskExecution(result=result, output=output)

    def run(self, request: TaskRunRequest) -> TaskRunResult:
        skill_paths = self.skill_paths_by_task.get(request.task_name)
        if skill_paths is None:
            skill_paths = self.skill_paths_by_task.get("unknown")
        if not skill_paths:
            raise TaskExecutionError(
                f"no Skill is configured for task {request.task_name!r}"
            )
        policy = request.web_access_policy
        runtime_policy = (
            policy
            if isinstance(policy, WebAccessPolicy)
            else WebAccessPolicy(
                enabled=policy.enabled,
                blocked_urls=policy.blocked_urls,
                blocked_domains=policy.blocked_domains,
                blocked_identifiers=policy.blocked_identifiers,
            )
        )
        runtime_request = AgentRunRequest(
            run_id=request.run_id,
            prompt=request.prompt,
            input_data=request.input_data,
            output_schema=make_responses_strict_schema(request.output_schema),
            skill_paths=skill_paths,
            input_artifacts=request.input_artifacts,
            output_artifacts=request.output_artifacts,
            timeout_seconds=request.timeout_seconds,
            access_mode=(
                AgentAccessMode.READ_ONLY
                if request.access_mode is TaskAccessMode.READ_ONLY
                else AgentAccessMode.WORKSPACE_WRITE
            ),
            enable_workspace_network=request.enable_workspace_network,
            enable_web_search=request.enable_web_search,
            web_access_policy=runtime_policy,
            task_name=request.task_name,
            run_record_digest_output_fields=(
                request.run_record_digest_output_fields
            ),
        )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _task_result(asyncio.run(self.runtime.run(runtime_request)))
        raise TaskExecutionError(
            "synchronous task execution cannot run inside an active event loop"
        )


def _task_result(result: AgentRunResult) -> TaskRunResult:
    return TaskRunResult(
        provider=TaskProvider(result.provider.value),
        model=result.model,
        run_id=result.run_id,
        session_id=result.session_id,
        output=result.output,
        events=tuple(
            TaskEvent(event.event_type, event.payload)
            for event in result.events
        ),
        stderr=result.stderr,
        duration_seconds=result.duration_seconds,
        web_access_audit=WebAccessAudit(
            enabled=result.web_access_audit.enabled,
            potential_contamination=(
                result.web_access_audit.potential_contamination
            ),
            inspected_value_count=(
                result.web_access_audit.inspected_value_count
            ),
            violations=tuple(
                WebPolicyViolation(
                    source=item.source,
                    match_type=item.match_type,
                    rule_digest=item.rule_digest,
                    observed_digest=item.observed_digest,
                )
                for item in result.web_access_audit.violations
            ),
        ),
        skill_snapshots=tuple(
            TaskSkillSnapshot(item.name, item.sha256)
            for item in result.skill_snapshots
        ),
        output_artifacts={
            name: TaskOutputArtifact(
                item.name,
                item.relative_path,
                item.content,
                item.sha256,
            )
            for name, item in result.output_artifacts.items()
        },
        retained_workspace=result.retained_workspace,
    )


# The old name remains as a source-compatible alias while callers migrate to
# the single gateway terminology. It is the same class, not a second adapter.
AgentTaskExecutorAdapter = AgentTaskGateway
