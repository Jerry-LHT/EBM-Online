"""Deterministic inconsistency GRADE domain method."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.base import GradeDomainMethod
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.decision import (
    DOMAIN,
    decide_inconsistency,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.evidence import (
    extract_inconsistency_features,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.profiler import (
    build_clinical_profile,
)


class Method(GradeDomainMethod):
    domain = DOMAIN

    def run(self, *, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
        return predict(domain_evidence=domain_evidence, evidence_body=evidence_body)


def predict(*, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
    features = extract_inconsistency_features(domain_evidence=domain_evidence, evidence_body=evidence_body)
    clinical_profile = build_clinical_profile(domain_evidence=domain_evidence, evidence_body=evidence_body)
    return decide_inconsistency(features=features, clinical_profile=clinical_profile)


def build_method() -> Method:
    return Method()
