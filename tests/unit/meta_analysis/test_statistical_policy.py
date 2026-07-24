from __future__ import annotations

import math

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.analysis_method_selection.contextual.method import (
    Method as AnalysisMethod,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.overall_estimation.statistical.stats import (
    pool_rows as pool_overall_rows,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subgroup_analysis.statistical.stats import (
    pool_rows as pool_subgroup_rows,
)


def _binary_row(study_id: str, a: int, n1: int, c: int, n0: int) -> dict:
    return {
        "row_id": f"row::{study_id}",
        "setting_id": "setting-1",
        "study_id": study_id,
        "extraction_status": "extracted",
        "data_type": "Dichotomous",
        "subgroup": {"factor": None, "level": None},
        "result_data": {
            "experimental_events": a,
            "experimental_total": n1,
            "control_events": c,
            "control_total": n0,
        },
    }


def _continuous_row(
    study_id: str,
    m1: float,
    sd1: float,
    n1: int,
    m0: float,
    sd0: float,
    n0: int,
) -> dict:
    return {
        "row_id": f"row::{study_id}",
        "setting_id": "setting-1",
        "study_id": study_id,
        "extraction_status": "extracted",
        "data_type": "Continuous",
        "subgroup": {"factor": None, "level": None},
        "result_data": {
            "experimental_mean": m1,
            "experimental_sd": sd1,
            "experimental_total": n1,
            "control_mean": m0,
            "control_sd": sd0,
            "control_total": n0,
        },
        "continuous_effect_alignment": {
            "result_frame": "post_intervention",
            "change_score_definition": "not_applicable",
            "scale_direction": "higher_is_better",
            "effect_multiplier": 1,
            "status": "ready",
        },
    }


@pytest.mark.parametrize(
    ("data_type", "effect_measure", "model", "expected_method"),
    [
        ("Dichotomous", "Risk Ratio", "common_effect", "Mantel-Haenszel"),
        ("Dichotomous", "Odds Ratio", "common_effect", "Mantel-Haenszel"),
        ("Dichotomous", "Risk Difference", "common_effect", "Mantel-Haenszel"),
        ("Dichotomous", "Risk Ratio", "varying_effects", "Inverse Variance"),
        ("Continuous", "Mean Difference", "common_effect", "Inverse Variance"),
        ("Continuous", "Std. Mean Difference", "varying_effects", "Inverse Variance"),
    ],
)
def test_analysis_method_core_matrix(
    data_type: str,
    effect_measure: str,
    model: str,
    expected_method: str,
) -> None:
    rows = (
        [_binary_row("one", 10, 100, 20, 100), _binary_row("two", 5, 80, 10, 80)]
        if data_type == "Dichotomous"
        else [
            _continuous_row("one", 12, 4, 50, 10, 4, 50),
            _continuous_row("two", 18, 6, 60, 15, 5, 60),
        ]
    )
    setting = {
        "setting_id": "setting-1",
        "data_type": data_type,
        "subgroup": {"factor": None, "level": None},
        "source_context": {
            "setting_definition": {
                "planned_effect_measure": effect_measure,
                "clinical_model_assumption": model,
                "continuous_result_frame_priority": ["post_intervention"],
            }
        },
    }

    decision = AnalysisMethod().run(
        instance={"analysis_setting": setting, "meta_analysis_data_rows": rows}
    )[0]

    assert decision["method_status"] == "ready"
    assert decision["statistical_method"] == expected_method
    assert decision["analysis_model"] == (
        "random_effects" if model == "varying_effects" else "fixed_effect"
    )
    assert decision["heterogeneity_estimator"] == (
        "REML" if model == "varying_effects" else None
    )
    assert decision["interval_method"] == "Wald"


@pytest.mark.parametrize(
    ("measure", "expected"),
    [
        ("Risk Ratio", 2.0),
        ("Odds Ratio", 2.25),
        ("Risk Difference", 0.1),
    ],
)
def test_single_study_binary_effects_match_direct_calculation(
    measure: str,
    expected: float,
) -> None:
    pooled = pool_overall_rows(
        rows=[_binary_row("one", 20, 100, 10, 100)],
        data_type="Dichotomous",
        effect_measure=measure,
        analysis_model="fixed_effect",
        statistical_method="Mantel-Haenszel",
    )

    assert pooled is not None
    assert pooled["effect_value"] == pytest.approx(expected)
    assert pooled["participant_count"] == 200


def test_mantel_haenszel_name_from_method_selection_is_applied() -> None:
    rows = [
        _binary_row("one", 1, 10, 8, 10),
        _binary_row("two", 9, 100, 10, 100),
    ]
    kwargs = {
        "rows": rows,
        "data_type": "Dichotomous",
        "effect_measure": "Risk Ratio",
        "analysis_model": "fixed_effect",
        "statistical_method": "Mantel-Haenszel",
    }

    overall = pool_overall_rows(**kwargs)
    subgroup = pool_subgroup_rows(**kwargs)

    assert overall is not None and subgroup is not None
    assert overall["statistical_method"] == "Mantel-Haenszel"
    assert subgroup["statistical_method"] == "Mantel-Haenszel"
    assert subgroup["effect_value"] == pytest.approx(overall["effect_value"])


def test_meta_analysis_data_rows_return_single_study_weights() -> None:
    rows = [
        _binary_row("one", 10, 100, 20, 100),
        _binary_row("two", 5, 80, 10, 80),
    ]
    pooled = pool_overall_rows(
        rows=rows,
        data_type="Dichotomous",
        effect_measure="Risk Ratio",
        analysis_model="fixed_effect",
        statistical_method="Mantel-Haenszel",
        estimate_id="overall-estimate::setting-1",
        estimate_scope="overall",
        method_id="method-1",
    )

    assert pooled is not None
    data_rows = pooled["meta_analysis_data_rows"]
    assert {row["analysis_status"] for row in data_rows} == {"included"}
    assert sum(row["weight_fraction"] for row in data_rows) == pytest.approx(1.0)
    assert all(row["estimate_id"] == "overall-estimate::setting-1" for row in data_rows)
    assert all(row["variance"] > 0 and row["standard_error"] > 0 for row in data_rows)


def test_direction_alignment_changes_effect_but_not_weight() -> None:
    row = _continuous_row("one", 2, 4, 50, 5, 4, 50)
    positive = pool_overall_rows(
        rows=[row],
        data_type="Continuous",
        effect_measure="Mean Difference",
        analysis_model="fixed_effect",
    )
    reversed_row = {**row, "continuous_effect_alignment": {"effect_multiplier": -1}}
    reversed_result = pool_overall_rows(
        rows=[reversed_row],
        data_type="Continuous",
        effect_measure="Mean Difference",
        analysis_model="fixed_effect",
    )

    assert positive is not None and reversed_result is not None
    left = positive["meta_analysis_data_rows"][0]
    right = reversed_result["meta_analysis_data_rows"][0]
    assert right["effect_value"] == pytest.approx(-left["effect_value"])
    assert right["variance"] == pytest.approx(left["variance"])
    assert right["weight_fraction"] == pytest.approx(left["weight_fraction"])


def test_random_effects_heterogeneity_uses_fixed_inverse_variance_centre() -> None:
    specs = [(-2.0, 1.0, 20), (0.0, 2.0, 30), (1.0, 4.0, 40), (5.0, 1.5, 50)]
    rows = [
        _continuous_row(f"study-{index}", mean, sd, total, 0, sd, total)
        for index, (mean, sd, total) in enumerate(specs, start=1)
    ]
    variances = [2 * sd * sd / total for _, sd, total in specs]
    effects = [mean for mean, _, _ in specs]
    fixed_weights = [1 / variance for variance in variances]
    fixed_centre = sum(
        weight * effect for weight, effect in zip(fixed_weights, effects)
    ) / sum(fixed_weights)
    expected_q = sum(
        weight * (effect - fixed_centre) ** 2
        for weight, effect in zip(fixed_weights, effects)
    )
    kwargs = {
        "rows": rows,
        "data_type": "Continuous",
        "effect_measure": "Mean Difference",
        "analysis_model": "random_effects",
    }

    overall = pool_overall_rows(**kwargs)
    subgroup = pool_subgroup_rows(**kwargs)

    assert overall is not None and subgroup is not None
    assert overall["chi2"] == pytest.approx(expected_q)
    assert subgroup["chi2"] == pytest.approx(expected_q)
    assert overall["i2"] == pytest.approx(subgroup["i2"])


def test_md_and_hedges_g_match_direct_single_study_formulas() -> None:
    row = _continuous_row("one", 12, 4, 50, 10, 4, 50)
    md = pool_overall_rows(
        rows=[row],
        data_type="Continuous",
        effect_measure="Mean Difference",
        analysis_model="fixed_effect",
    )
    smd = pool_overall_rows(
        rows=[row],
        data_type="Continuous",
        effect_measure="Std. Mean Difference",
        analysis_model="fixed_effect",
        smd_method="Hedges_g",
    )
    correction = 1 - 3 / (4 * 98 - 1)

    assert md is not None and md["effect_value"] == pytest.approx(2.0)
    assert smd is not None
    assert smd["effect_value"] == pytest.approx(correction * 0.5)


def test_hedges_g_variance_matches_revman_n_minus_3_94_formula() -> None:
    row = _continuous_row("one", 12, 4, 50, 10, 4, 50)
    pooled = pool_overall_rows(
        rows=[row],
        data_type="Continuous",
        effect_measure="Std. Mean Difference",
        analysis_model="fixed_effect",
        smd_method="Hedges_g",
    )

    assert pooled is not None
    g_value = pooled["analysis_effect"]
    expected_variance = 100 / (50 * 50) + g_value**2 / (2 * (100 - 3.94))
    assert pooled["meta_analysis_data_rows"][0]["variance"] == pytest.approx(
        expected_variance
    )


def test_fixed_mh_rr_uses_observed_counts_when_one_study_has_a_zero_cell() -> None:
    pooled = pool_overall_rows(
        rows=[
            _binary_row("one", 1, 10, 0, 10),
            _binary_row("two", 2, 10, 1, 10),
        ],
        data_type="Dichotomous",
        effect_measure="Risk Ratio",
        analysis_model="fixed_effect",
        statistical_method="Mantel-Haenszel",
        zero_cell_handling={"correction_value": 0.5},
    )

    assert pooled is not None
    # R = 1*10/20 + 2*10/20; S = 0*10/20 + 1*10/20.
    assert pooled["effect_value"] == pytest.approx(3.0)
    weights = {
        row["study_id"]: row["weight_fraction"]
        for row in pooled["meta_analysis_data_rows"]
    }
    assert weights == pytest.approx({"one": 0.0, "two": 1.0})


def test_fixed_mh_risk_difference_keeps_double_zero_study_consistently() -> None:
    pooled = pool_overall_rows(
        rows=[
            _binary_row("double-zero", 0, 10, 0, 10),
            _binary_row("informative", 2, 10, 1, 10),
        ],
        data_type="Dichotomous",
        effect_measure="Risk Difference",
        analysis_model="fixed_effect",
        statistical_method="Mantel-Haenszel",
    )

    assert pooled is not None
    assert pooled["effect_value"] == pytest.approx(0.05)
    assert pooled["included_study_ids"] == ["double-zero", "informative"]
    assert pooled["participant_count"] == 40
    assert sum(
        row["weight_fraction"] for row in pooled["meta_analysis_data_rows"]
    ) == pytest.approx(1.0)


def test_random_effect_i2_uses_reml_tau2_and_typical_within_study_variance() -> None:
    rows = [
        _continuous_row(f"study-{index}", effect, 2, 40, 0, 2, 40)
        for index, effect in enumerate((-1.0, 0.0, 1.5, 3.0, 5.0), start=1)
    ]
    pooled = pool_overall_rows(
        rows=rows,
        data_type="Continuous",
        effect_measure="Mean Difference",
        analysis_model="random_effects",
    )

    assert pooled is not None
    fixed_weights = [1 / 0.2] * 5
    weight_sum = sum(fixed_weights)
    typical_variance = 4 * weight_sum / (
        weight_sum**2 - sum(weight**2 for weight in fixed_weights)
    )
    expected = pooled["tau2"] / (pooled["tau2"] + typical_variance) * 100
    assert pooled["i2"] == pytest.approx(expected)
    assert pooled["i2_method"] == "tau2_typical_within_study_variance"


def test_random_effect_defaults_to_reml_wald_and_prediction_interval_requires_five_studies() -> None:
    rows = [
        _continuous_row(f"study-{index}", effect, 2, 40, 0, 2, 40)
        for index, effect in enumerate((-1.0, 0.0, 1.5, 3.0, 5.0), start=1)
    ]
    four = pool_overall_rows(
        rows=rows[:4],
        data_type="Continuous",
        effect_measure="Mean Difference",
        analysis_model="random_effects",
        interval_method="Wald",
        prediction_interval_enabled=True,
    )
    five = pool_overall_rows(
        rows=rows,
        data_type="Continuous",
        effect_measure="Mean Difference",
        analysis_model="random_effects",
        interval_method="Wald",
        prediction_interval_enabled=True,
    )

    assert four is not None and five is not None
    assert four["tau2"] > 0 and five["tau2"] > 0
    assert four["interval_method"] == "Wald"
    assert four["prediction_interval"] is None
    assert five["prediction_interval"] is not None
    assert five["prediction_interval"]["lower"] < five["effect_value"]
    assert five["prediction_interval"]["upper"] > five["effect_value"]


def test_hksj_is_explicit_and_falls_back_for_two_studies() -> None:
    two_rows = [
        _continuous_row("one", -1, 2, 40, 0, 2, 40),
        _continuous_row("two", 5, 2, 40, 0, 2, 40),
    ]
    fallback = pool_overall_rows(
        rows=two_rows,
        data_type="Continuous",
        effect_measure="Mean Difference",
        analysis_model="random_effects",
        interval_method="HKSJ",
    )
    applied = pool_overall_rows(
        rows=two_rows
        + [_continuous_row("three", 2, 2, 40, 0, 2, 40)],
        data_type="Continuous",
        effect_measure="Mean Difference",
        analysis_model="random_effects",
        interval_method="HKSJ",
    )

    assert fallback is not None and fallback["interval_method"] == "Wald"
    assert "requires more than two studies" in fallback["method_note"]
    assert applied is not None and applied["interval_method"] == "HKSJ"
    assert applied["effect_test"]["statistic_name"] == "t"


def test_overall_and_subgroup_engines_agree_for_the_same_rows() -> None:
    rows = [
        _continuous_row("one", 12, 4, 50, 10, 4, 50),
        _continuous_row("two", 9, 3, 30, 10, 3, 30),
    ]
    kwargs = {
        "rows": rows,
        "data_type": "Continuous",
        "effect_measure": "Mean Difference",
        "analysis_model": "random_effects",
        "interval_method": "Wald",
    }

    overall = pool_overall_rows(**kwargs)
    subgroup = pool_subgroup_rows(**kwargs)

    assert overall is not None and subgroup is not None
    for field in ("effect_value", "ci_lower", "ci_upper", "tau2", "chi2", "i2"):
        assert subgroup[field] == pytest.approx(overall[field])
    assert math.isfinite(overall["effect_value"])


def test_missing_multi_study_model_is_not_inferred_from_heterogeneity() -> None:
    setting = {
        "setting_id": "setting-1",
        "data_type": "Dichotomous",
        "subgroup": {"factor": None, "level": None},
        "source_context": {
            "setting_definition": {"planned_effect_measure": "Risk Ratio"}
        },
    }
    rows = [_binary_row("one", 1, 10, 2, 10), _binary_row("two", 8, 10, 1, 10)]

    decision = AnalysisMethod().run(
        instance={"analysis_setting": setting, "meta_analysis_data_rows": rows}
    )[0]

    assert decision["method_status"] == "invalid_plan"
    assert decision["status"] == "not_supported"


def test_missing_effect_measure_is_an_invalid_plan() -> None:
    setting = {
        "setting_id": "setting-1",
        "data_type": "Dichotomous",
        "subgroup": {"factor": None, "level": None},
        "source_context": {
            "setting_definition": {
                "clinical_model_assumption": "common_effect",
            }
        },
    }

    decision = AnalysisMethod().run(
        instance={
            "analysis_setting": setting,
                "meta_analysis_data_rows": [_binary_row("one", 1, 10, 2, 10)],
        }
    )[0]

    assert decision["method_status"] == "invalid_plan"
    assert decision["effect_measure"] == ""
    assert decision["statistical_method"] == ""


def test_single_study_retains_planned_varying_effects_model() -> None:
    setting = {
        "setting_id": "setting-1",
        "data_type": "Dichotomous",
        "subgroup": {"factor": None, "level": None},
        "source_context": {
            "setting_definition": {
                "planned_effect_measure": "Risk Ratio",
                "clinical_model_assumption": "varying_effects",
            }
        },
    }

    decision = AnalysisMethod().run(
        instance={
            "analysis_setting": setting,
            "meta_analysis_data_rows": [_binary_row("one", 1, 10, 2, 10)],
        }
    )[0]

    assert decision["method_status"] == "ready"
    assert decision["analysis_model"] == "random_effects"
    assert decision["heterogeneity_estimator"] is None
    assert decision["prediction_interval_enabled"] is False


def test_method_selection_enables_prediction_interval_only_at_five_studies() -> None:
    setting = {
        "setting_id": "setting-1",
        "data_type": "Continuous",
        "subgroup": {"factor": None, "level": None},
        "source_context": {
            "setting_definition": {
            "planned_effect_measure": "Mean Difference",
            "clinical_model_assumption": "varying_effects",
            "continuous_result_frame_priority": ["post_intervention"],
            }
        },
    }
    rows = [
        _continuous_row(f"study-{index}", index, 2, 40, 0, 2, 40)
        for index in range(1, 6)
    ]

    four = AnalysisMethod().run(
        instance={"analysis_setting": setting, "meta_analysis_data_rows": rows[:4]}
    )[0]
    five = AnalysisMethod().run(
        instance={"analysis_setting": setting, "meta_analysis_data_rows": rows}
    )[0]

    assert four["prediction_interval_enabled"] is False
    assert five["prediction_interval_enabled"] is True


def test_effect_measure_must_match_data_type() -> None:
    setting = {
        "setting_id": "setting-1",
        "data_type": "Dichotomous",
        "subgroup": {"factor": None, "level": None},
        "source_context": {
            "setting_definition": {
                "planned_effect_measure": "Mean Difference",
                "clinical_model_assumption": "common_effect",
            }
        },
    }

    decision = AnalysisMethod().run(
        instance={
            "analysis_setting": setting,
            "meta_analysis_data_rows": [_binary_row("one", 1, 10, 2, 10)],
        }
    )[0]

    assert decision["method_status"] == "incompatible_effect_measure"
    assert decision["effect_measure"] == "Mean Difference"
