from __future__ import annotations

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_meta_analysis import (
    RunMetaAnalysis,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMAPIError
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.errors import (
    MetaAnalysisConfigurationError,
    MetaAnalysisInvocationError,
    MetaAnalysisOutputError,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.synthesis_planning.synthesis_plan_llm.method import (
    Method as SynthesisPlanningMethod,
)
from ebm_backend.online_pipeline.infrastructure.llm.client import MAX_CONCURRENT_LLM_CALLS
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent import (
    method as study_evidence_method,
)


CONTEXT = {
    "review_id": "review-1",
    "question_text": "Does treatment improve pain?",
    "question_pico": {},
    "screening_criteria": {},
}


def _provider_error(*, retryable: bool) -> LLMAPIError:
    return LLMAPIError(
        "provider failure",
        status_code=503 if retryable else 400,
        request_id="request-1",
        retry_after_seconds=None,
        retryable=retryable,
        provider_message="provider failure",
    )


def test_synthesis_planner_disables_hidden_retries() -> None:
    captured = {}

    def caller(**kwargs):
        captured.update(kwargs)
        return {"targets": [], "unsupported_targets": [], "rationale": ""}

    result = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=caller,
    ).run(context=CONTEXT)

    assert result["status"] == "not_plannable"
    assert captured["config"]["sdk_max_retries"] == 0
    assert captured["config"]["json_marker_retry_enabled"] is False


@pytest.mark.parametrize(
    ("retryable", "expected_calls", "retry_exhausted"),
    [(True, 2, True), (False, 1, False)],
)
def test_synthesis_planner_retries_only_retryable_provider_errors(
    retryable: bool,
    expected_calls: int,
    retry_exhausted: bool,
) -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        raise _provider_error(retryable=retryable)

    with pytest.raises(MetaAnalysisInvocationError) as raised:
        SynthesisPlanningMethod(
            config={"model": "fake"},
            llm_caller=caller,
        ).run(context=CONTEXT)

    assert calls == expected_calls
    assert raised.value.retry_exhausted is retry_exhausted


def test_synthesis_planner_invalid_output_has_distinct_error() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        return {}

    with pytest.raises(MetaAnalysisOutputError):
        SynthesisPlanningMethod(
            config={"model": "fake"},
            llm_caller=caller,
        ).run(context=CONTEXT)

    assert calls == 2


def test_synthesis_planner_does_not_retry_programming_errors() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("implementation defect")

    with pytest.raises(RuntimeError, match="implementation defect"):
        SynthesisPlanningMethod(
            config={"model": "fake"},
            llm_caller=caller,
        ).run(context=CONTEXT)

    assert calls == 1


def test_evidence_agent_missing_config_is_not_silent_empty_evidence(monkeypatch) -> None:
    monkeypatch.setattr(study_evidence_method, "load_llm_config", lambda *_args, **_kwargs: None)

    with pytest.raises(MetaAnalysisConfigurationError):
        study_evidence_method.Method().run(
            review_id="review-1",
            targets=[{"target_id": "target-1", "data_type": "Dichotomous"}],
            study_id="study-1",
            article={"study_id": "study-1", "tables": []},
            plan_hash="hash-1",
        )


def test_evidence_agent_retry_is_first_call_plus_one_retry() -> None:
    calls = 0

    def caller(**_kwargs):
        nonlocal calls
        calls += 1
        raise _provider_error(retryable=True)

    with pytest.raises(MetaAnalysisInvocationError) as raised:
        study_evidence_method.Method(
            config={"model": "fake"},
            llm_caller=caller,
        )._call(
            config={"model": "fake"},
            stage="table_result_extraction",
            context_id="study-1::table-1",
            system="system",
            payload={},
            schema={"type": "object"},
            schema_name="test_schema",
            max_output_tokens=100,
            reasoning_effort="low",
        )

    assert calls == 2
    assert raised.value.retry_exhausted is True


def test_meta_analysis_worker_settings_have_hard_caps() -> None:
    adapter = object()
    use_case = RunMetaAnalysis(
        synthesis_planner=adapter,  # type: ignore[arg-type]
        study_evidence_agent=adapter,  # type: ignore[arg-type]
        analysis_methods_selector=adapter,  # type: ignore[arg-type]
        subgroup_analyzer=adapter,  # type: ignore[arg-type]
        overall_estimates_calculator=adapter,  # type: ignore[arg-type]
        max_article_workers=100,
    )
    evidence_agent = study_evidence_method.Method(
        config={"model": "fake"},
        max_controller_turns=100,
        max_section_reads=100,
        max_table_reads=100,
        max_table_workers=100,
    )

    assert use_case.max_article_workers == 16
    assert evidence_agent.max_controller_turns == 12
    assert evidence_agent.max_section_reads == 8
    assert evidence_agent.max_table_reads == 32
    assert evidence_agent.max_table_workers == 4
    assert MAX_CONCURRENT_LLM_CALLS == 32
