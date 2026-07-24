"""Optimal information size signals for GRADE imprecision."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.utils import as_int, norm_text


LOW_EVENT_THRESHOLD = 100
LOW_PARTICIPANT_THRESHOLD = 400
VERY_LOW_EVENT_THRESHOLD = 50


def assess_ois(numeric_features: dict[str, Any], threshold: dict[str, Any]) -> dict[str, Any]:
    """Assess OIS-style information size concerns.

    This is intentionally a deterministic signal extractor. It does not decide
    downgrading by itself; the decision engine combines it with CI and threshold
    crossing logic.
    """

    notes = norm_text(threshold.get("optimal_information_size_notes"))
    if "not_met" in notes or "insufficient" in notes or "underpowered" in notes:
        return {"concern": True, "severity": "serious", "reason": "threshold_source_reports_ois_concern"}

    events = as_int(numeric_features.get("total_events"))
    participants = as_int(numeric_features.get("participant_count"))
    study_count = as_int(numeric_features.get("study_count"))
    data_type = norm_text(numeric_features.get("data_type"))

    if events is not None:
        if events < VERY_LOW_EVENT_THRESHOLD:
            return {"concern": True, "severity": "very_serious", "reason": "very_low_total_events"}
        if events < LOW_EVENT_THRESHOLD:
            return {"concern": True, "severity": "serious", "reason": "low_total_events"}

    if participants is not None and participants < LOW_PARTICIPANT_THRESHOLD and ("continuous" in data_type or events is None):
        return {"concern": True, "severity": "serious", "reason": "low_participant_count"}

    if study_count is not None and study_count <= 1 and participants is not None and participants < 1000:
        return {"concern": True, "severity": "serious", "reason": "single_study_limited_information_size"}

    return {"concern": False, "severity": "none", "reason": "ois_not_triggered"}
