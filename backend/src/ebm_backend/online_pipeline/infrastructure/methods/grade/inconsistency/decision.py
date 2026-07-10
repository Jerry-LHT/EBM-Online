"""Deterministic GRADE inconsistency decision engine."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.common import as_float, judgement


DOMAIN = "inconsistency"


def decide_inconsistency(
    *,
    features: dict[str, Any],
    clinical_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a GRADE inconsistency judgement from upstream meta-analysis evidence."""

    heterogeneity = features.get("heterogeneity") or {}
    study_summary = features.get("study_effect_summary") or {}
    subgroup_tests = [row for row in features.get("subgroup_tests") or [] if isinstance(row, dict)]
    study_count = _first_float(features.get("study_count"), study_summary.get("evaluable_study_count")) or 0
    i2 = as_float(heterogeneity.get("i2"))
    p_value = as_float(heterogeneity.get("p_value"))
    prediction_interval_crosses = bool((features.get("prediction_interval") or {}).get("crosses_no_effect"))
    important_subgroup = _important_subgroup_test(subgroup_tests)
    direction_conflict = bool(study_summary.get("opposing_direction")) and study_count >= 2
    large_spread = _large_effect_spread(features)
    clinical_support = _clinical_supports_inconsistency(clinical_profile or {})
    profile = _evidence_profile(
        i2=i2,
        p_value=p_value,
        study_count=study_count,
        direction_conflict=direction_conflict,
        large_spread=large_spread,
        important_subgroup=important_subgroup,
        prediction_interval_crosses=prediction_interval_crosses,
        clinical_support=clinical_support,
    )

    decision_features = {
        "study_count": study_count,
        "i2": i2,
        "heterogeneity_p_value": p_value,
        "important_subgroup_test": important_subgroup,
        "prediction_interval_crosses_no_effect": prediction_interval_crosses,
        "direction_conflict": direction_conflict,
        "large_effect_spread": large_spread,
        "clinical_supports_inconsistency": clinical_support,
        "study_effect_summary": study_summary,
        "evidence_profile": profile,
    }

    if study_count <= 1:
        return _with_debug(
            judgement(
                DOMAIN,
                downgraded="no",
                severity="none",
                levels=0,
                level_evaluable=True,
                rationale="A single-study evidence body does not provide study-to-study inconsistency evidence.",
            ),
            features=features,
            clinical_profile=clinical_profile,
            decision_features={**decision_features, "reason_group": "single_study_not_evaluable_for_between_study_inconsistency"},
        )

    if i2 is None and p_value is None and not direction_conflict and not important_subgroup and not prediction_interval_crosses:
        return _with_debug(
            judgement(
                DOMAIN,
                downgraded="unclear",
                severity="unclear",
                levels="unclear",
                level_evaluable=False,
                rationale="Heterogeneity statistics and study-level inconsistency signals are unavailable.",
            ),
            features=features,
            clinical_profile=clinical_profile,
            decision_features={**decision_features, "reason_group": "missing_heterogeneity_evidence"},
        )

    if profile["very_serious"]:
        return _with_debug(
            judgement(
                DOMAIN,
                downgraded="yes",
                severity="very_serious",
                levels=2,
                level_evaluable=True,
                rationale="Multiple strong inconsistency signals suggest very serious unexplained variation across studies.",
            ),
            features=features,
            clinical_profile=clinical_profile,
            decision_features={**decision_features, "reason_group": "multiple_strong_inconsistency_signals"},
        )

    if profile["downgrade"]:
        return _with_debug(
            judgement(
                DOMAIN,
                downgraded="yes",
                severity="serious",
                levels=1,
                level_evaluable=True,
                rationale="Statistical heterogeneity is supported by study-level or subgroup inconsistency signals.",
            ),
            features=features,
            clinical_profile=clinical_profile,
            decision_features={**decision_features, "reason_group": profile["reason_group"]},
        )

    return _with_debug(
        judgement(
            DOMAIN,
            downgraded="no",
            severity="none",
            levels=0,
            level_evaluable=True,
            rationale="Available heterogeneity statistics and study-level effects do not show important inconsistency.",
        ),
        features=features,
        clinical_profile=clinical_profile,
        decision_features={**decision_features, "reason_group": "no_important_inconsistency_signal"},
    )


def _evidence_profile(
    *,
    i2: float | None,
    p_value: float | None,
    study_count: float,
    direction_conflict: bool,
    large_spread: bool,
    important_subgroup: bool,
    prediction_interval_crosses: bool,
    clinical_support: bool,
) -> dict[str, Any]:
    statistical_strength, statistical_points = _statistical_signal(i2=i2, p_value=p_value)
    pattern_signals = {
        "direction_conflict": direction_conflict,
        "large_effect_spread": large_spread,
        "important_subgroup_test": important_subgroup,
        "prediction_interval_crosses_no_effect": prediction_interval_crosses,
        "clinical_heterogeneity_support": clinical_support,
    }
    pattern_count = sum(1 for value in pattern_signals.values() if value)
    pattern_points = (
        (1.0 if direction_conflict else 0.0)
        + (0.5 if large_spread else 0.0)
        + (0.5 if important_subgroup else 0.0)
        + (1.0 if prediction_interval_crosses else 0.0)
        + (0.5 if clinical_support else 0.0)
    )
    p_value_points = 0.5 if p_value is not None and p_value < 0.10 else 0.0
    score = statistical_points + p_value_points + pattern_points
    downgrade = score >= 3.0 and statistical_strength != "none"
    reason_group = "no_important_inconsistency_signal"
    if downgrade:
        if statistical_strength == "very_strong":
            reason_group = "very_strong_statistical_inconsistency_profile"
        elif statistical_strength == "strong":
            reason_group = "strong_statistical_inconsistency_profile"
        elif statistical_strength == "substantial":
            reason_group = "substantial_statistical_inconsistency_profile"
        elif pattern_count >= 2:
            reason_group = "moderate_statistical_signal_with_pattern_support"
        else:
            reason_group = "combined_inconsistency_profile_score"
    very_serious = (
        downgrade
        and statistical_strength == "very_strong"
        and pattern_count >= 2
        and (p_value is None or p_value < 0.01)
    )
    return {
        "statistical_signal": statistical_strength,
        "statistical_points": statistical_points,
        "p_value_points": p_value_points,
        "pattern_signals": pattern_signals,
        "pattern_signal_count": pattern_count,
        "pattern_points": pattern_points,
        "combined_score": round(score, 4),
        "downgrade": downgrade,
        "very_serious": very_serious,
        "reason_group": reason_group,
    }


def _statistical_signal(*, i2: float | None, p_value: float | None) -> tuple[str, float]:
    if i2 is None:
        if p_value is not None and p_value < 0.10:
            return "weak", 0.5
        return "none", 0.0
    if i2 >= 85:
        return "very_strong", 4.0
    if i2 >= 75:
        return "strong", 3.0
    if i2 >= 60:
        return "substantial", 2.0
    if i2 >= 50:
        return "moderate", 1.5
    if i2 >= 30:
        return "weak", 1.0
    if p_value is not None and p_value < 0.10:
        return "weak", 0.5
    return "none", 0.0


def _important_subgroup_test(subgroup_tests: list[dict[str, Any]]) -> bool:
    for row in subgroup_tests:
        p_value = as_float(row.get("p_value"))
        i2 = as_float(row.get("i2"))
        if p_value is not None and p_value < 0.05:
            return True
        if p_value is not None and p_value < 0.10 and i2 is not None and i2 >= 50:
            return True
    return False


def _large_effect_spread(features: dict[str, Any]) -> bool:
    summary = features.get("study_effect_summary") or {}
    spread_ratio = as_float(summary.get("effect_spread_ratio"))
    effect_range = as_float(summary.get("effect_range"))
    if spread_ratio is not None and spread_ratio >= 3.0:
        return True
    if effect_range is not None:
        overall_lower = as_float(features.get("overall_ci_lower"))
        overall_upper = as_float(features.get("overall_ci_upper"))
        if overall_lower is not None and overall_upper is not None and effect_range > abs(overall_upper - overall_lower):
            return True
    return False


def _clinical_supports_inconsistency(profile: dict[str, Any]) -> bool:
    ratings = profile.get("domain_ratings") or {}
    if isinstance(ratings, dict) and any(str(value) == "serious_concern" for value in ratings.values()):
        return True
    signals = profile.get("body_signals") or []
    return any(isinstance(signal, dict) and str(signal.get("severity")) in {"serious", "very_serious"} for signal in signals)


def _with_debug(
    result: dict[str, Any],
    *,
    features: dict[str, Any],
    decision_features: dict[str, Any],
    clinical_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result["debug"] = {
        "input_policy": "analysis_setting_and_meta_analysis_only_no_sof_context",
        "features": features,
        "decision_features": decision_features,
    }
    if clinical_profile is not None:
        result["debug"]["clinical_profile"] = clinical_profile
    return result


def _first_float(*values: Any) -> float | None:
    for value in values:
        number = as_float(value)
        if number is not None:
            return number
    return None
