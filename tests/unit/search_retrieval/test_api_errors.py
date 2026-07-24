from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException

from ebm_backend.online_pipeline.domain.article import SearchRetrievalResult
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.errors import (
    SearchRetrievalStageError,
)
from ebm_backend.online_pipeline.interfaces.api import routes_modules
from ebm_backend.online_pipeline.interfaces.api.request_schemas import SearchRetrievalRequest


class _UseCase:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.config = None

    def execute(self, **kwargs):
        self.config = kwargs["config"]
        if self.error is not None:
            raise self.error
        return SearchRetrievalResult(returned_count=0)


def test_search_route_maps_retry_exhaustion_to_bad_gateway(monkeypatch) -> None:
    use_case = _UseCase(
        error=SearchRetrievalStageError(stage="pubmed_search", attempts=2)
    )
    monkeypatch.setattr(
        routes_modules,
        "get_search_retrieval_use_case_for_api",
        lambda **kwargs: use_case,
    )

    with pytest.raises(HTTPException) as raised:
        routes_modules.run_search_retrieval(
            SearchRetrievalRequest(question_pico={"P": ["depression"]})
        )

    assert raised.value.status_code == 502
    assert raised.value.detail["code"] == "search_retrieval_stage_retry_exhausted"
    assert raised.value.detail["stage"] == "pubmed_search"
    assert raised.value.detail["attempts"] == 2


def test_search_route_maps_invalid_input_to_stable_bad_request(monkeypatch) -> None:
    monkeypatch.setattr(
        routes_modules,
        "get_search_retrieval_use_case_for_api",
        lambda **kwargs: _UseCase(error=ValueError("invalid concepts")),
    )

    with pytest.raises(HTTPException) as raised:
        routes_modules.run_search_retrieval(
            SearchRetrievalRequest(question_pico={"P": ["depression"]})
        )

    assert raised.value.status_code == 400
    assert raised.value.detail["code"] == "search_retrieval_invalid_input"


def test_search_route_maps_invalid_question_shape_to_stable_bad_request() -> None:
    with pytest.raises(HTTPException) as raised:
        routes_modules.run_search_retrieval(
            SearchRetrievalRequest(question_pico={"P": "not-a-list"})
        )

    assert raised.value.status_code == 400
    assert raised.value.detail["code"] == "search_retrieval_invalid_input"


def test_search_route_maps_limits_and_rct_toggle_to_module_config(monkeypatch) -> None:
    use_case = _UseCase()
    monkeypatch.setattr(
        routes_modules,
        "get_search_retrieval_use_case_for_api",
        lambda **kwargs: use_case,
    )

    routes_modules.run_search_retrieval(
        SearchRetrievalRequest(
            question_pico={"P": ["depression"]},
            max_candidates_per_source=40,
            max_results_per_source=10,
            rct_filter_enabled=False,
        )
    )

    assert use_case.config.max_candidates_per_source == 40
    assert use_case.config.max_results_per_source == 10
    assert use_case.config.constraints.study_design == ""
