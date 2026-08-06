from typing import Protocol

from ebm_backend.online_pipeline_v2.domain.common import TaskCompletion
from ebm_backend.online_pipeline_v2.domain.protocol import (
    ProtocolDraft,
    Q2ProtocolInput,
)


class DraftProtocolPort(Protocol):
    def draft(
        self,
        inputs: Q2ProtocolInput,
        protocol_version: str,
    ) -> TaskCompletion[ProtocolDraft]: ...
