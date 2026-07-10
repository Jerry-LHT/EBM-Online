from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.study_screening.factory import (
    build_study_screening_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.method import Method


def test_factory_builds_default_study_screening_method() -> None:
    method = build_study_screening_method(method_name="default")

    assert isinstance(method, Method)


def test_factory_rejects_unknown_method() -> None:
    try:
        build_study_screening_method(method_name="unknown")
    except ValueError as exc:
        assert "Unknown method" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
