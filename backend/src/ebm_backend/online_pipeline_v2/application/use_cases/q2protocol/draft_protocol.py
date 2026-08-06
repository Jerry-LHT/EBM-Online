from dataclasses import dataclass

from ebm_backend.online_pipeline_v2.application.ports.q2protocol.draft_protocol import (
    DraftProtocolPort,
)
from ebm_backend.online_pipeline_v2.domain.common import TaskCompletion
from ebm_backend.online_pipeline_v2.domain.protocol import (
    ProtocolDraft,
    Q2ProtocolInput,
)


@dataclass(slots=True)
class DraftProtocol:
    port: DraftProtocolPort

    def execute(
        self,
        inputs: Q2ProtocolInput,
        protocol_version: str,
    ) -> TaskCompletion[ProtocolDraft]:
        return self.port.draft(inputs, protocol_version)
