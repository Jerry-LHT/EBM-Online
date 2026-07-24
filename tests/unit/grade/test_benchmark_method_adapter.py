from __future__ import annotations

import pytest

from benchmark.online_pipeline.grade.method_adapter import (
    load_grade_benchmark_method,
    load_grade_domain_benchmark_method,
)


@pytest.mark.parametrize(
    ("domain", "method_name"),
    [
        ("risk_of_bias", "method_deterministic"),
        ("inconsistency", "method_deterministic"),
        ("imprecision", "method_deterministic"),
    ],
)
def test_domain_benchmark_adapter_uses_explicit_mapping(
    domain: str,
    method_name: str,
) -> None:
    adapter = load_grade_domain_benchmark_method(domain, method_name)

    assert adapter.domain == domain
    assert callable(adapter.domain_methods[domain].run)


def test_fully_qualified_grade_method_spec_is_supported() -> None:
    adapter = load_grade_benchmark_method(
        "grade.risk_of_bias.method_deterministic"
    )

    assert adapter.domain == "risk_of_bias"


def test_unqualified_generic_grade_method_is_rejected() -> None:
    with pytest.raises(ValueError, match="A domain is required"):
        load_grade_benchmark_method("method_deterministic")
