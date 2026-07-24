"""Benchmark adapter for Risk of Bias methods."""

from __future__ import annotations


def load_risk_of_bias_benchmark_method(method_spec: str):
    method_name = method_spec.removeprefix("risk_of_bias.")
    if method_name == "method_onestep_llm":
        from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.method import build_method

        return build_method()
    if method_name == "method_hybrid_slots":
        from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_hybrid_slots.method import build_method

        return build_method()
    if method_name == "method_calibrated_slots":
        from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_calibrated_slots.method import build_method

        return build_method()
    raise ValueError(f"Unknown Risk of Bias benchmark method '{method_name}'")
