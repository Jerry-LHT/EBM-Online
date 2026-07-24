from __future__ import annotations

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subgroup_analysis.statistical.method import (
    Method,
)


def _row(
    *,
    setting_id: str,
    study_id: str,
    level: str,
    experimental_mean: float,
    control_mean: float,
) -> dict:
    return {
        "data_row_id": f"row::{setting_id}::{study_id}",
        "setting_id": setting_id,
        "setting_family_id": "family-1",
        "study_id": study_id,
        "extraction_status": "extracted",
        "data_type": "Continuous",
        "subgroup": {
            "factor": "sex",
            "level": level,
            "scope": "participant_level",
            "membership_relation": "mutually_exclusive",
        },
        "result_data": {
            "experimental_mean": experimental_mean,
            "experimental_sd": 2.0,
            "experimental_total": 20,
            "control_mean": control_mean,
            "control_sd": 2.0,
            "control_total": 20,
        },
        "continuous_effect_alignment": {"effect_multiplier": 1},
    }


def _instance(*, setting_id: str, level: str, rows: list[dict], relation: str = "mutually_exclusive") -> dict:
    subgroup = {
        "factor": "sex",
        "level": level,
        "scope": "participant_level",
        "membership_relation": relation,
    }
    normalized_rows = [
        {**row, "subgroup": subgroup}
        for row in rows
    ]
    return {
        "instance_id": f"instance::{setting_id}",
        "analysis_setting": {
            "setting_id": setting_id,
            "setting_family_id": "family-1",
            "comparison": {"experimental": "treatment", "comparator": "control"},
            "outcome": {"label": "score", "measure": "scale"},
            "timepoint": {"label": "week 8"},
            "subgroup": subgroup,
            "data_type": "Continuous",
        },
        "meta_analysis_data_rows": normalized_rows,
        "analysis_methods": [
            {
                "method_id": f"method::{setting_id}",
                "method_status": "ready",
                "effect_measure": "Mean Difference",
                "analysis_model": "fixed_effect",
                "statistical_method": "Inverse Variance",
                "interval_method": "Wald",
                "ci_level": "95%",
                "analysis_included_study_ids": ["study-1", "study-2"],
            }
        ],
    }


def _paired_instances(*, relation: str = "mutually_exclusive") -> list[dict]:
    male_rows = [
        _row(
            setting_id="male",
            study_id="study-1",
            level="Male",
            experimental_mean=5,
            control_mean=3,
        ),
        _row(
            setting_id="male",
            study_id="study-2",
            level="Male",
            experimental_mean=6,
            control_mean=3,
        ),
    ]
    female_rows = [
        _row(
            setting_id="female",
            study_id="study-1",
            level="Female",
            experimental_mean=4,
            control_mean=3,
        ),
        _row(
            setting_id="female",
            study_id="study-2",
            level="Female",
            experimental_mean=3,
            control_mean=3,
        ),
    ]
    return [
        _instance(setting_id="male", level="Male", rows=male_rows, relation=relation),
        _instance(setting_id="female", level="Female", rows=female_rows, relation=relation),
    ]


def _binary_row(
    *,
    setting_id: str,
    study_id: str,
    level: str,
    experimental_events: int,
    experimental_total: int,
    control_events: int,
    control_total: int,
) -> dict:
    return {
        "data_row_id": f"row::{setting_id}::{study_id}",
        "setting_id": setting_id,
        "setting_family_id": "binary-family",
        "study_id": study_id,
        "extraction_status": "extracted",
        "data_type": "Dichotomous",
        "subgroup": {
            "factor": "sex",
            "level": level,
            "scope": "participant_level",
            "membership_relation": "mutually_exclusive",
        },
        "result_data": {
            "experimental_events": experimental_events,
            "experimental_total": experimental_total,
            "control_events": control_events,
            "control_total": control_total,
        },
    }


def _binary_instance(*, setting_id: str, level: str, rows: list[dict]) -> dict:
    subgroup = {
        "factor": "sex",
        "level": level,
        "scope": "participant_level",
        "membership_relation": "mutually_exclusive",
    }
    return {
        "instance_id": f"instance::{setting_id}",
        "analysis_setting": {
            "setting_id": setting_id,
            "setting_family_id": "binary-family",
            "comparison": {"experimental": "treatment", "comparator": "control"},
            "outcome": {"label": "response", "measure": "participants responding"},
            "timepoint": {"label": "week 8"},
            "subgroup": subgroup,
            "data_type": "Dichotomous",
        },
        "meta_analysis_data_rows": rows,
        "analysis_methods": [
            {
                "method_id": f"method::{setting_id}",
                "method_status": "ready",
                "effect_measure": "Risk Ratio",
                "analysis_model": "fixed_effect",
                "statistical_method": "Mantel-Haenszel",
                "interval_method": "Wald",
                "ci_level": "95%",
                "analysis_included_study_ids": ["study-1", "study-2"],
            }
        ],
    }


def _paired_binary_instances() -> list[dict]:
    female = [
        _binary_row(
            setting_id="female-binary",
            study_id="study-1",
            level="Female",
            experimental_events=20,
            experimental_total=40,
            control_events=10,
            control_total=40,
        ),
        _binary_row(
            setting_id="female-binary",
            study_id="study-2",
            level="Female",
            experimental_events=15,
            experimental_total=30,
            control_events=10,
            control_total=30,
        ),
    ]
    male = [
        _binary_row(
            setting_id="male-binary",
            study_id="study-1",
            level="Male",
            experimental_events=10,
            experimental_total=40,
            control_events=10,
            control_total=40,
        ),
        _binary_row(
            setting_id="male-binary",
            study_id="study-2",
            level="Male",
            experimental_events=6,
            experimental_total=40,
            control_events=8,
            control_total=40,
        ),
    ]
    return [
        _binary_instance(setting_id="female-binary", level="Female", rows=female),
        _binary_instance(setting_id="male-binary", level="Male", rows=male),
    ]


def test_participant_subgroup_pools_within_study_interactions() -> None:
    result = Method().run(instances=_paired_instances())
    test = result["instance::male"]["subgroup_difference_tests"][0]

    assert test["test_status"] == "computed"
    assert test["test_method"] == "within_study_interaction"
    assert test["subgroup_scope"] == "participant_level"
    # Levels are deterministically ordered Female then Male. Study-specific
    # interactions are -1 and -3, so their equal-weight pooled value is -2.
    assert (test["level_a"], test["level_b"]) == ("Female", "Male")
    assert test["interaction_effect_value"] == pytest.approx(-2.0)
    assert test["paired_study_ids"] == ["study-1", "study-2"]
    assert test["paired_study_count"] == 2
    assert test["interaction_ci_lower"] < test["interaction_effect_value"]
    assert test["interaction_ci_upper"] > test["interaction_effect_value"]


def test_binary_participant_subgroup_uses_ratio_of_risk_ratios_and_returns_weights() -> None:
    result = Method().run(instances=_paired_binary_instances())
    test = result["instance::female-binary"]["subgroup_difference_tests"][0]

    assert test["test_status"] == "computed"
    assert test["test_method"] == "within_study_interaction"
    assert test["interaction_scale"] == "ratio_of_ratios"
    assert (test["level_a"], test["level_b"]) == ("Female", "Male")
    # Each study has a female RR exactly twice its male RR, so the pooled
    # within-study ratio of risk ratios must remain 2 regardless of weights.
    assert test["interaction_effect_value"] == pytest.approx(2.0)
    assert test["paired_study_ids"] == ["study-1", "study-2"]
    assert test["interaction_ci_lower"] < test["interaction_effect_value"]
    assert test["interaction_ci_upper"] > test["interaction_effect_value"]

    for instance_id in ("instance::female-binary", "instance::male-binary"):
        rows = result[instance_id]["meta_analysis_data_rows"]
        assert {row["analysis_status"] for row in rows} == {"included"}
        assert sum(row["weight_fraction"] for row in rows) == pytest.approx(1.0)
        assert all(row["weight"] > 0 for row in rows)


@pytest.mark.parametrize("relation", ["overlapping", "unknown"])
def test_participant_subgroup_rejects_non_independent_membership(relation: str) -> None:
    result = Method().run(instances=_paired_instances(relation=relation))
    test = result["instance::male"]["subgroup_difference_tests"][0]

    assert test["test_status"] == "not_applicable"
    assert test["test_method"] == "within_study_interaction"
    assert "mutually exclusive" in test["test_notes"]


def test_participant_subgroup_requires_two_paired_studies() -> None:
    instances = _paired_instances()
    instances[1]["meta_analysis_data_rows"] = [
        row
        for row in instances[1]["meta_analysis_data_rows"]
        if row["study_id"] == "study-1"
    ]
    instances[1]["analysis_methods"][0]["analysis_included_study_ids"] = ["study-1"]

    result = Method().run(instances=instances)
    test = result["instance::male"]["subgroup_difference_tests"][0]

    assert test["test_status"] == "insufficient_paired_studies"
    assert test["paired_study_ids"] == ["study-1"]
