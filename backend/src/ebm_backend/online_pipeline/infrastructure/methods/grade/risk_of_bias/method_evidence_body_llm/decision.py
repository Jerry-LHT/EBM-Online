"""Validate semantic output and derive the stable GRADE domain judgement."""

from __future__ import annotations

from typing import Any

from ebm_backend.online_pipeline.domain.grade import GRADERiskOfBiasInput


_REQUIRED_FIELDS = {
    "assessment_status",
    "severity",
    "rationale",
    "driving_evidence",
}
_SEVERITY_TO_OUTPUT = {
    "not_serious": ("no", "not_serious", 0, True),
    "serious": ("yes", "serious", 1, True),
    "very_serious": ("yes", "very_serious", 2, True),
}


def judgement_from_llm(
    parsed: dict[str, Any],
    *,
    grade_input: GRADERiskOfBiasInput,
) -> dict[str, Any]:
    if set(parsed) != _REQUIRED_FIELDS:
        raise ValueError(
            "GRADE risk-of-bias LLM output must contain exactly the required fields"
        )
    status = str(parsed.get("assessment_status") or "").strip()
    severity = parsed.get("severity")
    rationale = str(parsed.get("rationale") or "").strip()
    if status not in {"completed", "not_evaluable"}:
        raise ValueError("Unsupported GRADE risk-of-bias assessment_status")
    if not rationale:
        raise ValueError("GRADE risk-of-bias rationale must not be empty")
    if status == "not_evaluable":
        if severity is not None:
            raise ValueError(
                "not_evaluable GRADE risk-of-bias output must use null severity"
            )
        _validated_drivers(parsed.get("driving_evidence"), grade_input=grade_input)
        return not_evaluable_judgement(rationale)
    severity_text = str(severity or "").strip()
    if severity_text not in _SEVERITY_TO_OUTPUT:
        raise ValueError("Unsupported completed GRADE risk-of-bias severity")
    drivers = _validated_drivers(
        parsed.get("driving_evidence"), grade_input=grade_input
    )
    if severity_text in {"serious", "very_serious"} and not drivers:
        raise ValueError(
            "Downgraded GRADE risk-of-bias output must identify driving evidence"
        )
    downgraded, output_severity, levels, level_evaluable = _SEVERITY_TO_OUTPUT[
        severity_text
    ]
    return {
        "domain": "risk_of_bias",
        "assessment_status": "assessed",
        "downgraded": downgraded,
        "severity": output_severity,
        "levels": levels,
        "level_evaluable": level_evaluable,
        "rationale": rationale,
        "source_spans": [],
    }


def not_evaluable_judgement(rationale: str) -> dict[str, Any]:
    return {
        "domain": "risk_of_bias",
        "assessment_status": "insufficient_evidence",
        "downgraded": "unclear",
        "severity": "unclear",
        "levels": "unclear",
        "level_evaluable": False,
        "rationale": rationale,
        "source_spans": [],
    }


def _validated_drivers(
    value: Any,
    *,
    grade_input: GRADERiskOfBiasInput,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("GRADE risk-of-bias driving_evidence must be a list")
    domains_by_study = {
        study.study_id: set(study.assessed_domains)
        for study in grade_input.contributing_studies
        if study.rob_available
    }
    validated: list[dict[str, Any]] = []
    seen_studies: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"study_id", "domains"}:
            raise ValueError("Invalid GRADE risk-of-bias driving evidence object")
        study_id = str(item.get("study_id") or "").strip()
        domains = item.get("domains")
        if study_id not in domains_by_study:
            raise ValueError(
                "GRADE risk-of-bias driver references a non-contributing study"
            )
        if study_id in seen_studies:
            raise ValueError(
                "GRADE risk-of-bias driving_evidence must not duplicate studies"
            )
        if not isinstance(domains, list) or any(
            not isinstance(domain, str) or not domain.strip() for domain in domains
        ):
            raise ValueError("GRADE risk-of-bias driver domains must be strings")
        normalized_domains = [domain.strip() for domain in domains]
        if len(set(normalized_domains)) != len(normalized_domains):
            raise ValueError("GRADE risk-of-bias driver domains must be unique")
        if not set(normalized_domains).issubset(domains_by_study[study_id]):
            raise ValueError(
                "GRADE risk-of-bias driver references an unassessed domain"
            )
        seen_studies.add(study_id)
        validated.append({"study_id": study_id, "domains": normalized_domains})
    return validated
