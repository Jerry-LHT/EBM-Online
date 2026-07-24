"""Factory for Study PIO extraction methods."""

from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.study_pio.extraction_study_pico_slotwise_llm.method import (
    build_method as build_slotwise_llm_method,
)

def build_production_study_pio():
    """Build the Study PIO adapter approved for the product API."""
    return build_slotwise_llm_method()
