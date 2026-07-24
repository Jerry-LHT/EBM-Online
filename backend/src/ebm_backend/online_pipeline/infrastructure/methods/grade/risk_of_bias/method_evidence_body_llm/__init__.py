"""Outcome-specific evidence-body LLM method for GRADE risk of bias."""

from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_evidence_body_llm.method import (
    Method,
    build_method,
)

__all__ = ["Method", "build_method"]
