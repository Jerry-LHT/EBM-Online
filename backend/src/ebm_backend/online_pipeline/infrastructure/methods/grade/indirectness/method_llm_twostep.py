"""LLM adjudicator for GRADE indirectness with dynamic threshold calibration."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.base import GradeDomainMethod
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.twostep import pipeline


DOMAIN = "indirectness"


class Method(GradeDomainMethod):
    domain = DOMAIN

    def __init__(self, *, config_path: str | None = None, model: str | None = None) -> None:
        self.config_path = config_path
        self.model = model

    def run(self, *, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
        return predict(
            domain_evidence=domain_evidence,
            evidence_body=evidence_body,
            config_path=self.config_path,
            model=self.model,
        )

    def run_batch_instances(self, *, method_instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return predict_batch_instances(
            method_instances=method_instances,
            config_path=self.config_path,
            model=self.model,
        )


def predict(
    *,
    domain_evidence: dict[str, Any],
    evidence_body: dict[str, Any],
    config_path: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    return pipeline.predict(
        domain_evidence=domain_evidence,
        evidence_body=evidence_body,
        config_path=config_path,
        model=model,
    )


def predict_batch_instances(
    *,
    method_instances: list[dict[str, Any]],
    config_path: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    return pipeline.predict_batch_instances(
        method_instances=method_instances,
        config_path=config_path,
        model=model,
    )


def build_method() -> Method:
    return Method()
