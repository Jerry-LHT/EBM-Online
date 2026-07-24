"""Shared deterministic statistical engine for subgroup and overall estimates."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


STATISTICAL_POLICY_ID = "cochrane_revman_v1"
STATISTICAL_POLICY_REFERENCE_DATE = "2026-07-16"


def effect_direction_convention(*, data_type: str, effect_measure: str) -> str | None:
    """Return the stable interpretation convention for a reported effect."""

    if data_type == "Dichotomous":
        return "experimental_relative_to_control"
    if data_type == "Continuous" and effect_measure == "Std. Mean Difference":
        return "positive_favors_experimental"
    if data_type == "Continuous":
        return "original_measure_direction"
    return None


@dataclass(frozen=True)
class StudyEffect:
    row_id: str
    study_id: str
    effect: float
    variance: float
    participants: int


def pool_effect_estimates(
    *,
    effects: list[float],
    variances: list[float],
    analysis_model: str,
    interval_method: str = "Wald",
) -> dict[str, Any] | None:
    """Pool already-calculated independent effects on their analysis scale."""

    if (
        not effects
        or len(effects) != len(variances)
        or any(not math.isfinite(value) for value in effects)
        or any(not math.isfinite(value) or value <= 0 for value in variances)
    ):
        return None
    random = _is_random(analysis_model)
    fixed_weights = [1 / value for value in variances]
    fixed_centre = _weighted_mean(effects, fixed_weights)
    q = sum(
        weight * (effect - fixed_centre) ** 2
        for effect, weight in zip(effects, fixed_weights)
    )
    df = len(effects) - 1
    tau2 = _reml_tau2(effects, variances) if random and len(effects) > 1 else 0.0
    weights = [
        1 / (variance + tau2) if variance + tau2 > 0 else 0.0
        for variance in variances
    ]
    pooled = _weighted_mean(effects, weights)
    conventional_variance = 1 / sum(weights)
    requested_interval = _normalized_interval_method(interval_method)
    applied_interval = "Wald"
    variance = conventional_variance
    critical = 1.959963984540054
    if random and requested_interval == "HKSJ" and len(effects) > 2 and tau2 > 0:
        q_random = sum(
            weight * (effect - pooled) ** 2
            for effect, weight in zip(effects, weights)
        )
        variance = (q_random / df) / sum(weights)
        critical = _student_t_ppf(0.975, df)
        applied_interval = "HKSJ"
    lower = pooled - critical * math.sqrt(variance)
    upper = pooled + critical * math.sqrt(variance)
    statistic = pooled / math.sqrt(variance)
    p_value = (
        _student_t_two_sided_p(statistic, df)
        if applied_interval == "HKSJ"
        else math.erfc(abs(statistic) / math.sqrt(2))
    )
    i2, i2_method = _i2(
        q=q,
        df=df,
        tau2=tau2,
        fixed_weights=fixed_weights,
        random=random,
    )
    return {
        "analysis_effect": pooled,
        "ci_lower": lower,
        "ci_upper": upper,
        "summary_variance": variance,
        "conventional_summary_variance": conventional_variance,
        "tau2": tau2,
        "chi2": q,
        "df": df,
        "p_value": _chi_square_sf(q, df) if df > 0 else 1.0,
        "i2": i2,
        "i2_method": i2_method,
        "interval_method": applied_interval,
        "effect_test": {
            "statistic_name": "t" if applied_interval == "HKSJ" else "z",
            "statistic_value": statistic,
            "p_value": p_value,
            "df": df if applied_interval == "HKSJ" else None,
        },
        "statistical_policy_id": STATISTICAL_POLICY_ID,
    }


def pool_rows(
    *,
    rows: list[dict[str, Any]],
    data_type: str,
    effect_measure: str,
    analysis_model: str,
    statistical_method: str | None = None,
    zero_cell_handling: dict[str, Any] | None = None,
    smd_method: str | None = None,
    interval_method: str = "Wald",
    prediction_interval_enabled: bool = False,
    estimate_id: str | None = None,
    estimate_scope: str | None = None,
    method_id: str | None = None,
) -> dict[str, Any] | None:
    random = _is_random(analysis_model)
    requested_method = _normalized_statistical_method(statistical_method)
    applied_method = (
        "Mantel-Haenszel"
        if not random and data_type == "Dichotomous" and requested_method == "Mantel-Haenszel"
        else "Inverse Variance"
    )
    effects = _study_effects(
        rows,
        data_type=data_type,
        effect_measure=effect_measure,
        zero_cell_handling=zero_cell_handling,
        smd_method=smd_method,
    )
    # A zero-variance risk-difference row remains informative to a fixed
    # Mantel-Haenszel analysis because its MH weight is based on arm sizes.
    # Inverse-variance synthesis cannot use a zero variance without assigning
    # infinite weight, so those rows remain non-estimable for IV methods.
    if applied_method == "Inverse Variance":
        effects = [item for item in effects if item.variance > 0]
    if not effects:
        return None
    values = [item.effect for item in effects]
    variances = [item.variance for item in effects]
    fixed_weights = [1 / value if value > 0 else 0.0 for value in variances]
    df = len(values) - 1
    method_notes: list[str] = []
    if requested_method == "Mantel-Haenszel" and applied_method != requested_method:
        method_notes.append(
            "Random-effects synthesis uses inverse-variance weights; "
            "Mantel-Haenszel is a common-effect method."
        )

    tau2 = _reml_tau2(values, variances) if random and len(values) > 1 else 0.0
    weights = [
        1 / (variance + tau2) if variance + tau2 > 0 else 0.0
        for variance in variances
    ]
    if applied_method == "Mantel-Haenszel":
        summary = _fixed_mantel_haenszel(
            rows=rows,
            effect_measure=effect_measure,
            zero_cell_handling=zero_cell_handling,
        )
        if summary is None:
            return None
        pooled, conventional_variance = summary
    else:
        pooled = _weighted_mean(values, weights)
        conventional_variance = 1 / sum(weights)
    if applied_method == "Mantel-Haenszel":
        raw_weight_by_row = _mantel_haenszel_weights(
            rows=rows,
            effect_measure=effect_measure,
            zero_cell_handling=zero_cell_handling,
        )
        raw_weights = [raw_weight_by_row.get(item.row_id, 0.0) for item in effects]
    else:
        raw_weights = list(weights)
    weight_sum = sum(raw_weights)
    if weight_sum <= 0:
        return None
    # Cochran's Q is a fixed-effect heterogeneity statistic.  For an
    # inverse-variance analysis its centre is the fixed inverse-variance
    # summary, not the random-effects summary used for the pooled effect.
    heterogeneity_centre = (
        pooled
        if applied_method == "Mantel-Haenszel"
        else _weighted_mean(values, fixed_weights)
    )
    q = sum(
        weight * (value - heterogeneity_centre) ** 2
        for value, weight in zip(values, fixed_weights)
    )
    i2, i2_method = _i2(
        q=q,
        df=df,
        tau2=tau2,
        fixed_weights=fixed_weights,
        random=random,
    )
    requested_interval = _normalized_interval_method(interval_method)
    applied_interval = "Wald"
    if (
        random
        and requested_interval == "HKSJ"
        and len(values) > 2
        and tau2 > 0
    ):
        q_random = sum(weight * (value - pooled) ** 2 for value, weight in zip(values, weights))
        scale = q_random / (len(values) - 1)
        variance = scale / sum(weights)
        critical = _student_t_ppf(0.975, len(values) - 1)
        statistic_name = "t"
        statistic = pooled / math.sqrt(variance)
        p_value = _student_t_two_sided_p(statistic, len(values) - 1)
        test_df = len(values) - 1
        applied_interval = "HKSJ"
    else:
        variance = conventional_variance
        critical = 1.959963984540054
        statistic_name = "z"
        statistic = pooled / math.sqrt(variance)
        p_value = math.erfc(abs(statistic) / math.sqrt(2))
        test_df = None
        if random and requested_interval == "HKSJ":
            method_notes.append(
                "HKSJ requires more than two studies and positive REML tau-squared; "
                "Wald confidence intervals were used."
            )
    lower = pooled - critical * math.sqrt(variance)
    upper = pooled + critical * math.sqrt(variance)
    ratio = effect_measure in {"Risk Ratio", "Odds Ratio"}
    return {
        "effect_value": math.exp(pooled) if ratio else pooled,
        "ci_lower": math.exp(lower) if ratio else lower,
        "ci_upper": math.exp(upper) if ratio else upper,
        "analysis_effect": pooled,
        "summary_variance": variance,
        "conventional_summary_variance": conventional_variance,
        "tau2": tau2,
        "chi2": q,
        "df": df,
        "p_value": _chi_square_sf(q, df) if df > 0 else 1.0,
        "i2": i2,
        "i2_method": i2_method,
        "statistical_policy_id": STATISTICAL_POLICY_ID,
        "effect_test": {
            "statistic_name": statistic_name,
            "statistic_value": statistic,
            "p_value": p_value,
            "df": test_df,
        },
        "prediction_interval": _prediction_interval(
            pooled=pooled,
            summary_variance=variance,
            tau2=tau2,
            study_count=len(values),
            ratio=ratio,
            random=random,
            enabled=prediction_interval_enabled,
            interval_method=applied_interval,
        ),
        "statistical_method": applied_method,
        "interval_method": applied_interval,
        "method_note": " ".join(method_notes) or None,
        "included_study_ids": list(dict.fromkeys(item.study_id for item in effects)),
        "participant_count": sum(item.participants for item in effects),
        "included_data_row_ids": [item.row_id for item in effects],
        "meta_analysis_data_rows": _enriched_data_rows(
            rows=rows,
            effects=effects,
            raw_weights=raw_weights,
            weight_sum=weight_sum,
            effect_measure=effect_measure,
            estimate_id=estimate_id,
            estimate_scope=estimate_scope,
            method_id=method_id,
            statistical_method=applied_method,
            analysis_model=analysis_model,
            zero_cell_handling=zero_cell_handling,
        ),
    }


def _enriched_data_rows(
    *,
    rows: list[dict[str, Any]],
    effects: list[StudyEffect],
    raw_weights: list[float],
    weight_sum: float,
    effect_measure: str,
    estimate_id: str | None,
    estimate_scope: str | None,
    method_id: str | None,
    statistical_method: str,
    analysis_model: str,
    zero_cell_handling: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    by_row_id = {str(row.get("data_row_id") or row.get("row_id") or ""): row for row in rows}
    enriched: list[dict[str, Any]] = []
    critical = 1.959963984540054
    effect_by_row = {item.row_id: item for item in effects}
    weight_by_row = {
        item.row_id: weight
        for item, weight in zip(effects, raw_weights)
    }
    for row_id, item in effect_by_row.items():
        row = dict(by_row_id.get(row_id) or {})
        variance = item.variance
        standard_error = math.sqrt(variance)
        lower = item.effect - critical * standard_error
        upper = item.effect + critical * standard_error
        ratio = effect_measure in {"Risk Ratio", "Odds Ratio"}
        enriched.append(
            {
                **row,
                "data_row_id": row_id,
                "method_id": method_id,
                "estimate_id": estimate_id,
                "estimate_scope": estimate_scope,
                "analysis_status": "included",
                "analysis_exclusion_reason": None,
                "participant_count": item.participants,
                "effect_measure": effect_measure,
                "analysis_model": analysis_model,
                "statistical_method": statistical_method,
                "analysis_effect": item.effect,
                "analysis_scale": "log" if ratio else "natural",
                "effect_value": math.exp(item.effect) if ratio else item.effect,
                "ci_lower": math.exp(lower) if ratio else lower,
                "ci_upper": math.exp(upper) if ratio else upper,
                "variance": variance,
                "standard_error": standard_error,
                "weight": weight_by_row[row_id],
                "weight_fraction": weight_by_row[row_id] / weight_sum,
                "analysis_notes": _study_analysis_notes(
                    row=row,
                    effect_measure=effect_measure,
                    analysis_model=analysis_model,
                    zero_cell_handling=zero_cell_handling,
                ),
            }
        )
    included_ids = set(effect_by_row)
    for row in rows:
        row_id = str(row.get("data_row_id") or row.get("row_id") or "")
        if row_id in included_ids:
            continue
        enriched.append(
            {
                **row,
                "data_row_id": row_id,
                "method_id": method_id,
                "estimate_id": estimate_id,
                "estimate_scope": estimate_scope,
                "analysis_status": "excluded",
                "analysis_exclusion_reason": "study_result_not_estimable",
                "effect_measure": effect_measure,
                "analysis_model": analysis_model,
                "statistical_method": statistical_method,
            }
        )
    return sorted(enriched, key=lambda row: str(row.get("data_row_id") or ""))


def _study_analysis_notes(
    *,
    row: dict[str, Any],
    effect_measure: str,
    analysis_model: str,
    zero_cell_handling: dict[str, Any] | None,
) -> str:
    notes = [
        "Study weight uses inverse variance with REML tau-squared."
        if analysis_model in {"random_effects", "random_effect"}
        else "Study weight uses the applied statistical method."
    ]
    if effect_measure in {"Risk Ratio", "Odds Ratio"} and zero_cell_handling:
        data = result_data(row)
        a, n1, c, n0 = (
            _integer_number(data.get(name))
            for name in (
                "experimental_events",
                "experimental_total",
                "control_events",
                "control_total",
            )
        )
        if all(math.isfinite(value) for value in (a, n1, c, n0)):
            b, d = n1 - a, n0 - c
            if min(a, b, c, d) == 0:
                notes.append(
                    "A per-study continuity correction was applied to the individual-study effect and variance. "
                    "Fixed Mantel-Haenszel pooling continued to use the observed table counts."
                )
    return " ".join(notes)


def _mantel_haenszel_weights(
    *,
    rows: list[dict[str, Any]],
    effect_measure: str,
    zero_cell_handling: dict[str, Any] | None,
) -> dict[str, float]:
    weights: dict[str, float] = {}
    for row in rows:
        data = result_data(row)
        a, n1, c, n0 = (
            _integer_number(data.get(name))
            for name in ("experimental_events", "experimental_total", "control_events", "control_total")
        )
        if not all(math.isfinite(value) for value in (a, n1, c, n0)) or min(n1, n0) <= 0 or min(a, c) < 0 or a > n1 or c > n0:
            continue
        b, d = n1 - a, n0 - c
        if (a == 0 and c == 0) or (b == 0 and d == 0):
            continue
        total = a + b + c + d
        if effect_measure == "Risk Ratio":
            value = c * n1 / total
        elif effect_measure == "Odds Ratio":
            value = b * c / total
        elif effect_measure == "Risk Difference":
            value = n1 * n0 / total
        else:
            value = 0.0
        if value > 0:
            weights[str(row.get("data_row_id") or row.get("row_id") or "")] = value
    return weights


def _fixed_mantel_haenszel(
    *,
    rows: list[dict[str, Any]],
    effect_measure: str,
    zero_cell_handling: dict[str, Any] | None,
) -> tuple[float, float] | None:
    tables = []
    for row in rows:
        data = result_data(row)
        a, n1, c, n0 = (
            _integer_number(data.get(name))
            for name in (
                "experimental_events",
                "experimental_total",
                "control_events",
                "control_total",
            )
        )
        if (
            not all(math.isfinite(value) for value in (a, n1, c, n0))
            or min(n1, n0) <= 0
            or min(a, c) < 0
            or a > n1
            or c > n0
        ):
            continue
        b, d = n1 - a, n0 - c
        if effect_measure in {"Risk Ratio", "Odds Ratio"}:
            if (a == 0 and c == 0) or (b == 0 and d == 0):
                continue
        tables.append([a, b, c, d])
    if not tables:
        return None

    if effect_measure == "Risk Ratio":
        r_value = sum(a * (c + d) / (a + b + c + d) for a, b, c, d in tables)
        s_value = sum(c * (a + b) / (a + b + c + d) for a, b, c, d in tables)
        if r_value <= 0 or s_value <= 0:
            return None
        p_value = sum(
            (
                (a + b) * (c + d) * (a + c)
                - a * c * (a + b + c + d)
            )
            / ((a + b + c + d) ** 2)
            for a, b, c, d in tables
        )
        variance = p_value / (r_value * s_value)
        return (math.log(r_value / s_value), variance) if variance > 0 else None

    if effect_measure == "Odds Ratio":
        r_value = sum(a * d / (a + b + c + d) for a, b, c, d in tables)
        s_value = sum(b * c / (a + b + c + d) for a, b, c, d in tables)
        if r_value <= 0 or s_value <= 0:
            return None
        e_value = sum((a + d) * a * d / ((a + b + c + d) ** 2) for a, b, c, d in tables)
        f_value = sum((a + d) * b * c / ((a + b + c + d) ** 2) for a, b, c, d in tables)
        g_value = sum((b + c) * a * d / ((a + b + c + d) ** 2) for a, b, c, d in tables)
        h_value = sum((b + c) * b * c / ((a + b + c + d) ** 2) for a, b, c, d in tables)
        variance = 0.5 * (
            e_value / (r_value * r_value)
            + (f_value + g_value) / (r_value * s_value)
            + h_value / (s_value * s_value)
        )
        return (math.log(r_value / s_value), variance) if variance > 0 else None

    if effect_measure == "Risk Difference":
        weights = [
            (a + b) * (c + d) / (a + b + c + d)
            for a, b, c, d in tables
        ]
        weight_sum = sum(weights)
        if weight_sum <= 0:
            return None
        pooled = sum(
            weight * (a / (a + b) - c / (c + d))
            for weight, (a, b, c, d) in zip(weights, tables)
        ) / weight_sum
        j_value = sum(
            (
                a * b * ((c + d) ** 3)
                + c * d * ((a + b) ** 3)
            )
            /
            (
                (a + b)
                * (c + d)
                * ((a + b + c + d) ** 2)
            )
            for a, b, c, d in tables
        )
        variance = j_value / (weight_sum * weight_sum)
        return (pooled, variance) if variance > 0 else None
    return None


def _study_effects(
    rows: list[dict[str, Any]],
    *,
    data_type: str,
    effect_measure: str,
    zero_cell_handling: dict[str, Any] | None,
    smd_method: str | None,
) -> list[StudyEffect]:
    effects = []
    for row in rows:
        data = result_data(row)
        study_id = str(row.get("study_id") or "")
        effect = (
            _binary_effect(data, effect_measure, zero_cell_handling)
            if data_type == "Dichotomous"
            else _giv_effect(
                data,
                effect_measure,
                _effect_multiplier(row),
            )
            if _is_giv_result(data)
            else _continuous_effect(
                data,
                effect_measure,
                smd_method,
                _effect_multiplier(row),
            )
        )
        if effect is not None and study_id:
            effects.append(
                StudyEffect(
                    str(row.get("data_row_id") or row.get("row_id") or ""),
                    study_id,
                    *effect,
                )
            )
    return effects


def _is_giv_result(data: dict[str, Any]) -> bool:
    return "effect_value" in data or "standard_error" in data


def _giv_effect(
    data: dict[str, Any],
    measure: str,
    effect_multiplier: int | None,
) -> tuple[float, float, int] | None:
    effect = _number(data.get("effect_value"))
    standard_error = _number(data.get("standard_error"))
    reported_measure = str(data.get("effect_measure") or "")
    analysis_scale = str(data.get("analysis_scale") or "natural")
    participants = _integer_number(data.get("participant_count"))
    if (
        measure != "Mean Difference"
        or reported_measure != measure
        or analysis_scale != "natural"
        or effect_multiplier not in {-1, 1}
        or not math.isfinite(effect)
        or not math.isfinite(standard_error)
        or standard_error <= 0
    ):
        return None
    participant_count = (
        int(participants)
        if math.isfinite(participants) and participants > 0
        else 0
    )
    return effect * effect_multiplier, standard_error**2, participant_count


def _binary_effect(
    data: dict[str, Any],
    measure: str,
    handling: dict[str, Any] | None,
) -> tuple[float, float, int] | None:
    a, n1, c, n0 = (_integer_number(data.get(name)) for name in ("experimental_events", "experimental_total", "control_events", "control_total"))
    if not all(math.isfinite(value) for value in (a, n1, c, n0)) or min(n1, n0) <= 0 or min(a, c) < 0 or a > n1 or c > n0:
        return None
    participants = int(n1 + n0)
    if measure == "Risk Difference":
        effect = a / n1 - c / n0
        variance = (a / n1) * (1 - a / n1) / n1 + (c / n0) * (1 - c / n0) / n0
        return (effect, variance, participants) if variance >= 0 else None
    b, d = n1 - a, n0 - c
    if (a == 0 and c == 0) or (b == 0 and d == 0):
        return None
    if min(a, b, c, d) == 0:
        correction = float((handling or {}).get("correction_value") or 0.5)
        a, b, c, d = a + correction, b + correction, c + correction, d + correction
        n1, n0 = a + b, c + d
    if measure == "Risk Ratio":
        effect = math.log((a / n1) / (c / n0))
        variance = 1 / a - 1 / n1 + 1 / c - 1 / n0
    elif measure == "Odds Ratio":
        effect = math.log((a * d) / (b * c))
        variance = 1 / a + 1 / b + 1 / c + 1 / d
    else:
        return None
    return (effect, variance, participants) if variance > 0 else None


def _continuous_effect(
    data: dict[str, Any],
    measure: str,
    smd_method: str | None,
    effect_multiplier: int | None,
) -> tuple[float, float, int] | None:
    m1 = _number(data.get("experimental_mean"))
    sd1 = _number(data.get("experimental_sd"))
    n1 = _integer_number(data.get("experimental_total"))
    m0 = _number(data.get("control_mean"))
    sd0 = _number(data.get("control_sd"))
    n0 = _integer_number(data.get("control_total"))
    if effect_multiplier not in {-1, 1}:
        return None
    if not all(math.isfinite(value) for value in (m1, sd1, n1, m0, sd0, n0)) or min(n1, n0) <= 1 or min(sd1, sd0) < 0:
        return None
    participants = int(n1 + n0)
    if measure == "Mean Difference":
        variance = sd1 * sd1 / n1 + sd0 * sd0 / n0
        return (
            ((m1 - m0) * effect_multiplier, variance, participants)
            if variance > 0
            else None
        )
    if measure != "Std. Mean Difference" or smd_method not in {None, "Hedges_g"}:
        return None
    df = n1 + n0 - 2
    pooled_variance = ((n1 - 1) * sd1 * sd1 + (n0 - 1) * sd0 * sd0) / df
    if pooled_variance <= 0:
        return None
    d_value = (m1 - m0) / math.sqrt(pooled_variance)
    correction = 1 - 3 / (4 * df - 1)
    raw_g_value = correction * d_value
    total = n1 + n0
    variance = total / (n1 * n0) + raw_g_value * raw_g_value / (2 * (total - 3.94))
    return raw_g_value * effect_multiplier, variance, participants


def _i2(
    *,
    q: float,
    df: int,
    tau2: float,
    fixed_weights: list[float],
    random: bool,
) -> tuple[float, str]:
    """Return I-squared under the versioned Cochrane/RevMan policy.

    Common-effect analyses retain the conventional Q-based statistic.  For a
    random-effects analysis, current RevMan pairs the selected tau-squared
    estimator with the typical within-study variance.  This distinction is
    material for REML but collapses to the familiar Q expression for the
    DerSimonian-Laird moment estimator.
    """

    if not random:
        value = max(0.0, (q - df) / q * 100) if q > 0 and df > 0 else 0.0
        return value, "q_based"
    weight_sum = sum(fixed_weights)
    denominator = weight_sum * weight_sum - sum(weight * weight for weight in fixed_weights)
    if df <= 0 or weight_sum <= 0 or denominator <= 0:
        return 0.0, "tau2_typical_within_study_variance"
    typical_variance = df * weight_sum / denominator
    value = (
        tau2 / (tau2 + typical_variance) * 100
        if tau2 > 0 and typical_variance > 0
        else 0.0
    )
    return value, "tau2_typical_within_study_variance"


def result_data(row: dict[str, Any]) -> dict[str, Any]:
    items = row.get("result_items") if isinstance(row.get("result_items"), list) else None
    if items is None:
        items = row.get("candidate_results") if isinstance(row.get("candidate_results"), list) else []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("result_data"), dict) and (str(item.get("analysis_disposition") or "") == "ready_for_estimate" or item.get("include_in_estimate") is True):
            return item["result_data"]
    return row.get("result_data") if isinstance(row.get("result_data"), dict) else {}


def _effect_multiplier(row: dict[str, Any]) -> int | None:
    items = row.get("result_items") if isinstance(row.get("result_items"), list) else []
    alignment: dict[str, Any] = {}
    for item in items:
        if isinstance(item, dict) and isinstance(
            item.get("continuous_effect_alignment"), dict
        ):
            alignment = item["continuous_effect_alignment"]
            break
    if not alignment and isinstance(row.get("continuous_effect_alignment"), dict):
        alignment = row["continuous_effect_alignment"]
    value = alignment.get("effect_multiplier")
    return int(value) if value in {-1, 1, -1.0, 1.0} else None


def _reml_tau2(values: list[float], variances: list[float]) -> float:
    def objective(tau2: float) -> float:
        weights = [1 / (variance + tau2) for variance in variances]
        mean = _weighted_mean(values, weights)
        return 0.5 * (sum(math.log(variance + tau2) for variance in variances) + math.log(sum(weights)) + sum(weight * (value - mean) ** 2 for value, weight in zip(values, weights)))

    spread = max(values) - min(values)
    upper = max(1.0, spread * spread * 10, max(variances) * 100)
    candidate = _bounded_minimum(objective, 0.0, upper)
    return candidate if objective(candidate) < objective(0.0) else 0.0


def _prediction_interval(*, pooled: float, summary_variance: float, tau2: float, study_count: int, ratio: bool, random: bool, enabled: bool, interval_method: str) -> dict[str, float] | None:
    if not enabled or not random or study_count < 5:
        return None
    critical = (
        _student_t_ppf(0.975, study_count - 1)
        if interval_method == "HKSJ"
        else 1.959963984540054
    )
    width = critical * math.sqrt(tau2 + summary_variance)
    lower, upper = pooled - width, pooled + width
    return {"lower": math.exp(lower) if ratio else lower, "upper": math.exp(upper) if ratio else upper}


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    return sum(value * weight for value, weight in zip(values, weights)) / sum(weights)


def _is_random(value: str) -> bool:
    return value in {"random_effect", "random_effects"}


def _normalized_statistical_method(value: str | None) -> str:
    normalized = " ".join(
        str(value or "").replace("_", " ").replace("-", " ").split()
    ).casefold()
    if normalized in {"mh", "m h", "mantel haenszel"}:
        return "Mantel-Haenszel"
    return "Inverse Variance"


def _normalized_interval_method(value: str | None) -> str:
    normalized = "".join(str(value or "").casefold().split())
    return "HKSJ" if normalized in {"hksj", "hartung-knapp-sidik-jonkman"} else "Wald"


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _integer_number(value: Any) -> float:
    if isinstance(value, bool):
        return math.nan
    number = _number(value)
    return number if math.isfinite(number) and number.is_integer() else math.nan


def _bounded_minimum(function, lower: float, upper: float) -> float:
    ratio = (math.sqrt(5) - 1) / 2
    left, right = lower, upper
    x1 = right - ratio * (right - left)
    x2 = left + ratio * (right - left)
    f1, f2 = function(x1), function(x2)
    for _ in range(160):
        if abs(right - left) <= 1e-10 * (1 + abs(left) + abs(right)):
            break
        if f1 < f2:
            right, x2, f2 = x2, x1, f1
            x1 = right - ratio * (right - left)
            f1 = function(x1)
        else:
            left, x1, f1 = x1, x2, f2
            x2 = left + ratio * (right - left)
            f2 = function(x2)
    return max(0.0, (left + right) / 2)


def _chi_square_sf(value: float, df: int) -> float:
    return _regularized_gamma_q(df / 2, value / 2)


# Public alias used by subgroup interaction tests and the benchmark adapter.
chi_square_sf = _chi_square_sf


def _regularized_gamma_q(a: float, x: float) -> float:
    if x <= 0:
        return 1.0
    if x < a + 1:
        term = total = 1 / a
        ap = a
        for _ in range(200):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-14:
                break
        p = total * math.exp(-x + a * math.log(x) - math.lgamma(a))
        return max(0.0, min(1.0, 1 - p))
    b = x + 1 - a
    c = 1 / 1e-300
    d = 1 / b
    h = d
    for index in range(1, 201):
        an = -index * (index - a)
        b += 2
        value_d = an * d + b
        d = value_d if abs(value_d) > 1e-300 else 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14:
            break
    return max(0.0, min(1.0, math.exp(-x + a * math.log(x) - math.lgamma(a)) * h))


def _student_t_ppf(probability: float, df: int) -> float:
    if df <= 0:
        return math.inf
    lower, upper = 0.0, 1.0
    while _student_t_cdf(upper, df) < probability:
        upper *= 2
    for _ in range(100):
        middle = (lower + upper) / 2
        if _student_t_cdf(middle, df) < probability:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2


def _student_t_two_sided_p(value: float, df: int) -> float:
    x = df / (df + value * value)
    return max(0.0, min(1.0, _regularized_beta(x, df / 2, 0.5)))


def _student_t_cdf(value: float, df: int) -> float:
    if value == 0:
        return 0.5
    tail = 0.5 * _regularized_beta(df / (df + value * value), df / 2, 0.5)
    return 1 - tail if value > 0 else tail


def _regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return front * _beta_fraction(x, a, b) / a
    return 1 - front * _beta_fraction(1 - x, b, a) / b


def _beta_fraction(x: float, a: float, b: float) -> float:
    qab, qap, qam = a + b, a + 1, a - 1
    c = 1.0
    d = 1 - qab * x / qap
    d = 1 / (d if abs(d) > 1e-300 else 1e-300)
    result = d
    for index in range(1, 201):
        twice = 2 * index
        aa = index * (b - index) * x / ((qam + twice) * (a + twice))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + aa / c
        c = c if abs(c) > 1e-300 else 1e-300
        result *= d * c
        aa = -(a + index) * (qab + index) * x / ((a + twice) * (qap + twice))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + aa / c
        c = c if abs(c) > 1e-300 else 1e-300
        delta = d * c
        result *= delta
        if abs(delta - 1) < 3e-14:
            break
    return result
