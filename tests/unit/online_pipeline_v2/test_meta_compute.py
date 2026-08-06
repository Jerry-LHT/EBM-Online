from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest


_SCRIPT = (
    Path(__file__).parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/"
    "agent_execution/skills/evidence_synthesis/synthesize-evidence/scripts/meta_compute.py"
)
_SPEC = importlib.util.spec_from_file_location("v2_meta_compute", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
meta_compute = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(meta_compute)


def _dich(
    study_id: str,
    experimental_cases: int,
    experimental_n: int,
    control_cases: int,
    control_n: int,
) -> dict[str, int | str]:
    return {
        "study_id": study_id,
        "experimental_cases": experimental_cases,
        "experimental_n": experimental_n,
        "control_cases": control_cases,
        "control_n": control_n,
    }


def _continuous(
    study_id: str,
    experimental_n: int,
    experimental_mean: float,
    experimental_sd: float,
    control_n: int,
    control_mean: float,
    control_sd: float,
) -> dict[str, int | float | str]:
    return {
        "study_id": study_id,
        "experimental_n": experimental_n,
        "experimental_mean": experimental_mean,
        "experimental_sd": experimental_sd,
        "control_n": control_n,
        "control_mean": control_mean,
        "control_sd": control_sd,
    }


@pytest.mark.parametrize(
    ("specification", "expected_measure"),
    [
        (
            {
                "data_type": "dichotomous",
                "effect_measure": "RR",
                "statistical_method": "MH",
                "analysis_model": "fixed",
                "studies": [
                    _dich("a", 10, 100, 20, 100),
                    _dich("b", 5, 50, 10, 50),
                ],
            },
            "RR",
        ),
        (
            {
                "data_type": "dichotomous",
                "effect_measure": "OR",
                "statistical_method": "Peto",
                "analysis_model": "fixed",
                "studies": [
                    _dich("a", 2, 100, 4, 100),
                    _dich("b", 3, 150, 5, 150),
                ],
            },
            "OR",
        ),
        (
            {
                "data_type": "dichotomous",
                "effect_measure": "RD",
                "statistical_method": "IV",
                "analysis_model": "fixed",
                "studies": [
                    _dich("a", 10, 100, 20, 100),
                    _dich("b", 15, 100, 20, 100),
                ],
            },
            "RD",
        ),
        (
            {
                "data_type": "continuous",
                "effect_measure": "MD",
                "statistical_method": "IV",
                "analysis_model": "fixed",
                "studies": [
                    _continuous("a", 50, 8.0, 2.0, 50, 10.0, 2.5),
                    _continuous("b", 40, 7.5, 2.2, 42, 9.0, 2.1),
                ],
            },
            "MD",
        ),
        (
            {
                "data_type": "continuous",
                "effect_measure": "SMD",
                "statistical_method": "IV",
                "analysis_model": "random",
                "heterogeneity_estimator": "DL",
                "studies": [
                    _continuous("a", 50, 8.0, 2.0, 50, 10.0, 2.5),
                    _continuous("b", 40, 7.5, 2.2, 42, 9.0, 2.1),
                ],
            },
            "SMD",
        ),
        (
            {
                "data_type": "giv",
                "effect_measure": "RATIO",
                "statistical_method": "IV",
                "analysis_model": "random",
                "heterogeneity_estimator": "REML",
                "studies": [
                    {"study_id": "a", "effect": math.log(0.8), "se": 0.1},
                    {"study_id": "b", "effect": math.log(0.7), "se": 0.15},
                ],
            },
            "RATIO",
        ),
        (
            {
                "data_type": "oev",
                "effect_measure": "LOG_HR",
                "statistical_method": "IV",
                "analysis_model": "fixed",
                "studies": [
                    {"study_id": "a", "o_minus_e": -2.0, "variance": 10.0},
                    {"study_id": "b", "o_minus_e": -1.0, "variance": 8.0},
                ],
            },
            "LOG_HR",
        ),
    ],
)
def test_supported_analysis_matrix(
    specification,
    expected_measure,
) -> None:
    result = meta_compute.compute_meta_analysis(specification)

    assert result["settings"]["effect_measure"] == expected_measure
    assert math.isfinite(result["overall"]["estimate"])
    assert result["overall"]["ci_start"] <= result["overall"]["ci_end"]
    assert len(result["input_digest"]) == len("sha256:") + 64
    assert len(result["output_digest"]) == len("sha256:") + 64


def test_giv_ratio_input_is_log_scale_and_display_is_anti_logged() -> None:
    result = meta_compute.compute_meta_analysis(
        {
            "data_type": "giv",
            "effect_measure": "RATIO",
            "statistical_method": "IV",
            "analysis_model": "fixed",
            "studies": [
                {"study_id": "a", "effect": math.log(0.8), "se": 0.1},
            ],
        }
    )

    assert result["studies"][0]["estimate"] == pytest.approx(0.8)
    assert result["overall"]["estimate"] == pytest.approx(0.8)


@pytest.mark.parametrize(
    "uncertainty",
    ({}, {"se": 0.1, "variance": 0.01}),
)
def test_giv_requires_exactly_one_uncertainty_input(uncertainty) -> None:
    with pytest.raises(meta_compute.MetaComputationError) as caught:
        meta_compute.compute_meta_analysis(
            {
                "data_type": "giv",
                "effect_measure": "DIFFERENCE",
                "statistical_method": "IV",
                "analysis_model": "fixed",
                "studies": [
                    {"study_id": "a", "effect": 0.2, **uncertainty},
                ],
            }
        )

    assert caught.value.code == "invalid_giv_uncertainty"


def test_mh_risk_ratio_matches_simple_common_effect() -> None:
    result = meta_compute.compute_meta_analysis(
        {
            "data_type": "dichotomous",
            "effect_measure": "RR",
            "statistical_method": "MH",
            "analysis_model": "fixed",
            "studies": [
                _dich("a", 10, 100, 20, 100),
                _dich("b", 5, 50, 10, 50),
            ],
        }
    )

    assert result["overall"]["estimate"] == pytest.approx(0.5)
    assert result["overall"]["tau2"] == 0
    assert result["overall"]["i2"] == 0


def test_zero_cell_rules_exclude_double_zero_but_keep_single_zero() -> None:
    result = meta_compute.compute_meta_analysis(
        {
            "data_type": "dichotomous",
            "effect_measure": "RR",
            "statistical_method": "IV",
            "analysis_model": "fixed",
            "studies": [
                _dich("double-zero", 0, 50, 0, 50),
                _dich("single-zero", 0, 50, 2, 50),
            ],
        }
    )

    assert [row["study_id"] for row in result["studies"]] == ["single-zero"]
    assert result["studies"][0]["continuity_correction"] == 0.5
    assert "double-zero" in result["warnings"][0]


def test_mh_applies_continuity_correction_per_study_before_pooling() -> None:
    result = meta_compute.compute_meta_analysis(
        {
            "data_type": "dichotomous",
            "effect_measure": "RR",
            "statistical_method": "MH",
            "analysis_model": "fixed",
            "studies": [
                _dich("single-zero", 0, 50, 2, 50),
                _dich("ordinary", 10, 100, 20, 100),
            ],
        }
    )

    assert result["overall"]["estimate"] == pytest.approx(7 / 15)
    corrected_weight = 2.5 * 51 / 102
    ordinary_weight = 20 * 100 / 200
    assert result["studies"][0]["weight_percent"] == pytest.approx(
        100 * corrected_weight / (corrected_weight + ordinary_weight)
    )


def test_ratio_measure_excludes_study_with_all_participants_as_events() -> None:
    result = meta_compute.compute_meta_analysis(
        {
            "data_type": "dichotomous",
            "effect_measure": "RR",
            "statistical_method": "IV",
            "analysis_model": "fixed",
            "studies": [
                _dich("all-events", 50, 50, 50, 50),
                _dich("informative", 10, 50, 20, 50),
            ],
        }
    )

    assert [row["study_id"] for row in result["studies"]] == ["informative"]
    assert "all-events" in result["warnings"][0]


def test_double_zero_is_available_for_risk_difference_with_correction() -> None:
    result = meta_compute.compute_meta_analysis(
        {
            "data_type": "dichotomous",
            "effect_measure": "RD",
            "statistical_method": "IV",
            "analysis_model": "fixed",
            "studies": [
                _dich("double-zero", 0, 50, 0, 50),
                _dich("events", 1, 50, 2, 50),
            ],
        }
    )

    assert [row["study_id"] for row in result["studies"]] == [
        "double-zero",
        "events",
    ]
    assert result["studies"][0]["continuity_correction"] == 0.5


def test_fixed_mh_uses_measure_specific_contribution_weights() -> None:
    result = meta_compute.compute_meta_analysis(
        {
            "data_type": "dichotomous",
            "effect_measure": "RR",
            "statistical_method": "MH",
            "analysis_model": "fixed",
            "studies": [
                _dich("a", 10, 100, 20, 100),
                _dich("b", 2, 50, 5, 50),
            ],
        }
    )

    # MH RR contribution is proportional to c*n_experimental/N.
    expected_a = (20 * 100 / 200) / (
        (20 * 100 / 200) + (5 * 50 / 100)
    )
    assert result["studies"][0]["weight_percent"] == pytest.approx(
        100 * expected_a
    )


def test_single_study_fixed_is_valid_but_random_is_typed_failure() -> None:
    specification = {
        "data_type": "giv",
        "effect_measure": "DIFFERENCE",
        "statistical_method": "IV",
        "analysis_model": "fixed",
        "studies": [{"study_id": "a", "effect": 1.2, "se": 0.2}],
    }
    fixed = meta_compute.compute_meta_analysis(specification)
    assert fixed["overall"]["study_count"] == 1

    with pytest.raises(meta_compute.MetaComputationError) as caught:
        meta_compute.compute_meta_analysis(
            {**specification, "analysis_model": "random"}
        )
    assert caught.value.code == "random_single_study"

    with pytest.raises(meta_compute.MetaComputationError) as hksj:
        meta_compute.compute_meta_analysis(
            {**specification, "ci_method": "HKSJ"}
        )
    assert hksj.value.code == "hksj_requires_random"


def test_random_dichotomous_synthesis_requires_inverse_variance() -> None:
    with pytest.raises(meta_compute.MetaComputationError) as caught:
        meta_compute.compute_meta_analysis(
            {
                "data_type": "dichotomous",
                "effect_measure": "RR",
                "statistical_method": "MH",
                "analysis_model": "random",
                "studies": [
                    _dich("a", 10, 100, 20, 100),
                    _dich("b", 5, 50, 10, 50),
                ],
            }
        )

    assert caught.value.code == "unsupported_mh_random"


def test_hksj_prediction_q_profile_and_subgroups() -> None:
    result = meta_compute.compute_meta_analysis(
        {
            "data_type": "giv",
            "effect_measure": "DIFFERENCE",
            "statistical_method": "IV",
            "analysis_model": "random",
            "heterogeneity_estimator": "DL",
            "ci_method": "HKSJ",
            "prediction_interval": True,
            "tau2_ci": True,
            "studies": [
                {"study_id": "a", "effect": 0.2, "se": 0.1, "subgroup": "low"},
                {"study_id": "b", "effect": 0.8, "se": 0.12, "subgroup": "low"},
                {"study_id": "c", "effect": 1.1, "se": 0.15, "subgroup": "high"},
                {"study_id": "d", "effect": 1.5, "se": 0.2, "subgroup": "high"},
            ],
        }
    )

    assert result["overall"]["effect_statistic_name"] == "T"
    assert result["overall"]["prediction_interval"] is not None
    assert result["overall"]["tau2_ci"]["start"] >= 0
    assert result["overall"]["tau2_ci"]["end"] >= (
        result["overall"]["tau2_ci"]["start"]
    )
    assert {row["subgroup"] for row in result["subgroups"]} == {"low", "high"}
    assert result["subgroup_difference"]["df"] == 1


def test_random_analysis_allows_single_study_subgroup_without_estimating_tau() -> None:
    result = meta_compute.compute_meta_analysis(
        {
            "data_type": "giv",
            "effect_measure": "DIFFERENCE",
            "statistical_method": "IV",
            "analysis_model": "random",
            "heterogeneity_estimator": "DL",
            "ci_method": "HKSJ",
            "studies": [
                {"study_id": "a", "effect": 0.2, "se": 0.1, "subgroup": "one"},
                {"study_id": "b", "effect": 0.8, "se": 0.12, "subgroup": "two"},
                {"study_id": "c", "effect": 1.1, "se": 0.15, "subgroup": "two"},
            ],
        }
    )

    single = next(
        row for row in result["subgroups"] if row["subgroup"] == "one"
    )
    assert single["study_count"] == 1
    assert single["tau2"] == 0
    assert single["effect_statistic_name"] == "Z"
    assert "Single-Study subgroup" in single["inference_note"]
    assert result["overall"]["effect_statistic_name"] == "T"


def test_invalid_counts_and_unsupported_design_fail_without_coercion() -> None:
    with pytest.raises(meta_compute.MetaComputationError) as counts:
        meta_compute.compute_meta_analysis(
            {
                "data_type": "dichotomous",
                "effect_measure": "RR",
                "statistical_method": "IV",
                "analysis_model": "fixed",
                "studies": [_dich("bad", 11, 10, 1, 10)],
            }
        )
    assert counts.value.code == "invalid_event_count"

    with pytest.raises(meta_compute.MetaComputationError) as unsupported:
        meta_compute.compute_meta_analysis(
            {
                "data_type": "cluster_raw",
                "effect_measure": "RR",
                "studies": [{"study_id": "bad"}],
            }
        )
    assert unsupported.value.code == "unsupported_data_type"


def test_reml_nonconvergence_is_typed(monkeypatch) -> None:
    def fail_root(*args, **kwargs):
        raise ValueError("forced")

    monkeypatch.setattr(meta_compute, "brentq", fail_root)
    with pytest.raises(meta_compute.MetaComputationError) as caught:
        meta_compute.compute_meta_analysis(
            {
                "data_type": "giv",
                "effect_measure": "DIFFERENCE",
                "statistical_method": "IV",
                "analysis_model": "random",
                "heterogeneity_estimator": "REML",
                "studies": [
                    {"study_id": "a", "effect": 0.0, "se": 0.05},
                    {"study_id": "b", "effect": 2.0, "se": 0.05},
                    {"study_id": "c", "effect": 4.0, "se": 0.05},
                ],
            }
        )
    assert caught.value.code == "reml_nonconvergence"
