"""Factory for Q2PICO infrastructure methods."""

from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.q2pico.method import build_method


def build_q2pico_method(*, method_name: str):
    if method_name != "default":
        raise ValueError(f"Unknown method '{method_name}' for module 'q2pico'")
    return build_method()
