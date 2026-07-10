"""Small deterministic pooling helpers for meta-analysis test methods."""

from __future__ import annotations

import math
from typing import Any


def pool_rows(*, rows: list[dict[str, Any]], data_type: str | None) -> dict[str, float] | None:
    if data_type == "Dichotomous":
        return _pool_dichotomous(rows)
    if data_type == "Continuous":
        return _pool_continuous(rows)
    return None


def participant_count(rows: list[dict[str, Any]]) -> int:
    total = 0
    for row in rows:
        data = _row_result_data(row)
        total += int(data.get("experimental_total") or 0)
        total += int(data.get("control_total") or 0)
    return total


def _pool_dichotomous(rows: list[dict[str, Any]]) -> dict[str, float] | None:
    effects = []
    variances = []
    for row in rows:
        data = _row_result_data(row)
        a = float(data.get("experimental_events") or 0) + 0.5
        b = float((data.get("experimental_total") or 0) - (data.get("experimental_events") or 0)) + 0.5
        c = float(data.get("control_events") or 0) + 0.5
        d = float((data.get("control_total") or 0) - (data.get("control_events") or 0)) + 0.5
        if min(a, b, c, d) <= 0:
            continue
        log_rr = math.log((a / (a + b)) / (c / (c + d)))
        var = (1 / a) - (1 / (a + b)) + (1 / c) - (1 / (c + d))
        effects.append(log_rr)
        variances.append(var)
    if not effects:
        return None
    return _fixed_effect_summary(effects, variances, exp_transform=True)


def _pool_continuous(rows: list[dict[str, Any]]) -> dict[str, float] | None:
    effects = []
    variances = []
    for row in rows:
        data = _row_result_data(row)
        n1 = float(data.get("experimental_total") or 0)
        n0 = float(data.get("control_total") or 0)
        if n1 <= 0 or n0 <= 0:
            continue
        m1 = float(data.get("experimental_mean") or 0.0)
        s1 = float(data.get("experimental_sd") or 0.0)
        m0 = float(data.get("control_mean") or 0.0)
        s0 = float(data.get("control_sd") or 0.0)
        md = m1 - m0
        var = (s1 * s1 / n1) + (s0 * s0 / n0)
        effects.append(md)
        variances.append(var)
    if not effects:
        return None
    return _fixed_effect_summary(effects, variances, exp_transform=False)


def _row_result_data(row: dict[str, Any]) -> dict[str, Any]:
    items = row.get("result_items") if isinstance(row.get("result_items"), list) else None
    if items is None:
        items = row.get("candidate_results") if isinstance(row.get("candidate_results"), list) else None
    if items:
        ready = [
            item
            for item in items
            if isinstance(item, dict)
            and str(item.get("analysis_disposition") or "").strip().lower() == "ready_for_estimate"
            and isinstance(item.get("result_data"), dict)
        ]
        source = ready[0] if ready else next((item for item in items if isinstance(item, dict)), None)
        if isinstance(source, dict) and isinstance(source.get("result_data"), dict):
            return source["result_data"]
    return row.get("result_data") if isinstance(row.get("result_data"), dict) else {}


def _fixed_effect_summary(effects: list[float], variances: list[float], *, exp_transform: bool) -> dict[str, float]:
    weights = [1.0 / max(var, 1e-9) for var in variances]
    pooled = sum(weight * effect for weight, effect in zip(weights, effects)) / sum(weights)
    se = math.sqrt(1.0 / sum(weights))
    lower = pooled - 1.96 * se
    upper = pooled + 1.96 * se
    if exp_transform:
        return {
            "effect_value": math.exp(pooled),
            "ci_lower": math.exp(lower),
            "ci_upper": math.exp(upper),
        }
    return {
        "effect_value": pooled,
        "ci_lower": lower,
        "ci_upper": upper,
    }
