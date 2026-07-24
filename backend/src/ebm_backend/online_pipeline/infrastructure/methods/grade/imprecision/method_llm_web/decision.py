"""Deterministic GRADE imprecision decision engine."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.utils import as_float, judgement, norm_text
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.evidence import is_ratio_measure
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.ois import assess_ois
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.thresholds import (
    DEFAULT_ABSOLUTE_THRESHOLD_PER_1000,
    RATIO_IMPORTANT_BENEFIT,
    RATIO_IMPORTANT_HARM,
)


DOMAIN = "imprecision"


def decide_imprecision(
    *,
    setting_context: dict[str, Any],
    numeric_features: dict[str, Any],
    threshold: dict[str, Any],
) -> dict[str, Any]:
    data_type = norm_text(numeric_features.get("data_type"))
    if "dichotomous" in data_type or "binary" in data_type:
        return _decide_dichotomous(setting_context=setting_context, numeric_features=numeric_features, threshold=threshold)
    if "continuous" in data_type:
        return _decide_continuous(setting_context=setting_context, numeric_features=numeric_features, threshold=threshold)
    return _decide_generic(setting_context=setting_context, numeric_features=numeric_features, threshold=threshold)


def _decide_generic(
    *,
    setting_context: dict[str, Any],
    numeric_features: dict[str, Any],
    threshold: dict[str, Any],
) -> dict[str, Any]:
    lower = as_float(numeric_features.get("ci_lower"))
    upper = as_float(numeric_features.get("ci_upper"))
    if lower is None or upper is None:
        return _with_debug(
            judgement(DOMAIN, downgraded="unclear", severity="unclear", levels="unclear", level_evaluable=False, rationale="Confidence interval is unavailable."),
            setting_context=setting_context,
            numeric_features=numeric_features,
            threshold=threshold,
            decision_features={"decision_engine": "generic", "decision_reason_group": "missing_ci", "reason": "missing_ci"},
        )

    no_effect = as_float(numeric_features.get("no_effect"))
    crosses_no_effect = no_effect is not None and lower <= no_effect <= upper
    threshold_assessment = _decision_threshold_assessment(numeric_features, threshold)
    ois_assessment = assess_ois(numeric_features, threshold)
    insufficient_info = bool(ois_assessment["concern"])
    large_effect = _large_effect(numeric_features, threshold_assessment)
    decision_features = {
        "decision_engine": "generic",
        "crosses_no_effect": crosses_no_effect,
        **threshold_assessment,
        "information_size_concern": insufficient_info,
        "ois_assessment": ois_assessment,
        "large_effect": large_effect,
    }

    decision_features["low_confidence_threshold"] = _low_confidence_threshold_assessment(threshold_assessment)
    if _should_downgrade_two_levels(threshold_assessment, ois_assessment, numeric_features):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="very_serious",
            levels=2,
            level_evaluable=True,
            rationale="Confidence interval includes both important benefit and important harm thresholds.",
        )
    elif threshold_assessment["crosses_both_important_benefit_and_harm"]:
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Confidence interval includes both important benefit and important harm thresholds.",
        )
    elif threshold_assessment["crosses_decision_threshold"] or crosses_no_effect:
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Confidence interval crosses no effect or a clinical decision threshold.",
        )
        if ois_assessment["severity"] == "very_serious" and _is_very_wide(numeric_features):
            result = judgement(
                DOMAIN,
                downgraded="yes",
                severity="very_serious",
                levels=2,
                level_evaluable=True,
                rationale="Confidence interval crosses an important threshold and information size is clearly insufficient.",
            )
    elif ois_assessment["severity"] in {"serious", "very_serious"} and (large_effect or _is_very_wide(numeric_features)):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Information size is clearly insufficient under GRADE OIS considerations.",
        )
    elif _should_downgrade_for_ois_only(ois_assessment, numeric_features):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Information size is insufficient under GRADE OIS considerations.",
        )
    else:
        result = judgement(
            DOMAIN,
            downgraded="no",
            severity="none",
            levels=0,
            level_evaluable=True,
            rationale="Confidence interval does not cross no effect or important decision thresholds, and information size does not trigger imprecision rules.",
        )
    return _with_debug(result, setting_context=setting_context, numeric_features=numeric_features, threshold=threshold, decision_features=decision_features)


def _decide_dichotomous(
    *,
    setting_context: dict[str, Any],
    numeric_features: dict[str, Any],
    threshold: dict[str, Any],
) -> dict[str, Any]:
    lower = as_float(numeric_features.get("ci_lower"))
    upper = as_float(numeric_features.get("ci_upper"))
    if lower is None or upper is None:
        return _with_debug(
            judgement(DOMAIN, downgraded="unclear", severity="unclear", levels="unclear", level_evaluable=False, rationale="Confidence interval is unavailable."),
            setting_context=setting_context,
            numeric_features=numeric_features,
            threshold=threshold,
            decision_features={"decision_engine": "dichotomous", "decision_reason_group": "missing_ci"},
        )
    threshold_assessment = _decision_threshold_assessment(numeric_features, threshold, allow_fallback=False)
    fallback_assessment = _decision_threshold_assessment(numeric_features, threshold, allow_fallback=True)
    if threshold_assessment["threshold_basis"] == "no_threshold":
        threshold_assessment = fallback_assessment
        threshold_assessment["threshold_basis"] = "low_confidence_" + str(threshold_assessment.get("threshold_basis") or "fallback")
    no_effect = as_float(numeric_features.get("no_effect"))
    crosses_no_effect = no_effect is not None and lower <= no_effect <= upper
    ois_assessment = assess_ois(numeric_features, threshold)
    decision_features = {
        "decision_engine": "dichotomous",
        "crosses_no_effect": crosses_no_effect,
        **threshold_assessment,
        "information_size_concern": bool(ois_assessment["concern"]),
        "ois_assessment": ois_assessment,
    }
    low_confidence_threshold = _low_confidence_threshold_assessment(threshold_assessment)
    decision_features["low_confidence_threshold"] = low_confidence_threshold

    if _should_downgrade_two_levels(threshold_assessment, ois_assessment, numeric_features):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="very_serious",
            levels=2,
            level_evaluable=True,
            rationale="Confidence interval includes both important benefit and important harm thresholds.",
        )
        decision_features["decision_reason_group"] = "ci_spans_important_benefit_and_harm"
    elif threshold_assessment["crosses_both_important_benefit_and_harm"]:
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Confidence interval includes both important benefit and important harm thresholds.",
        )
        decision_features["decision_reason_group"] = "ci_spans_important_benefit_and_harm"
    elif crosses_no_effect and _ci_includes_important_effect(threshold_assessment):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Confidence interval crosses no effect and includes a clinically important effect.",
        )
        decision_features["decision_reason_group"] = "ci_crosses_no_effect_and_important_effect"
        if ois_assessment["severity"] == "very_serious" and _is_very_wide(numeric_features):
            result = judgement(
                DOMAIN,
                downgraded="yes",
                severity="very_serious",
                levels=2,
                level_evaluable=True,
                rationale="Confidence interval crosses no effect, includes an important effect, and information size is clearly insufficient.",
            )
            decision_features["decision_reason_group"] = "ci_crosses_no_effect_important_effect_and_very_low_information"
    elif crosses_no_effect and _absolute_ci_width_may_be_decision_changing(numeric_features):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Confidence interval crosses no effect and the absolute effect interval may include clinically meaningful differences.",
        )
        decision_features["decision_reason_group"] = "ci_crosses_no_effect_with_wide_absolute_interval"
    elif crosses_no_effect and _is_very_wide(numeric_features) and ois_assessment["severity"] in {"serious", "very_serious"}:
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Confidence interval crosses no effect and is very wide with limited information size.",
        )
        decision_features["decision_reason_group"] = "ci_crosses_no_effect_very_wide_low_information"
    elif _should_downgrade_for_ois_only(ois_assessment, numeric_features):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Information size is insufficient under GRADE OIS considerations.",
        )
        decision_features["decision_reason_group"] = "ois_only_information_size_concern"
    else:
        result = judgement(
            DOMAIN,
            downgraded="no",
            severity="none",
            levels=0,
            level_evaluable=True,
            rationale="Confidence interval does not include both important benefit and harm, and imprecision does not appear decision-changing.",
        )
        decision_features["decision_reason_group"] = "ci_not_decision_changing"
    return _with_debug(result, setting_context=setting_context, numeric_features=numeric_features, threshold=threshold, decision_features=decision_features)


def _decide_continuous(
    *,
    setting_context: dict[str, Any],
    numeric_features: dict[str, Any],
    threshold: dict[str, Any],
) -> dict[str, Any]:
    lower = as_float(numeric_features.get("ci_lower"))
    upper = as_float(numeric_features.get("ci_upper"))
    if lower is None or upper is None:
        return _with_debug(
            judgement(DOMAIN, downgraded="unclear", severity="unclear", levels="unclear", level_evaluable=False, rationale="Confidence interval is unavailable."),
            setting_context=setting_context,
            numeric_features=numeric_features,
            threshold=threshold,
            decision_features={"decision_engine": "continuous", "decision_reason_group": "missing_ci"},
        )
    threshold_assessment = _decision_threshold_assessment(numeric_features, threshold, allow_fallback=False)
    no_effect = as_float(numeric_features.get("no_effect"))
    crosses_no_effect = no_effect is not None and lower <= no_effect <= upper
    ois_assessment = assess_ois(numeric_features, threshold)
    decision_features = {
        "decision_engine": "continuous",
        "crosses_no_effect": crosses_no_effect,
        **threshold_assessment,
        "information_size_concern": bool(ois_assessment["concern"]),
        "ois_assessment": ois_assessment,
        "threshold_unavailable": threshold_assessment["threshold_basis"] == "no_threshold",
    }
    if _should_downgrade_two_levels(threshold_assessment, ois_assessment, numeric_features):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="very_serious",
            levels=2,
            level_evaluable=True,
            rationale="Confidence interval includes both important benefit and important harm thresholds.",
        )
        decision_features["decision_reason_group"] = "ci_spans_important_benefit_and_harm"
    elif threshold_assessment["crosses_both_important_benefit_and_harm"]:
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Confidence interval includes both important benefit and important harm thresholds.",
        )
        decision_features["decision_reason_group"] = "ci_spans_important_benefit_and_harm"
    elif crosses_no_effect and _ci_includes_important_effect(threshold_assessment):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Confidence interval crosses no effect and includes the minimal important difference.",
        )
        decision_features["decision_reason_group"] = "ci_crosses_no_effect_and_mid"
    elif threshold_assessment["threshold_basis"] == "no_threshold":
        result = judgement(
            DOMAIN,
            downgraded="unclear",
            severity="unclear",
            levels="unclear",
            level_evaluable=False,
            rationale="Continuous outcome MID or scale-specific threshold is unavailable.",
        )
        decision_features["decision_reason_group"] = "continuous_mid_unavailable"
    elif crosses_no_effect and ois_assessment["severity"] in {"serious", "very_serious"} and _is_very_wide(numeric_features):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Confidence interval crosses no effect and is very wide with limited information size.",
        )
        decision_features["decision_reason_group"] = "ci_crosses_no_effect_very_wide_low_information"
    elif _should_downgrade_for_ois_only(ois_assessment, numeric_features):
        result = judgement(
            DOMAIN,
            downgraded="yes",
            severity="serious",
            levels=1,
            level_evaluable=True,
            rationale="Information size is insufficient under GRADE OIS considerations.",
        )
        decision_features["decision_reason_group"] = "ois_only_information_size_concern"
    else:
        result = judgement(
            DOMAIN,
            downgraded="no",
            severity="none",
            levels=0,
            level_evaluable=True,
            rationale="Confidence interval does not cross clinically important thresholds for the continuous outcome.",
        )
        decision_features["decision_reason_group"] = "ci_not_decision_changing"
    return _with_debug(result, setting_context=setting_context, numeric_features=numeric_features, threshold=threshold, decision_features=decision_features)


def _decision_threshold_assessment(numeric_features: dict[str, Any], threshold: dict[str, Any], *, allow_fallback: bool = True) -> dict[str, Any]:
    lower, upper, benefit, harm, basis = _validated_threshold_interval(numeric_features, threshold)
    if allow_fallback and (lower is None or upper is None or benefit is None or harm is None):
        lower, upper, benefit, harm, basis = _fallback_threshold_interval(numeric_features)
    if lower is None or upper is None or benefit is None or harm is None:
        return {
            "threshold_basis": "no_threshold",
            "ci_lower_on_threshold_scale": lower,
            "ci_upper_on_threshold_scale": upper,
            "important_benefit_threshold": benefit,
            "important_harm_threshold": harm,
            "ci_zone_lower": "unknown",
            "ci_zone_upper": "unknown",
            "crosses_decision_threshold": False,
            "crosses_both_important_benefit_and_harm": False,
            "entire_ci_important_benefit": False,
            "entire_ci_important_harm": False,
            "includes_important_benefit": False,
            "includes_important_harm": False,
        }
    lower_zone = _decision_zone(lower, benefit, harm)
    upper_zone = _decision_zone(upper, benefit, harm)
    threshold_low = min(benefit, harm)
    threshold_high = max(benefit, harm)
    return {
        "threshold_basis": basis,
        "ci_lower_on_threshold_scale": lower,
        "ci_upper_on_threshold_scale": upper,
        "important_benefit_threshold": benefit,
        "important_harm_threshold": harm,
        "lower_decision_threshold": threshold_low,
        "upper_decision_threshold": threshold_high,
        "ci_zone_lower": lower_zone,
        "ci_zone_upper": upper_zone,
        "crosses_decision_threshold": lower_zone != upper_zone,
        "crosses_both_important_benefit_and_harm": lower <= threshold_low and upper >= threshold_high,
        "entire_ci_important_benefit": _ci_entirely_in_semantic_zone(lower, upper, benefit, harm, "important_benefit"),
        "entire_ci_important_harm": _ci_entirely_in_semantic_zone(lower, upper, benefit, harm, "important_harm"),
        "includes_important_benefit": lower <= benefit <= upper if benefit < harm else lower <= benefit <= upper,
        "includes_important_harm": lower <= harm <= upper if benefit < harm else lower <= harm <= upper,
    }


def _validated_threshold_interval(numeric_features: dict[str, Any], threshold: dict[str, Any]) -> tuple[float | None, float | None, float | None, float | None, str]:
    if threshold.get("threshold_valid") is False:
        return None, None, None, None, "invalid_threshold"
    scale = str(threshold.get("threshold_scale") or "")
    if scale == "absolute_risk_difference_per_1000":
        lower = as_float(numeric_features.get("absolute_ci_lower_per_1000"))
        upper = as_float(numeric_features.get("absolute_ci_upper_per_1000"))
        benefit = as_float(threshold.get("important_benefit"))
        harm = as_float(threshold.get("important_harm"))
        if lower is not None and upper is not None and benefit is not None and harm is not None:
            return lower, upper, benefit, harm, "absolute_threshold"
    if scale == "ratio":
        lower = as_float(numeric_features.get("ci_lower"))
        upper = as_float(numeric_features.get("ci_upper"))
        benefit = as_float(threshold.get("important_benefit"))
        harm = as_float(threshold.get("important_harm"))
        if lower is not None and upper is not None and benefit is not None and harm is not None:
            return lower, upper, benefit, harm, "ratio_threshold"
    if scale == "continuous_mid":
        lower = as_float(numeric_features.get("ci_lower"))
        upper = as_float(numeric_features.get("ci_upper"))
        benefit = as_float(threshold.get("important_benefit"))
        harm = as_float(threshold.get("important_harm"))
        if lower is not None and upper is not None and benefit is not None and harm is not None:
            return lower, upper, benefit, harm, "continuous_mid_threshold"
    return None, None, None, None, "no_valid_threshold"


def _fallback_threshold_interval(numeric_features: dict[str, Any]) -> tuple[float | None, float | None, float | None, float | None, str]:
    effect_measure = str(numeric_features.get("effect_measure") or "")
    lower = as_float(numeric_features.get("ci_lower"))
    upper = as_float(numeric_features.get("ci_upper"))
    if is_ratio_measure(effect_measure) and lower is not None and upper is not None:
        return lower, upper, RATIO_IMPORTANT_BENEFIT, RATIO_IMPORTANT_HARM, "fallback_ratio_threshold"

    abs_lower = as_float(numeric_features.get("absolute_ci_lower_per_1000"))
    abs_upper = as_float(numeric_features.get("absolute_ci_upper_per_1000"))
    if abs_lower is not None and abs_upper is not None:
        return (
            abs_lower,
            abs_upper,
            -DEFAULT_ABSOLUTE_THRESHOLD_PER_1000,
            DEFAULT_ABSOLUTE_THRESHOLD_PER_1000,
            "fallback_absolute_threshold",
        )
    return None, None, None, None, "no_threshold"


def _large_effect(numeric_features: dict[str, Any], threshold_assessment: dict[str, Any]) -> bool:
    effect = as_float(numeric_features.get("effect"))
    basis = str(threshold_assessment.get("threshold_basis") or "")
    benefit = as_float(threshold_assessment.get("important_benefit_threshold"))
    harm = as_float(threshold_assessment.get("important_harm_threshold"))
    if effect is None or benefit is None or harm is None:
        return False
    if "ratio" in basis:
        return effect <= benefit or effect >= harm
    no_effect = as_float(numeric_features.get("no_effect"))
    return bool(no_effect is not None and abs(effect - no_effect) >= min(abs(benefit), abs(harm)))


def _should_downgrade_two_levels(
    threshold_assessment: dict[str, Any],
    ois_assessment: dict[str, Any],
    numeric_features: dict[str, Any],
) -> bool:
    if not threshold_assessment.get("crosses_both_important_benefit_and_harm"):
        return False
    if ois_assessment.get("severity") == "very_serious":
        return True
    return bool(ois_assessment.get("severity") == "serious" and _is_very_wide(numeric_features))


def _should_downgrade_for_ois_only(ois_assessment: dict[str, Any], numeric_features: dict[str, Any]) -> bool:
    if ois_assessment.get("severity") == "very_serious":
        return True
    if ois_assessment.get("severity") != "serious":
        return False
    return _is_very_wide(numeric_features) or ois_assessment.get("reason") in {
        "low_participant_count",
        "single_study_limited_information_size",
        "threshold_source_reports_ois_concern",
    }


def _decision_zone(value: float, benefit: float, harm: float) -> str:
    if benefit < harm:
        if value <= benefit:
            return "important_benefit"
        if value >= harm:
            return "important_harm"
        return "trivial_or_small"
    if value >= benefit:
        return "important_benefit"
    if value <= harm:
        return "important_harm"
    return "trivial_or_small"


def _ci_entirely_in_semantic_zone(lower: float, upper: float, benefit: float, harm: float, zone: str) -> bool:
    return _decision_zone(lower, benefit, harm) == zone and _decision_zone(upper, benefit, harm) == zone


def _ci_includes_important_effect(threshold_assessment: dict[str, Any]) -> bool:
    return bool(
        threshold_assessment.get("includes_important_benefit")
        or threshold_assessment.get("includes_important_harm")
        or threshold_assessment.get("entire_ci_important_benefit")
        or threshold_assessment.get("entire_ci_important_harm")
    )


def _low_confidence_threshold_assessment(threshold_assessment: dict[str, Any]) -> bool:
    return str(threshold_assessment.get("threshold_basis") or "").startswith("low_confidence_")


def _absolute_ci_width_may_be_decision_changing(numeric_features: dict[str, Any]) -> bool:
    lower = as_float(numeric_features.get("absolute_ci_lower_per_1000"))
    upper = as_float(numeric_features.get("absolute_ci_upper_per_1000"))
    if lower is None or upper is None:
        return False
    return max(abs(lower), abs(upper)) >= DEFAULT_ABSOLUTE_THRESHOLD_PER_1000


def _is_very_wide(numeric_features: dict[str, Any]) -> bool:
    lower = as_float(numeric_features.get("ci_lower"))
    upper = as_float(numeric_features.get("ci_upper"))
    effect_measure = str(numeric_features.get("effect_measure") or "")
    if lower is None or upper is None:
        return False
    if is_ratio_measure(effect_measure):
        return lower > 0 and upper / lower >= 4
    return abs(upper - lower) >= 1


def _with_debug(
    payload: dict[str, Any],
    *,
    setting_context: dict[str, Any],
    numeric_features: dict[str, Any],
    threshold: dict[str, Any],
    decision_features: dict[str, Any],
) -> dict[str, Any]:
    payload["debug"] = {
        "setting_context": setting_context,
        "numeric_features": numeric_features,
        "threshold_result": threshold,
        "decision_features": decision_features,
    }
    return payload
