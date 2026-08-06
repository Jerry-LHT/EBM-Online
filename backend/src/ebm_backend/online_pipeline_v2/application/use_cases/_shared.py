from __future__ import annotations

from typing import Protocol, TypeVar

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactEnvelope,
    DomainValidationError,
    TaskCompletion,
    TaskInvocation,
    TaskName,
    build_artifact,
)
InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class VersionedProtocol(Protocol):
    version: str


def require_protocol_version(
    invocation: TaskInvocation[InputT],
    protocol: VersionedProtocol,
) -> None:
    if protocol.version != invocation.context.protocol_version:
        raise DomainValidationError(
            "protocol version does not match task invocation"
        )


def finish_artifact(
    invocation: TaskInvocation[InputT],
    task: TaskName,
    completion: TaskCompletion[OutputT],
) -> ArtifactEnvelope[OutputT]:
    return build_artifact(
        context=invocation.context,
        task=task,
        data=completion.data,
        provenance=invocation.provenance + completion.additional_provenance,
        status=completion.status,
        issues=completion.issues,
    )
