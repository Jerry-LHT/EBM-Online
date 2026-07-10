"""Inconsistency method with local LLM characteristic profiling.

The LLM is only used to summarize clinical/methodological heterogeneity from
clean local evidence. It does not perform web retrieval and does not make the
final GRADE downgrade decision.
"""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_llm_web import (
    Method as _ProfileMethod,
    predict as _predict,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.mode import (
    InconsistencyMethodConfig,
)


class Method(_ProfileMethod):
    def __init__(self, *, config_path: str | None = None, model: str | None = None) -> None:
        super().__init__(
            method_config=InconsistencyMethodConfig(mode="audit", allow_llm_profile=True),
            config_path=config_path,
            model=model,
        )


def predict(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    return _predict(
        domain_evidence=domain_evidence,
        evidence_body=evidence_body,
        method_config=InconsistencyMethodConfig(mode="audit", allow_llm_profile=True),
    )


def build_method() -> Method:
    return Method()
