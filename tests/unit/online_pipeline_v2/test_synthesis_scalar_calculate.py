from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/agent_execution/"
    "skills/evidence_synthesis/synthesize-evidence/scripts/scalar_calculate.py"
)
_SPEC = importlib.util.spec_from_file_location("v2_scalar_calculate", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
scalar_calculate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scalar_calculate)


def test_scalar_calculator_preserves_decimal_result_and_digest() -> None:
    result = scalar_calculate.calculate(
        {
            "expression": "(events / sample) * 100",
            "inputs": {"events": "1", "sample": "3"},
            "precision": 40,
        }
    )

    assert result["schema_version"] == "scalar-calculate-output.v1"
    assert result["outputs"]["value"].startswith("33.333333333333333333")
    assert result["input_digest"].startswith("sha256:")
    assert result["output_digest"].startswith("sha256:")


def test_scalar_calculator_returns_structured_domain_error() -> None:
    with pytest.raises(scalar_calculate.ScalarCalculationError) as caught:
        scalar_calculate.calculate(
            {"expression": "events / sample", "inputs": {"events": 1, "sample": 0}}
        )

    assert caught.value.code == "numeric_operation_failed"
