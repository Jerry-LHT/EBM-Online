"""Adapter entry point for the LLM-backed GRADE risk-of-bias method."""

from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_llm.pipeline import (
    Method,
    build_method,
)

__all__ = ["Method", "build_method"]
