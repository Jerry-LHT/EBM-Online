from __future__ import annotations

from benchmark.online_pipeline.q2pico.evaluation.method_adapter import (
    load_q2pico_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.q2pico.split_slot_llm.method import (
    Method,
)


def test_benchmark_adapter_loads_backend_q2pico_method() -> None:
    assert isinstance(load_q2pico_method("q2pico.default"), Method)
