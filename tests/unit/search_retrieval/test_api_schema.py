from __future__ import annotations

import pytest
from pydantic import ValidationError

from ebm_backend.online_pipeline.interfaces.api.request_schemas import (
    SearchRetrievalRequest,
)


def test_search_request_defaults_to_pubmed_source() -> None:
    request = SearchRetrievalRequest(question_pico={})

    assert request.source_names == ["pubmed"]
    assert request.max_candidates_per_source is None
    assert request.max_results_per_source == 500
    assert request.rct_filter_enabled is True


def test_search_request_requires_at_least_one_source_method() -> None:
    with pytest.raises(ValidationError):
        SearchRetrievalRequest(question_pico={}, source_names=[])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_candidates_per_source": 10001},
        {"max_results_per_source": 501},
        {"max_candidates_per_source": 10, "max_results_per_source": 20},
    ],
)
def test_search_request_enforces_bounded_consistent_limits(kwargs) -> None:
    with pytest.raises(ValidationError):
        SearchRetrievalRequest(question_pico={}, **kwargs)
