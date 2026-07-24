"""Benchmark-side loading for the backend Q2PICO capability."""

from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.q2pico.factory import (
    build_production_q2pico,
)


def load_q2pico_method(method_spec: str):
    method_name = _method_name(method_spec=method_spec, module_name="q2pico")
    if method_name != "default":
        raise ValueError(f"Unknown Q2PICO benchmark method '{method_name}'")
    return build_production_q2pico()


def _method_name(*, method_spec: str, module_name: str) -> str:
    if "." not in method_spec:
        return method_spec
    supplied_module, method_name = method_spec.split(".", 1)
    if supplied_module != module_name:
        raise ValueError(
            f"Method '{method_spec}' does not belong to benchmark module '{module_name}'"
        )
    return method_name
