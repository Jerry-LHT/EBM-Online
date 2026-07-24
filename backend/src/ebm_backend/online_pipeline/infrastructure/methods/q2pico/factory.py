"""Factory for Q2PICO infrastructure methods."""

from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.q2pico.split_slot_llm.method import (
    build_method,
)


def build_production_q2pico():
    """Build the Q2PICO adapter approved for the product API."""
    return build_method()
