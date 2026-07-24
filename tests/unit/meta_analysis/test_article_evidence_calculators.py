from __future__ import annotations

import math

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent.calculators import (
    solve_arm,
)


def _material(
    kind: str,
    *,
    value: float | None = None,
    material_id: str | None = None,
    **fields: object,
) -> dict[str, object]:
    return {
        "material_id": material_id or kind,
        "kind": kind,
        "value": value,
        "lower": None,
        "upper": None,
        "confidence_level": None,
        "decimal_places": None,
        "statistical_scope": "arm",
        "applies_to": "mean",
        **fields,
    }


def test_dichotomous_solver_derives_unique_event_count_from_percentage_and_n() -> None:
    result = solve_arm(
        data_type="Dichotomous",
        materials=[
            _material("analyzed_total", value=30),
            _material("percentage", value=16.7, decimal_places=1),
        ],
    )

    assert result.values == {"total": 30, "events": 5}
    assert result.field_traces["events"]["method"] == "calculated"
    assert set(result.field_traces["events"]["input_material_ids"]) == {
        "analyzed_total",
        "percentage",
    }


def test_dichotomous_solver_rejects_percentage_that_does_not_identify_one_count() -> None:
    result = solve_arm(
        data_type="Dichotomous",
        materials=[
            _material("analyzed_total", value=1000),
            _material("percentage", value=10, decimal_places=0),
        ],
    )

    assert result.values == {"total": 1000}
    assert "reported_percentage_does_not_identify_one_event_count" in result.warnings


def test_continuous_solver_derives_sd_from_arm_mean_se_and_n() -> None:
    result = solve_arm(
        data_type="Continuous",
        materials=[
            _material("analyzed_total", value=25),
            _material("mean", value=12.0),
            _material(
                "standard_error",
                value=0.8,
                statistical_scope="arm",
                applies_to="mean",
            ),
        ],
    )

    assert result.values["total"] == 25
    assert result.values["mean"] == 12.0
    assert result.values["sd"] == 4.0
    assert result.field_traces["sd"]["method"] == "calculated"


def test_continuous_solver_uses_t_distribution_for_arm_mean_ci() -> None:
    result = solve_arm(
        data_type="Continuous",
        materials=[
            _material("analyzed_total", value=16),
            _material("mean", value=10.0),
            _material(
                "confidence_interval",
                lower=8.9342,
                upper=11.0658,
                confidence_level=0.95,
                statistical_scope="arm",
                applies_to="mean",
            ),
        ],
    )

    assert math.isclose(float(result.values["sd"]), 2.0, rel_tol=0.001)
    assert "t_quantile" in str(result.field_traces["sd"]["formula"])


def test_continuous_solver_does_not_treat_between_group_se_as_arm_sd() -> None:
    result = solve_arm(
        data_type="Continuous",
        materials=[
            _material("analyzed_total", value=25),
            _material("mean", value=12.0),
            _material(
                "standard_error",
                value=0.8,
                statistical_scope="between_group",
                applies_to="mean_difference",
            ),
        ],
    )

    assert result.values == {"total": 25, "mean": 12.0}


def test_continuous_solver_derives_sd_from_reported_arm_variance() -> None:
    result = solve_arm(
        data_type="Continuous",
        materials=[
            _material("analyzed_total", value=20),
            _material("mean", value=4.0),
            _material("variance", value=2.25),
        ],
    )

    assert result.values["sd"] == 1.5
    assert result.field_traces["sd"]["formula"] == "sd = sqrt(arm_variance)"


def test_dichotomous_solver_rejects_conflicting_reported_count_and_percentage() -> None:
    result = solve_arm(
        data_type="Dichotomous",
        materials=[
            _material("analyzed_total", value=30),
            _material("event_count", value=5),
            _material("percentage", value=50.0, decimal_places=1),
        ],
    )

    assert result.values == {"total": 30}
    assert "event_count_conflicts_with_reported_percentage" in result.warnings


def test_solver_does_not_consume_material_with_unresolved_uncertainty() -> None:
    result = solve_arm(
        data_type="Dichotomous",
        materials=[
            _material("analyzed_total", value=30),
            _material(
                "event_count",
                value=5,
                uncertainties=["arm binding is unclear"],
            ),
        ],
    )

    assert result.values == {"total": 30}
    assert "uncertain_materials:event_count" in result.warnings
