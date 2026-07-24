"""Shared helpers for deterministic GRADE test methods."""

from __future__ import annotations

import math
import re
from typing import Any


def not_serious(domain: str, rationale: str) -> dict[str, Any]:
    return judgement(domain, downgraded="no", severity="none", levels=0, level_evaluable=True, rationale=rationale)


def serious(domain: str, rationale: str) -> dict[str, Any]:
    return judgement(domain, downgraded="yes", severity="serious", levels=1, level_evaluable=True, rationale=rationale)


def very_serious(domain: str, rationale: str) -> dict[str, Any]:
    return judgement(domain, downgraded="yes", severity="very_serious", levels=2, level_evaluable=True, rationale=rationale)


def unclear(domain: str, rationale: str) -> dict[str, Any]:
    return judgement(domain, downgraded="unclear", severity="unclear", levels="unclear", level_evaluable=False, rationale=rationale)


def judgement(
    domain: str,
    *,
    downgraded: str,
    severity: str,
    levels: int | str,
    level_evaluable: bool,
    rationale: str,
) -> dict[str, Any]:
    return {
        "domain": domain,
        "downgraded": downgraded,
        "severity": severity,
        "levels": levels,
        "level_evaluable": level_evaluable,
        "rationale": rationale,
        "source_spans": [],
    }


def first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace("%", ""))
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def as_int(value: Any) -> int | None:
    number = as_float(value)
    if number is None:
        return None
    return int(number)


def norm_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value if item is not None)
    return re.sub(r"\s+", " ", str(value or "").lower()).strip().replace("-", "_")


def join_text(*values: Any) -> str:
    parts = []
    for value in values:
        if isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value if item)
        elif value:
            parts.append(str(value))
    return "\n".join(parts)


def token_overlap(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9]+", left.lower()))
    right_tokens = set(re.findall(r"[a-z0-9]+", right.lower()))
    if not left_tokens or not right_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def ci_crosses_line_of_no_effect(lower: float, upper: float, effect_measure: str) -> bool:
    no_effect = 0.0
    if any(token in effect_measure.lower() for token in ("risk ratio", "odds ratio", "hazard ratio", "ratio", "rr", "or")):
        no_effect = 1.0
    return lower <= no_effect <= upper


def ci_ratio(lower: float, upper: float) -> float:
    if lower <= 0:
        return float("inf")
    return abs(upper / lower)
