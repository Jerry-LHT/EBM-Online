from __future__ import annotations

from benchmark.online_pipeline.meta_analysis.evaluation_common import method_adapters


def _instance(instance_id: str = "instance-1") -> dict:
    return {
        "instance_id": instance_id,
        "review_id": "review-1",
        "analysis_setting": {
            "setting_id": "setting-1",
            "setting_family_id": "family-1",
            "candidate_id": "benchmark-candidate-1",
        },
    }


def test_subtask5_production_adapter_adds_benchmark_only_candidate_id(
    monkeypatch,
) -> None:
    class StubMethod:
        def run(self, *, instance):
            return [{"overall_estimate_id": "estimate-1", "setting_id": "setting-1"}]

    monkeypatch.setattr(
        method_adapters,
        "build_production_overall_estimates_method",
        lambda: StubMethod(),
    )

    prediction = method_adapters.predict_subtask5(
        instance=_instance(),
        gold={},
        method="method_production",
    )

    assert prediction["overall_estimates"] == [
        {
            "overall_estimate_id": "estimate-1",
            "setting_id": "setting-1",
            "candidate_id": "benchmark-candidate-1",
        }
    ]


def test_subtask4_production_adapter_adds_benchmark_only_candidate_id(
    monkeypatch,
) -> None:
    class StubMethod:
        def run(self, *, instances):
            return {
                str(instance["instance_id"]): {
                    "subgroup_estimates": [
                        {"subgroup_estimate_id": "subgroup-1"}
                    ],
                    "subgroup_difference_tests": [
                        {"subgroup_difference_test_id": "test-1"}
                    ],
                }
                for instance in instances
            }

    monkeypatch.setattr(
        method_adapters,
        "build_production_subgroup_analysis_method",
        lambda: StubMethod(),
    )

    prediction = method_adapters.predict_subtask4(
        instances=[_instance()],
        gold_by_id={},
        method="method_production",
    )[0]

    assert prediction["subgroup_results"]["subgroup_estimates"][0][
        "candidate_id"
    ] == "benchmark-candidate-1"
    assert prediction["subgroup_results"]["subgroup_difference_tests"][0][
        "candidate_id"
    ] == "benchmark-candidate-1"


def test_subtask2_production_adapter_calls_article_evidence_without_gold_values(
    monkeypatch,
) -> None:
    captured = {}

    class StubMethod:
        def run(self, **kwargs):
            captured.update(kwargs)
            target = kwargs["targets"][0]
            return {
                "study_result_rows": [
                    {
                        "row_id": "row-1",
                        "setting_id": target["target_id"],
                        "study_id": kwargs["study_id"],
                        "data_type": target["data_type"],
                        "result_items": [],
                    }
                ]
            }

    instance = {
        "instance_id": "instance-1",
        "review_id": "review-1",
        "included_studies": ["study-1"],
        "article_study_links": [{"study_id": "study-1", "article_id": "article-1"}],
        "analysis_setting": {
            "setting_id": "setting-1",
            "population_scope": "adults",
            "comparison": {"experimental": "treatment", "comparator": "control"},
            "outcome": {"label": "pain"},
            "timepoint": {"label": "7 days"},
            "subgroup": {"factor": None, "level": None},
            "data_type": "Dichotomous",
            "result_selection_policy": {"tie_policy": "unresolved"},
            "effect_measure_plan": "Risk Ratio",
        },
    }
    article = {"study_id": "study-1", "article_id": "article-1", "tables": []}
    monkeypatch.setattr(method_adapters, "load_articles_for_instance", lambda **_kwargs: [article])
    monkeypatch.setattr(method_adapters, "build_study_evidence_method", lambda: StubMethod())

    prediction = method_adapters.predict_subtask2(
        instance=instance,
        gold={"private_gold_numeric_value": 999},
        method="method_article_evidence_agent",
        dataset_dir="unused",
    )

    assert prediction["study_result_rows"][0]["setting_id"].startswith("target::setting-1")
    assert captured["article"] is article
    assert captured["targets"][0]["outcome"] == {"label": "pain"}
    assert captured["targets"][0]["data_type"] == "Dichotomous"
    assert "private_gold_numeric_value" not in str(captured)
