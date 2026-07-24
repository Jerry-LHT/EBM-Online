"""Benchmark adapter for Search Retrieval methods."""

from __future__ import annotations

from ebm_backend.online_pipeline.application.use_cases.run_search_retrieval import (
    RunSearchRetrieval,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.factory import (
    build_search_retrieval_source,
)


def load_search_retrieval_benchmark_use_case(method_spec: str) -> RunSearchRetrieval:
    method_name = method_spec.removeprefix("search_retrieval.")
    if method_name != "pubmed_pmc":
        raise ValueError(f"Unknown Search Retrieval benchmark method '{method_spec}'")
    return RunSearchRetrieval(
        retrieval_sources=(
            build_search_retrieval_source(source_name="pubmed"),
        )
    )
