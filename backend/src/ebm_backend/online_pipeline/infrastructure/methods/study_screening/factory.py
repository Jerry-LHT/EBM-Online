"""Factory for study-screening infrastructure methods."""

from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.study_screening.method import build_method


def build_study_screening_method(*, method_name: str):
    if method_name != "default":
        raise ValueError(f"Unknown method '{method_name}' for module 'study_screening'")
    return build_method()
