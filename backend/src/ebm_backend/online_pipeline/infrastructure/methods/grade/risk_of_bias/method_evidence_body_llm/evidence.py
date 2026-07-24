"""Build the bounded semantic payload owned by the concrete GRADE RoB method."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.domain.grade import GRADERiskOfBiasInput
from ebm_backend.online_pipeline.domain.serialization import to_jsonable


def build_payload(grade_input: GRADERiskOfBiasInput) -> dict[str, Any]:
    return to_jsonable(grade_input)


def lacks_assessable_rob(grade_input: GRADERiskOfBiasInput) -> bool:
    return not any(
        study.rob_available and study.domains
        for study in grade_input.contributing_studies
    )
