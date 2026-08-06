from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.use_cases._shared import (
    finish_artifact,
    require_protocol_version,
)
from ebm_backend.online_pipeline_v2.application.use_cases.q2protocol.draft_protocol import (
    DraftProtocol,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactEnvelope,
    TaskInvocation,
    TaskName,
)
from ebm_backend.online_pipeline_v2.domain.protocol import (
    ProtocolDraft,
    Q2ProtocolInput,
)


@dataclass(slots=True)
class ExecuteQ2Protocol:
    draft_protocol: DraftProtocol

    def execute(
        self,
        invocation: TaskInvocation[Q2ProtocolInput],
    ) -> ArtifactEnvelope[ProtocolDraft]:
        completion = self.draft_protocol.execute(
            invocation.inputs,
            invocation.context.protocol_version,
        )
        if completion.data is not None:
            require_protocol_version(invocation, completion.data)
        return finish_artifact(invocation, TaskName.Q2PROTOCOL, completion)
