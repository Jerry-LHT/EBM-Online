from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.loader import (
    get_meta_analysis_subtask_method,
)


def test_source_local_candidate_extraction_method_is_loadable() -> None:
    method = get_meta_analysis_subtask_method(
        "study_results",
        "method_source_local_candidate_extraction",
    )

    assert callable(method.run)
