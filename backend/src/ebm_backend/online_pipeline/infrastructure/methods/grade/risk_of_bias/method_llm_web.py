"""Delegate risk-of-bias judgement for grade.method_llm_web runs."""

from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_test import Method


def build_method() -> Method:
    return Method()
