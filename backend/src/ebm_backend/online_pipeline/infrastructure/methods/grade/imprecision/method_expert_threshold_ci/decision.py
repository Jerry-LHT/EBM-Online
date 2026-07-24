"""Deterministic threshold-crossing decision for GRADE imprecision."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.ois import (
    assess_ois,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.threshold import (
    ThresholdProfile,
)


DOMAIN = "imprecision"


def unclear_judgement(
    reason: str,
    *,
    numeric_profile: dict[str, Any] | None = None,
    threshold: ThresholdProfile | None = None,
    ois: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "domain": DOMAIN,
        "assessment_status": "insufficient_evidence",
        "downgraded": "unclear",
        "severity": "unclear",
        "levels": "unclear",
        "level_evaluable": False,
        "rationale": _unclear_rationale(reason, threshold=threshold),
        "source_spans": [],
        "debug": {
            "decision_reason": reason,
            "numeric_profile": numeric_profile or {},
            "threshold": asdict(threshold) if threshold is not None else None,
            "ois": ois,
        },
    }


def decide_imprecision(
    *,
    numeric_profile: dict[str, Any],
    threshold: ThresholdProfile,
) -> dict[str, Any]:
    lower = float(numeric_profile["decision_ci_lower"])
    upper = float(numeric_profile["decision_ci_upper"])
    benefit = float(threshold.important_benefit)
    harm = float(threshold.important_harm)
    crosses_benefit = lower <= benefit <= upper
    crosses_harm = lower <= harm <= upper
    ois = assess_ois(numeric_profile=numeric_profile, threshold=threshold)
    debug = {
        "decision_reason": "",
        "crosses_important_benefit_threshold": crosses_benefit,
        "crosses_important_harm_threshold": crosses_harm,
        "numeric_profile": numeric_profile,
        "threshold": asdict(threshold),
        "ois": ois,
    }

    if crosses_benefit and crosses_harm:
        debug["decision_reason"] = "ci_crosses_benefit_and_harm_thresholds"
        return _judgement(
            severity="very_serious",
            levels=2,
            rationale=_crossing_rationale(
                numeric_profile=numeric_profile,
                threshold=threshold,
                crossed="benefit and harm",
            ),
            debug=debug,
        )
    if crosses_benefit or crosses_harm:
        crossed = "benefit" if crosses_benefit else "harm"
        debug["decision_reason"] = f"ci_crosses_{crossed}_threshold"
        return _judgement(
            severity="serious",
            levels=1,
            rationale=_crossing_rationale(
                numeric_profile=numeric_profile,
                threshold=threshold,
                crossed=crossed,
            ),
            debug=debug,
        )
    if not ois.get("evaluated"):
        debug["decision_reason"] = "ois_unavailable"
        return unclear_judgement(
            "ois_unavailable",
            numeric_profile=numeric_profile,
            threshold=threshold,
            ois=ois,
        )
    if ois.get("concern"):
        debug["decision_reason"] = "ois_not_met"
        return _judgement(
            severity="serious",
            levels=1,
            rationale=_ois_rationale(
                numeric_profile=numeric_profile,
                threshold=threshold,
                ois=ois,
                met=False,
            ),
            debug=debug,
        )
    debug["decision_reason"] = "ci_does_not_cross_clinical_thresholds"
    return _judgement(
        severity="not_serious",
        levels=0,
        rationale=_ois_rationale(
            numeric_profile=numeric_profile,
            threshold=threshold,
            ois=ois,
            met=True,
        ),
        debug=debug,
    )


def _judgement(
    *,
    severity: str,
    levels: int,
    rationale: str,
    debug: dict[str, Any],
) -> dict[str, Any]:
    return {
        "domain": DOMAIN,
        "assessment_status": "assessed",
        "downgraded": "yes" if levels else "no",
        "severity": severity,
        "levels": levels,
        "level_evaluable": True,
        "rationale": rationale,
        "source_spans": [],
        "debug": debug,
    }


def _unclear_rationale(
    reason: str,
    *,
    threshold: ThresholdProfile | None,
) -> str:
    if reason == "threshold_unavailable" and threshold is not None:
        return (
            "A defensible clinical importance threshold could not be established: "
            f"{threshold.rationale}"
        )
    if reason == "threshold_low_confidence" and threshold is not None:
        return (
            "The automatically generated clinical threshold was too uncertain "
            f"for a definitive GRADE judgement: {threshold.rationale}"
        )
    messages = {
        "effect_estimate_not_computed": "The matched effect estimate is not computed.",
        "unsupported_ci_level": "A valid 95% confidence interval is unavailable.",
        "effect_or_ci_unavailable": "The pooled effect or confidence interval is unavailable.",
        "invalid_ci_order": "The confidence interval bounds are invalid.",
        "effect_outside_confidence_interval": (
            "The pooled effect is inconsistent with its confidence interval."
        ),
        "effect_direction_convention_unavailable": (
            "The meta-analysis effect direction is unavailable or incompatible."
        ),
        "contributing_data_rows_incomplete": (
            "The matched estimate does not have complete contributing DataRow coverage."
        ),
        "contributing_data_rows_unavailable": (
            "The matched estimate has no contributing DataRows."
        ),
        "contributing_data_rows_invalid": (
            "The contributing DataRows contain invalid result data."
        ),
        "participant_count_mismatch": (
            "The estimate participant count does not match its contributing DataRows."
        ),
        "invalid_ratio_estimate": "The ratio estimate or confidence interval is invalid.",
        "control_baseline_risk_unavailable": (
            "The exact contributing rows do not provide a usable comparator baseline risk."
        ),
        "absolute_effect_conversion_invalid": (
            "The relative effect cannot be converted to a valid absolute effect."
        ),
        "unsupported_effect_measure": "The effect measure is unsupported for this method.",
        "ois_unavailable": (
            "The confidence interval does not cross a clinical threshold, but the "
            "optimal information size cannot be evaluated from the available data."
        ),
    }
    return messages.get(reason, "The available evidence is insufficient to assess imprecision.")


def _crossing_rationale(
    *,
    numeric_profile: dict[str, Any],
    threshold: ThresholdProfile,
    crossed: str,
) -> str:
    return (
        f"The 95% CI {_ci_text(numeric_profile)} crosses the clinically important "
        f"{crossed} threshold(s): benefit {_number(threshold.important_benefit)} "
        f"and harm {_number(threshold.important_harm)} {threshold.unit}. "
        f"Threshold basis: {threshold.basis}, confidence {threshold.confidence}."
    )


def _ois_rationale(
    *,
    numeric_profile: dict[str, Any],
    threshold: ThresholdProfile,
    ois: dict[str, Any],
    met: bool,
) -> str:
    status = "is met" if met else "is not met"
    return (
        f"The 95% CI {_ci_text(numeric_profile)} does not cross the important "
        f"benefit/harm thresholds {_number(threshold.important_benefit)} and "
        f"{_number(threshold.important_harm)} {threshold.unit}. The optimal "
        f"information size {status}: actual {ois['actual_information_size']}, "
        f"required {ois['required_information_size']}. Threshold basis: "
        f"{threshold.basis}, confidence {threshold.confidence}."
    )


def _ci_text(numeric_profile: dict[str, Any]) -> str:
    return (
        f"[{_number(numeric_profile['decision_ci_lower'])}, "
        f"{_number(numeric_profile['decision_ci_upper'])}] on the "
        f"{numeric_profile['decision_scale']} scale"
    )


def _number(value: Any) -> str:
    return f"{float(value):.6g}"
