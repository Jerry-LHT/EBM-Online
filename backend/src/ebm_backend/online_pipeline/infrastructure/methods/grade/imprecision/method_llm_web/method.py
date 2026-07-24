"""LLM-web threshold researcher plus deterministic imprecision decision method."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.decision import decide_imprecision
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.evidence import (
    build_setting_context,
    build_threshold_audit_context,
    build_threshold_research_context,
    extract_numeric_features,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.researcher import (
    FallbackThresholdResearcher,
    LLMWebThresholdResearcher,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.registry import InMemoryThresholdEvidenceRegistry


DOMAIN = "imprecision"


class Method:
    domain = DOMAIN

    def __init__(self, *, threshold_researcher: Any | None = None) -> None:
        self.threshold_registry = InMemoryThresholdEvidenceRegistry()
        self.threshold_researcher = threshold_researcher or LLMWebThresholdResearcher(registry=self.threshold_registry)

    def run(self, *, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
        return predict(
            domain_evidence=domain_evidence,
            evidence_body=evidence_body,
            threshold_researcher=self.threshold_researcher,
        )

    def research_threshold(self, *, domain_evidence: dict[str, Any], evidence_body: dict[str, Any]) -> dict[str, Any]:
        threshold_context = build_threshold_research_context(domain_evidence=domain_evidence, evidence_body=evidence_body)
        audit_context = build_threshold_audit_context(domain_evidence=domain_evidence, evidence_body=evidence_body)
        return self.threshold_researcher.research(threshold_context=threshold_context, audit_context=audit_context)

    def run_with_threshold(
        self,
        *,
        domain_evidence: dict[str, Any],
        evidence_body: dict[str, Any],
        threshold: dict[str, Any],
    ) -> dict[str, Any]:
        return predict_with_threshold(domain_evidence=domain_evidence, evidence_body=evidence_body, threshold=threshold)


def predict(
    *,
    domain_evidence: dict[str, Any],
    evidence_body: dict[str, Any],
    threshold_researcher: Any | None = None,
) -> dict[str, Any]:
    setting_context = build_setting_context(domain_evidence=domain_evidence, evidence_body=evidence_body)
    threshold_context = build_threshold_research_context(domain_evidence=domain_evidence, evidence_body=evidence_body)
    audit_context = build_threshold_audit_context(domain_evidence=domain_evidence, evidence_body=evidence_body)
    numeric_features = extract_numeric_features(domain_evidence=domain_evidence, evidence_body=evidence_body)
    researcher = threshold_researcher or LLMWebThresholdResearcher()
    threshold = researcher.research(threshold_context=threshold_context, audit_context=audit_context)
    _attach_context(threshold, threshold_context=threshold_context, audit_context=audit_context)
    return decide_imprecision(setting_context=setting_context, numeric_features=numeric_features, threshold=threshold)


def predict_with_threshold(
    *,
    domain_evidence: dict[str, Any],
    evidence_body: dict[str, Any],
    threshold: dict[str, Any],
) -> dict[str, Any]:
    setting_context = build_setting_context(domain_evidence=domain_evidence, evidence_body=evidence_body)
    threshold_context = build_threshold_research_context(domain_evidence=domain_evidence, evidence_body=evidence_body)
    audit_context = build_threshold_audit_context(domain_evidence=domain_evidence, evidence_body=evidence_body)
    numeric_features = extract_numeric_features(domain_evidence=domain_evidence, evidence_body=evidence_body)
    _attach_context(threshold, threshold_context=threshold_context, audit_context=audit_context)
    return decide_imprecision(setting_context=setting_context, numeric_features=numeric_features, threshold=threshold)


def _attach_context(threshold: dict[str, Any], *, threshold_context: dict[str, Any], audit_context: dict[str, Any]) -> None:
    existing_threshold_context = threshold.get("threshold_research_context")
    if isinstance(existing_threshold_context, dict):
        threshold["threshold_research_context"] = {**threshold_context, **existing_threshold_context}
    else:
        threshold["threshold_research_context"] = threshold_context

    existing_audit_context = threshold.get("threshold_audit_context")
    if isinstance(existing_audit_context, dict):
        threshold["threshold_audit_context"] = {**audit_context, **existing_audit_context}
    else:
        threshold["threshold_audit_context"] = audit_context

    threshold.setdefault("threshold_research_key", threshold_context.get("threshold_research_key"))


def build_method() -> Method:
    return Method()


__all__ = [
    "FallbackThresholdResearcher",
    "LLMWebThresholdResearcher",
    "Method",
    "build_method",
    "predict",
    "predict_with_threshold",
]
