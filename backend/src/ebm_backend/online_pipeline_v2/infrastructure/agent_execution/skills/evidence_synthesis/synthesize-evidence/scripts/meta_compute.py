#!/usr/bin/env python3
"""Deterministic intervention-review meta-analysis core.

The input is one JSON analysis specification. The output contains study,
subgroup, and overall estimates plus complete statistical diagnostics. This
module never selects studies or methods.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Iterable

import numpy as np
from scipy.optimize import brentq
from scipy.stats import chi2, norm, t


_RATIO_MEASURES = {"RR", "OR", "RATIO", "LOG_OR", "LOG_HR"}
_ENGINE_ID = "ebm-scipy-intervention-meta"
_ENGINE_VERSION = "meta-compute.v2"


class MetaComputationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def compute_meta_analysis(specification: dict[str, Any]) -> dict[str, Any]:
    settings = _settings(specification)
    studies, warnings = _study_effects(specification, settings)
    if not studies:
        raise MetaComputationError(
            "no_usable_studies",
            "no studies remain after deterministic validity rules",
        )
    subgroups: list[dict[str, Any]] = []
    subgroup_names = list(dict.fromkeys(item["subgroup"] for item in studies))
    for name in subgroup_names:
        members = [item for item in studies if item["subgroup"] == name]
        subgroup_settings = {**settings, "prediction_interval": False}
        if len(members) == 1 and settings["analysis_model"] == "random":
            subgroup_settings.update(
                {
                    "analysis_model": "fixed",
                    "ci_method": "WALD",
                    "tau2_ci": False,
                }
            )
        pooled = _pool(
            members,
            subgroup_settings,
        )
        if len(members) == 1 and settings["analysis_model"] == "random":
            pooled["inference_note"] = (
                "Single-Study subgroup: no within-subgroup tau-squared "
                "estimate; the Study estimate and Wald interval are shown."
            )
        pooled["subgroup"] = name
        subgroups.append(pooled)
    overall = _pool(studies, settings)
    if settings["ci_method"] == "HKSJ" and overall["tau2"] == 0:
        warnings.append(
            "HKSJ with estimated tau-squared equal to zero can yield an "
            "overly narrow confidence interval; retain this method only when "
            "it is protocol-selected and review the sensitivity."
        )
    subgroup_difference = _subgroup_difference(subgroups)
    weights = np.asarray(overall.pop("_weights"), dtype=float)
    total_weight = float(weights.sum())
    for study, weight in zip(studies, weights, strict=True):
        study["weight_percent"] = float(100 * weight / total_weight)
        study["estimate"] = _display(float(study["yi"]), settings)
        study["ci_start"] = _display(
            float(study["yi"] - settings["critical_normal"] * math.sqrt(study["vi"])),
            settings,
        )
        study["ci_end"] = _display(
            float(study["yi"] + settings["critical_normal"] * math.sqrt(study["vi"])),
            settings,
        )
    for subgroup in subgroups:
        subgroup["weight_percent"] = float(
            100
            * sum(
                weight
                for study, weight in zip(studies, weights, strict=True)
                if study["subgroup"] == subgroup["subgroup"]
            )
            / total_weight
        )
        subgroup.pop("_weights", None)
    canonical_input = json.dumps(
        specification,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    result = {
        "schema_version": "meta-compute-output.v2",
        "engine_id": _ENGINE_ID,
        "engine_version": _ENGINE_VERSION,
        "settings": {
            key: value
            for key, value in settings.items()
            if key not in {"critical_normal", "alpha"}
        },
        "studies": studies,
        "subgroups": subgroups,
        "overall": overall,
        "subgroup_difference": subgroup_difference,
        "warnings": tuple(dict.fromkeys(warnings)),
        "input_digest": f"sha256:{sha256(canonical_input).hexdigest()}",
    }
    output_bytes = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    result["output_digest"] = f"sha256:{sha256(output_bytes).hexdigest()}"
    return result


def _settings(specification: dict[str, Any]) -> dict[str, Any]:
    data_type = str(specification.get("data_type", "")).lower()
    if data_type not in {"dichotomous", "continuous", "giv", "oev"}:
        raise MetaComputationError(
            "unsupported_data_type",
            f"unsupported data_type: {data_type}",
        )
    measure = str(specification.get("effect_measure", "")).upper()
    allowed = {
        "dichotomous": {"RR", "OR", "RD"},
        "continuous": {"MD", "SMD"},
        "giv": {"DIFFERENCE", "RATIO", "LOG_OR", "LOG_HR"},
        "oev": {"LOG_OR", "LOG_HR"},
    }[data_type]
    if measure not in allowed:
        raise MetaComputationError(
            "unsupported_effect_measure",
            f"{measure} is not supported for {data_type}",
        )
    method = str(specification.get("statistical_method", "IV")).upper()
    if method not in {"IV", "MH", "PETO"}:
        raise MetaComputationError(
            "unsupported_statistical_method",
            f"unsupported statistical method: {method}",
        )
    if method == "PETO" and not (data_type == "dichotomous" and measure == "OR"):
        raise MetaComputationError(
            "invalid_peto_use",
            "Peto is supported only for dichotomous odds ratios",
        )
    if method == "MH" and data_type != "dichotomous":
        raise MetaComputationError(
            "invalid_mh_use",
            "Mantel-Haenszel is supported only for dichotomous data",
        )
    model = str(specification.get("analysis_model", "fixed")).lower()
    if model not in {"fixed", "random"}:
        raise MetaComputationError(
            "unsupported_analysis_model",
            f"unsupported analysis_model: {model}",
        )
    if data_type == "oev" and model != "fixed":
        raise MetaComputationError(
            "unsupported_oev_random",
            "O-E and V synthesis is fixed-effect only",
        )
    if method == "PETO" and model != "fixed":
        raise MetaComputationError(
            "unsupported_peto_random",
            "Peto odds ratio is fixed-effect only",
        )
    if method == "MH" and model != "fixed":
        raise MetaComputationError(
            "unsupported_mh_random",
            "Mantel-Haenszel is fixed-effect only in the supported "
            "Cochrane intervention-review method matrix",
        )
    tau_method = str(specification.get("heterogeneity_estimator", "REML")).upper()
    if tau_method not in {"REML", "DL"}:
        raise MetaComputationError(
            "unsupported_tau_estimator",
            f"unsupported heterogeneity estimator: {tau_method}",
        )
    ci_method = str(specification.get("ci_method", "Wald")).upper()
    if ci_method not in {"WALD", "HKSJ"}:
        raise MetaComputationError(
            "unsupported_ci_method",
            f"unsupported CI method: {ci_method}",
        )
    if ci_method == "HKSJ" and model != "random":
        raise MetaComputationError(
            "hksj_requires_random",
            "HKSJ is supported only for random-effects synthesis",
        )
    level = _number(specification, "confidence_level", default=0.95)
    if not 0 < level < 1:
        raise MetaComputationError(
            "invalid_confidence_level",
            "confidence_level must be between zero and one",
        )
    return {
        "data_type": data_type,
        "effect_measure": measure,
        "statistical_method": method,
        "analysis_model": model,
        "heterogeneity_estimator": tau_method,
        "ci_method": ci_method,
        "confidence_level": level,
        "prediction_interval": bool(specification.get("prediction_interval", False)),
        "tau2_ci": bool(specification.get("tau2_ci", False)),
        "alpha": 1 - level,
        "critical_normal": float(norm.ppf(0.5 + level / 2)),
    }


def _study_effects(
    specification: dict[str, Any],
    settings: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    raw = specification.get("studies")
    if not isinstance(raw, list) or not raw:
        raise MetaComputationError(
            "missing_studies",
            "studies must be a non-empty list",
        )
    studies: list[dict[str, Any]] = []
    warnings: list[str] = []
    identifiers: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise MetaComputationError(
                "invalid_study",
                "every study must be an object",
            )
        study_id = str(item.get("study_id", "")).strip()
        if not study_id or study_id in identifiers:
            raise MetaComputationError(
                "invalid_study_id",
                "study_id values must be nonblank and unique",
            )
        identifiers.add(study_id)
        effect = _one_effect(item, settings)
        if effect is None:
            warnings.append(
                f"{study_id}: excluded as uninformative under zero-cell rules"
            )
            continue
        effect.update(
            {
                "study_id": study_id,
                "subgroup": str(item.get("subgroup", "Main analysis")).strip()
                or "Main analysis",
            }
        )
        studies.append(effect)
    if settings["statistical_method"] == "PETO":
        warnings.append(
            "Peto odds ratio can be biased with large effects, imbalanced "
            "allocation, or non-rare events; protocol assumptions require review."
        )
    return studies, warnings


def _one_effect(
    study: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any] | None:
    data_type = settings["data_type"]
    measure = settings["effect_measure"]
    if data_type == "dichotomous":
        a = _integer(study, "experimental_cases")
        n1 = _integer(study, "experimental_n", positive=True)
        c = _integer(study, "control_cases")
        n0 = _integer(study, "control_n", positive=True)
        if a > n1 or c > n0:
            raise MetaComputationError(
                "invalid_event_count",
                "events must be between zero and sample size",
            )
        b = n1 - a
        d = n0 - c
        totals = {
            "experimental_cases": a,
            "experimental_n": n1,
            "control_cases": c,
            "control_n": n0,
        }
        if measure in {"RR", "OR"} and ((a == 0 and c == 0) or (b == 0 and d == 0)):
            return None
        if settings["statistical_method"] == "PETO":
            total = n1 + n0
            events = a + c
            if total <= 1 or events in {0, total}:
                return None
            expected = n1 * events / total
            variance = (
                n1 * n0 * events * (total - events) / (total * total * (total - 1))
            )
            if variance <= 0:
                return None
            return {
                "yi": (a - expected) / variance,
                "vi": 1 / variance,
                "oe": a - expected,
                "oe_variance": variance,
                **totals,
            }
        if measure == "RD":
            p1 = a / n1
            p0 = c / n0
            variance = p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0
            if variance <= 0:
                aa, bb, cc, dd = a + 0.5, b + 0.5, c + 0.5, d + 0.5
                corrected_n1, corrected_n0 = aa + bb, cc + dd
                p1 = aa / corrected_n1
                p0 = cc / corrected_n0
                variance = p1 * (1 - p1) / corrected_n1 + p0 * (1 - p0) / corrected_n0
                return {
                    "yi": p1 - p0,
                    "vi": variance,
                    "continuity_correction": 0.5,
                    **totals,
                }
            return {
                "yi": p1 - p0,
                "vi": variance,
                "continuity_correction": 0.0,
                **totals,
            }
        corrected = any(value == 0 for value in (a, b, c, d))
        aa, bb, cc, dd = (
            (a + 0.5, b + 0.5, c + 0.5, d + 0.5)
            if corrected
            else (float(a), float(b), float(c), float(d))
        )
        if measure == "RR":
            yi = math.log((aa / (aa + bb)) / (cc / (cc + dd)))
            variance = 1 / aa - 1 / (aa + bb) + 1 / cc - 1 / (cc + dd)
        else:
            yi = math.log((aa * dd) / (bb * cc))
            variance = 1 / aa + 1 / bb + 1 / cc + 1 / dd
        return {
            "yi": yi,
            "vi": variance,
            "continuity_correction": 0.5 if corrected else 0.0,
            **totals,
        }
    if data_type == "continuous":
        n1 = _integer(study, "experimental_n", positive=True)
        n0 = _integer(study, "control_n", positive=True)
        m1 = _number(study, "experimental_mean")
        m0 = _number(study, "control_mean")
        sd1 = _positive(study, "experimental_sd")
        sd0 = _positive(study, "control_sd")
        if measure == "MD":
            yi = m1 - m0
            variance = sd1 * sd1 / n1 + sd0 * sd0 / n0
        else:
            degrees = n1 + n0 - 2
            if degrees <= 0:
                raise MetaComputationError(
                    "invalid_smd_degrees",
                    "SMD requires at least two total residual degrees of freedom",
                )
            pooled = math.sqrt(((n1 - 1) * sd1 * sd1 + (n0 - 1) * sd0 * sd0) / degrees)
            if pooled <= 0:
                raise MetaComputationError(
                    "invalid_pooled_sd",
                    "SMD pooled SD must be positive",
                )
            correction = 1 - 3 / (4 * degrees - 1)
            yi = correction * (m1 - m0) / pooled
            variance = (n1 + n0) / (n1 * n0) + yi * yi / (2 * (n1 + n0 - 3.94))
        return {
            "yi": yi,
            "vi": variance,
            "experimental_n": n1,
            "control_n": n0,
        }
    if data_type == "giv":
        estimate = _number(study, "effect")
        has_se = "se" in study and study["se"] is not None
        has_variance = "variance" in study and study["variance"] is not None
        if has_se == has_variance:
            raise MetaComputationError(
                "invalid_giv_uncertainty",
                "GIV Study input requires exactly one of se or variance",
            )
        if has_se:
            se = _positive(study, "se")
            variance = se * se
        else:
            variance = _positive(study, "variance")
        return {"yi": estimate, "vi": variance}
    oe = _number(study, "o_minus_e")
    variance = _positive(study, "variance")
    return {
        "yi": oe / variance,
        "vi": 1 / variance,
        "oe": oe,
        "oe_variance": variance,
    }


def _pool(
    studies: list[dict[str, Any]],
    settings: dict[str, Any],
) -> dict[str, Any]:
    k = len(studies)
    if k == 0:
        raise MetaComputationError("empty_pool", "cannot pool zero studies")
    yi = np.asarray([item["yi"] for item in studies], dtype=float)
    vi = np.asarray([item["vi"] for item in studies], dtype=float)
    fixed_weights = 1 / vi
    reference = _fixed_reference(studies, settings)
    q = float(np.sum(fixed_weights * (yi - reference["mu"]) ** 2))
    degrees = k - 1
    if settings["analysis_model"] == "random":
        if k < 2:
            raise MetaComputationError(
                "random_single_study",
                "random-effects synthesis requires at least two studies",
            )
        if settings["heterogeneity_estimator"] == "DL":
            tau2 = _tau2_dl(yi, vi, reference["mu"])
        else:
            tau2 = _tau2_reml(yi, vi)
        weights = 1 / (vi + tau2)
        mu = float(np.sum(weights * yi) / np.sum(weights))
        base_se = math.sqrt(1 / float(np.sum(weights)))
    else:
        tau2 = 0.0
        weights = _fixed_display_weights(studies, settings)
        mu = reference["mu"]
        base_se = math.sqrt(reference["variance"])
    if settings["ci_method"] == "HKSJ":
        if k < 2:
            raise MetaComputationError(
                "hksj_insufficient_studies",
                "HKSJ requires at least two studies",
            )
        residual = float(np.sum(weights * (yi - mu) ** 2))
        se = math.sqrt(residual / degrees / float(np.sum(weights)))
        critical = float(t.ppf(1 - settings["alpha"] / 2, degrees))
        statistic = mu / se if se > 0 else math.inf
        effect_p = float(2 * t.sf(abs(statistic), degrees))
        statistic_name = "T"
    else:
        se = base_se
        critical = settings["critical_normal"]
        statistic = mu / se if se > 0 else math.inf
        effect_p = float(2 * norm.sf(abs(statistic)))
        statistic_name = "Z"
    lower = mu - critical * se
    upper = mu + critical * se
    prediction = None
    if settings["prediction_interval"]:
        if settings["analysis_model"] != "random":
            raise MetaComputationError(
                "prediction_interval_fixed",
                "prediction intervals require a random-effects model",
            )
        if k < 3:
            raise MetaComputationError(
                "prediction_interval_insufficient_studies",
                "prediction intervals require at least three studies",
            )
        prediction_critical = float(t.ppf(1 - settings["alpha"] / 2, k - 2))
        spread = prediction_critical * math.sqrt(tau2 + se * se)
        prediction = {
            "start": _display(mu - spread, settings),
            "end": _display(mu + spread, settings),
        }
    tau_interval = None
    if settings["tau2_ci"]:
        tau_interval = _tau2_q_profile(yi, vi, settings["alpha"])
    result = {
        "study_count": k,
        "estimate": _display(mu, settings),
        "analysis_scale_estimate": mu,
        "standard_error": se,
        "ci_start": _display(lower, settings),
        "ci_end": _display(upper, settings),
        "prediction_interval": prediction,
        "tau2": tau2,
        "tau2_ci": tau_interval,
        "heterogeneity_q": q,
        "heterogeneity_df": degrees,
        "heterogeneity_p": (float(chi2.sf(q, degrees)) if degrees > 0 else None),
        "i2": (max(0.0, (q - degrees) / q) * 100 if degrees > 0 and q > 0 else 0.0),
        "effect_statistic_name": statistic_name,
        "effect_statistic": statistic,
        "effect_p": effect_p,
        "_weights": weights.tolist(),
        "_analysis_variance": se * se,
    }
    totals = _event_totals(studies)
    if totals:
        result.update(totals)
    return result


def _fixed_reference(
    studies: list[dict[str, Any]],
    settings: dict[str, Any],
) -> dict[str, float]:
    method = settings["statistical_method"]
    if method == "MH":
        return _mantel_haenszel(studies, settings["effect_measure"])
    yi = np.asarray([item["yi"] for item in studies], dtype=float)
    vi = np.asarray([item["vi"] for item in studies], dtype=float)
    weights = 1 / vi
    return {
        "mu": float(np.sum(weights * yi) / np.sum(weights)),
        "variance": float(1 / np.sum(weights)),
    }


def _mantel_haenszel(
    studies: list[dict[str, Any]],
    measure: str,
) -> dict[str, float]:
    rows = _mh_rows(studies)
    if measure == "RR":
        numerator = sum(a * n0 / total for a, _, _, _, _, n0, total in rows)
        denominator = sum(c * n1 / total for _, _, c, _, n1, _, total in rows)
        if numerator <= 0 or denominator <= 0:
            rows = _correct_mh_rows(rows)
            numerator = sum(a * n0 / total for a, _, _, _, _, n0, total in rows)
            denominator = sum(c * n1 / total for _, _, c, _, n1, _, total in rows)
        if numerator <= 0 or denominator <= 0:
            raise MetaComputationError(
                "mh_rr_undefined",
                "Mantel-Haenszel risk ratio is undefined",
            )
        variance_numerator = sum(
            (n1 * n0 * (a + c) / (total * total) - a * c / total)
            for a, _, c, _, n1, n0, total in rows
        )
        variance = variance_numerator / (numerator * denominator)
        return {"mu": math.log(numerator / denominator), "variance": variance}
    if measure == "OR":
        r_value = sum(a * d / total for a, _, _, d, _, _, total in rows)
        s_value = sum(b * c / total for _, b, c, _, _, _, total in rows)
        if r_value <= 0 or s_value <= 0:
            rows = _correct_mh_rows(rows)
            r_value = sum(a * d / total for a, _, _, d, _, _, total in rows)
            s_value = sum(b * c / total for _, b, c, _, _, _, total in rows)
        if r_value <= 0 or s_value <= 0:
            raise MetaComputationError(
                "mh_or_undefined",
                "Mantel-Haenszel odds ratio is undefined",
            )
        p_value = sum(
            (a + d) * a * d / (total * total) for a, _, _, d, _, _, total in rows
        )
        q_value = sum(
            (b + c) * b * c / (total * total) for _, b, c, _, _, _, total in rows
        )
        middle = sum(
            ((a + d) * b * c + (b + c) * a * d) / (total * total)
            for a, b, c, d, _, _, total in rows
        )
        variance = (
            p_value / (2 * r_value * r_value)
            + middle / (2 * r_value * s_value)
            + q_value / (2 * s_value * s_value)
        )
        return {"mu": math.log(r_value / s_value), "variance": variance}
    weights = np.asarray([n1 * n0 / total for *_, n1, n0, total in rows])
    differences = np.asarray([a / n1 - c / n0 for a, _, c, _, n1, n0, _ in rows])
    variances = np.asarray(
        [
            (a / n1) * (1 - a / n1) / n1 + (c / n0) * (1 - c / n0) / n0
            for a, _, c, _, n1, n0, _ in rows
        ]
    )
    return {
        "mu": float(np.sum(weights * differences) / np.sum(weights)),
        "variance": float(np.sum(weights * weights * variances) / np.sum(weights) ** 2),
    }


def _fixed_display_weights(
    studies: list[dict[str, Any]],
    settings: dict[str, Any],
) -> np.ndarray:
    method = settings["statistical_method"]
    if method != "MH":
        return np.asarray([1 / item["vi"] for item in studies], dtype=float)
    measure = settings["effect_measure"]
    rows = _mh_rows(studies)
    if measure == "RR":
        weights = np.asarray(
            [c * n1 / total for _, _, c, _, n1, _, total in rows],
            dtype=float,
        )
    elif measure == "OR":
        weights = np.asarray(
            [b * c / total for _, b, c, _, _, _, total in rows],
            dtype=float,
        )
    else:
        weights = np.asarray(
            [n1 * n0 / total for *_, n1, n0, total in rows],
            dtype=float,
        )
    if float(np.sum(weights)) <= 0:
        rows = _correct_mh_rows(rows)
        if measure == "RR":
            weights = np.asarray(
                [c * n1 / total for _, _, c, _, n1, _, total in rows],
                dtype=float,
            )
        elif measure == "OR":
            weights = np.asarray(
                [b * c / total for _, b, c, _, _, _, total in rows],
                dtype=float,
            )
    return weights


def _mh_rows(
    studies: list[dict[str, Any]],
) -> list[tuple[float, float, float, float, float, float, float]]:
    rows = []
    for item in studies:
        a = float(item["experimental_cases"])
        n1 = float(item["experimental_n"])
        c = float(item["control_cases"])
        n0 = float(item["control_n"])
        b = n1 - a
        d = n0 - c
        if item.get("continuity_correction") == 0.5:
            a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
            n1, n0 = a + b, c + d
        rows.append((a, b, c, d, n1, n0, n1 + n0))
    return rows


def _correct_mh_rows(
    rows: list[tuple[float, float, float, float, float, float, float]],
) -> list[tuple[float, float, float, float, float, float, float]]:
    corrected = []
    for a, b, c, d, _, _, _ in rows:
        aa, bb, cc, dd = a + 0.5, b + 0.5, c + 0.5, d + 0.5
        n1, n0 = aa + bb, cc + dd
        corrected.append((aa, bb, cc, dd, n1, n0, n1 + n0))
    return corrected


def _tau2_dl(yi: np.ndarray, vi: np.ndarray, reference: float) -> float:
    weights = 1 / vi
    q = float(np.sum(weights * (yi - reference) ** 2))
    denominator = float(np.sum(weights) - np.sum(weights * weights) / np.sum(weights))
    if denominator <= 0:
        raise MetaComputationError(
            "dl_invalid_denominator",
            "DL heterogeneity denominator is not positive",
        )
    return max(0.0, (q - (len(yi) - 1)) / denominator)


def _tau2_reml(yi: np.ndarray, vi: np.ndarray) -> float:
    def score(tau2: float) -> float:
        weights = 1 / (vi + tau2)
        mean = float(np.sum(weights * yi) / np.sum(weights))
        residual = yi - mean
        return float(
            np.sum(weights * weights * residual * residual)
            - np.sum(weights)
            + np.sum(weights * weights) / np.sum(weights)
        )

    if score(0.0) <= 0:
        return 0.0
    upper = max(float(np.var(yi, ddof=1)), float(np.max(vi)), 1e-8)
    for _ in range(80):
        if score(upper) < 0:
            try:
                return float(brentq(score, 0.0, upper, maxiter=500))
            except ValueError as exc:
                raise MetaComputationError(
                    "reml_nonconvergence",
                    "REML root finding did not converge",
                ) from exc
        upper *= 2
    raise MetaComputationError(
        "reml_nonconvergence",
        "REML score did not bracket a finite solution",
    )


def _tau2_q_profile(
    yi: np.ndarray,
    vi: np.ndarray,
    alpha: float,
) -> dict[str, float] | None:
    degrees = len(yi) - 1
    if degrees <= 0:
        return None

    def q_at(tau2: float) -> float:
        weights = 1 / (vi + tau2)
        mean = float(np.sum(weights * yi) / np.sum(weights))
        return float(np.sum(weights * (yi - mean) ** 2))

    q_zero = q_at(0.0)
    high_target = float(chi2.ppf(1 - alpha / 2, degrees))
    low_target = float(chi2.ppf(alpha / 2, degrees))

    def root_for(target: float) -> float:
        if q_zero <= target:
            return 0.0
        upper = max(float(np.var(yi, ddof=1)), float(np.max(vi)), 1e-8)
        for _ in range(100):
            if q_at(upper) < target:
                return float(brentq(lambda value: q_at(value) - target, 0.0, upper))
            upper *= 2
        raise MetaComputationError(
            "q_profile_nonconvergence",
            "Q-profile tau-squared interval did not bracket",
        )

    return {
        "start": root_for(high_target),
        "end": root_for(low_target),
    }


def _subgroup_difference(
    subgroups: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if len(subgroups) < 2:
        return None
    estimates = np.asarray(
        [item["analysis_scale_estimate"] for item in subgroups],
        dtype=float,
    )
    variances = np.asarray(
        [item["_analysis_variance"] for item in subgroups],
        dtype=float,
    )
    if np.any(variances <= 0):
        return None
    weights = 1 / variances
    mean = float(np.sum(weights * estimates) / np.sum(weights))
    statistic = float(np.sum(weights * (estimates - mean) ** 2))
    degrees = len(subgroups) - 1
    return {
        "chi2": statistic,
        "df": degrees,
        "p": float(chi2.sf(statistic, degrees)),
        "i2": (
            max(0.0, (statistic - degrees) / statistic) * 100 if statistic > 0 else 0.0
        ),
    }


def _event_totals(studies: Iterable[dict[str, Any]]) -> dict[str, int]:
    rows = list(studies)
    keys = (
        "experimental_cases",
        "experimental_n",
        "control_cases",
        "control_n",
    )
    if not rows or any(key not in row for row in rows for key in keys):
        return {}
    return {key: int(sum(row[key] for row in rows)) for key in keys}


def _display(value: float, settings: dict[str, Any]) -> float:
    if (
        settings["effect_measure"] in _RATIO_MEASURES
        or settings["effect_measure"] == "RR"
        or (
            settings["data_type"] == "dichotomous"
            and settings["effect_measure"] == "OR"
        )
    ):
        return math.exp(value)
    return value


def _number(
    values: dict[str, Any],
    name: str,
    *,
    default: float | None = None,
) -> float:
    if name not in values and default is not None:
        return default
    if isinstance(values.get(name), bool):
        raise MetaComputationError(
            "invalid_numeric_input",
            f"{name} must be numeric",
        )
    try:
        result = float(values[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise MetaComputationError(
            "invalid_numeric_input",
            f"{name} must be numeric",
        ) from exc
    if not math.isfinite(result):
        raise MetaComputationError(
            "invalid_numeric_input",
            f"{name} must be finite",
        )
    return result


def _positive(values: dict[str, Any], name: str) -> float:
    result = _number(values, name)
    if result <= 0:
        raise MetaComputationError(
            "invalid_positive_input",
            f"{name} must be positive",
        )
    return result


def _integer(
    values: dict[str, Any],
    name: str,
    *,
    positive: bool = False,
) -> int:
    value = _number(values, name)
    if not value.is_integer() or value < (1 if positive else 0):
        requirement = "a positive integer" if positive else "a non-negative integer"
        raise MetaComputationError(
            "invalid_integer_input",
            f"{name} must be {requirement}",
        )
    return int(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        specification = json.loads(arguments.input.read_text(encoding="utf-8"))
        if not isinstance(specification, dict):
            raise MetaComputationError(
                "invalid_input",
                "input must be a JSON object",
            )
        result = compute_meta_analysis(specification)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _write_json(
            arguments.output,
            {
                "schema_version": "meta-compute-error.v1",
                "status": "error",
                "engine_id": _ENGINE_ID,
                "engine_version": _ENGINE_VERSION,
                "error": {
                    "code": "invalid_input_document",
                    "message": str(exc),
                },
            },
        )
        raise SystemExit(2) from None
    except MetaComputationError as exc:
        _write_json(
            arguments.output,
            {
                "schema_version": "meta-compute-error.v1",
                "status": "error",
                "engine_id": _ENGINE_ID,
                "engine_version": _ENGINE_VERSION,
                "error": {"code": exc.code, "message": str(exc)},
            },
        )
        raise SystemExit(2) from None
    _write_json(arguments.output, result)


def _write_json(output: Path, value: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(output)


if __name__ == "__main__":
    main()
