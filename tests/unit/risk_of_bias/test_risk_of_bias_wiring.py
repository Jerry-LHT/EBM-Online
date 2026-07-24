from __future__ import annotations

import pytest

from benchmark.online_pipeline.risk_of_bias.evaluation.method_adapter import (
    load_risk_of_bias_benchmark_method,
)
from ebm_backend.online_pipeline.application.use_cases.run_risk_of_bias import (
    RiskOfBiasArticleContentMissingError,
    RunRiskOfBias,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.factory import (
    build_production_risk_of_bias,
)


class _FakeAssessor:
    def assess(self, **kwargs):
        return kwargs


class _FakeArticle:
    def __init__(self, study_id: str, text: str = "Full text") -> None:
        self.study_id = study_id
        self.xml_content = type(
            "XmlContent",
            (),
            {"sections": [type("Section", (), {"text": text})()]},
        )()


def test_use_case_delegates_to_risk_of_bias_port() -> None:
    use_case = RunRiskOfBias(risk_of_bias_assessor=_FakeAssessor())

    result = use_case.execute(
        included_studies=["study-1"],
        articles=[_FakeArticle("study-1")],  # type: ignore[list-item]
    )

    assert result[0]["study_id"] == "study-1"
    assert result[0]["article"].study_id == "study-1"
    assert result[0]["domain_config"].assessed_domains == [
        "random_sequence_generation",
        "allocation_concealment",
        "blinding_participants_personnel",
        "blinding_outcome_assessment",
        "incomplete_outcome_data",
        "selective_reporting",
        "other_bias",
    ]


def test_use_case_rejects_missing_article_instead_of_reusing_single_article() -> None:
    use_case = RunRiskOfBias(risk_of_bias_assessor=_FakeAssessor())
    only_article = _FakeArticle("source-study")

    with pytest.raises(ValueError, match="Missing CleanedArticle"):
        use_case.execute(
            included_studies=["requested-study", "missing-study"],
            articles=[only_article],  # type: ignore[list-item]
        )


def test_use_case_rejects_unmatched_study_when_multiple_articles_exist() -> None:
    use_case = RunRiskOfBias(risk_of_bias_assessor=_FakeAssessor())

    with pytest.raises(ValueError, match="missing"):
        use_case.execute(
            included_studies=["study-1", "missing", "study-2"],
            articles=[_FakeArticle("study-1"), _FakeArticle("study-2")],  # type: ignore[list-item]
        )


def test_use_case_rejects_empty_full_text_before_calling_assessor() -> None:
    use_case = RunRiskOfBias(risk_of_bias_assessor=_FakeAssessor())

    with pytest.raises(RiskOfBiasArticleContentMissingError) as raised:
        use_case.execute(
            included_studies=["study-1"],
            articles=[_FakeArticle("study-1", "   ")],  # type: ignore[list-item]
        )

    assert raised.value.study_ids == ["study-1"]


def test_use_case_rejects_unexpected_article() -> None:
    use_case = RunRiskOfBias(risk_of_bias_assessor=_FakeAssessor())

    with pytest.raises(ValueError, match="non-included"):
        use_case.execute(
            included_studies=["study-1"],
            articles=[
                _FakeArticle("study-1"),
                _FakeArticle("extra"),
            ],  # type: ignore[list-item]
        )


def test_use_case_enforces_five_hundred_study_limit() -> None:
    use_case = RunRiskOfBias(risk_of_bias_assessor=_FakeAssessor())

    with pytest.raises(ValueError, match="at most 500"):
        use_case.execute(
            included_studies=[f"study-{index}" for index in range(501)],
            articles=[],
        )


def test_use_case_preserves_input_order_under_study_concurrency() -> None:
    use_case = RunRiskOfBias(
        risk_of_bias_assessor=_FakeAssessor(),
        max_workers=2,
    )

    result = use_case.execute(
        included_studies=["study-2", "study-1"],
        articles=[
            _FakeArticle("study-1"),
            _FakeArticle("study-2"),
        ],  # type: ignore[list-item]
    )

    assert [item["study_id"] for item in result] == ["study-2", "study-1"]


@pytest.mark.parametrize(
    "method_name",
    ["method_onestep_llm", "method_calibrated_slots", "method_hybrid_slots"],
)
def test_benchmark_adapter_loads_risk_of_bias_methods(method_name: str) -> None:
    assert callable(load_risk_of_bias_benchmark_method(method_name).assess)


def test_factory_builds_selected_production_risk_of_bias_method() -> None:
    assert callable(build_production_risk_of_bias().assess)


def test_benchmark_adapter_loads_risk_of_bias_method() -> None:
    assert callable(
        load_risk_of_bias_benchmark_method("risk_of_bias.method_onestep_llm").assess
    )


def test_benchmark_adapter_rejects_unknown_risk_of_bias_method() -> None:
    with pytest.raises(ValueError, match="Unknown Risk of Bias benchmark method"):
        load_risk_of_bias_benchmark_method("unknown")
